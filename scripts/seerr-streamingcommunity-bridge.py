#!/usr/bin/env python3
"""Route pending Seerr requests through StreamingCommunity before *arr.

Only requests from the configured, non-auto-approving Seerr user are handled.
Uncertain matches remain in StreamingCommunity's native approval queue.
"""

from __future__ import annotations

import json
import hmac
import logging
import os
import queue
import re
import sqlite3
import threading
import time
import unicodedata
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests


LOG = logging.getLogger("seerr-bridge")
OPEN = {"pending", "approved", "downloading", "needs_attention"}
SUCCESS = {"completed", "available"}
FAILURE = {"failed", "denied", "cancelled"}


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}")
    return value


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def year(value: str | None) -> str:
    match = re.match(r"^\d{4}", str(value or ""))
    return match.group() if match else ""


def seerr_title(details: dict, media_type: str) -> tuple[str, str, list[str]]:
    if media_type == "movie":
        title = details.get("title") or details.get("originalTitle") or ""
        other = details.get("originalTitle") or ""
        release = details.get("releaseDate") or details.get("release_date")
    else:
        title = details.get("name") or details.get("originalName") or ""
        other = details.get("originalName") or ""
        release = details.get("firstAirDate") or details.get("first_air_date")
    return title, year(release), list(dict.fromkeys(x for x in (title, other) if x))


def choose(candidates: list[dict], names: list[str], wanted_year: str,
           tmdb_id: int) -> tuple[dict | None, bool]:
    """Return (best result, certain). A weak result is never downloaded."""
    seen = {normalized(name) for name in names if name}
    ranked: list[tuple[float, dict]] = []
    for item in candidates:
        item_year = year(item.get("release_date"))
        same_name = normalized(item.get("name", "")) in seen
        tmdb_match = str(item.get("tmdb_id") or "") == str(tmdb_id)
        similarity = max((SequenceMatcher(None, normalized(item.get("name", "")), n).ratio()
                          for n in seen), default=0.0)
        score = (10 if tmdb_match else 0) + (3 if same_name else similarity)
        if wanted_year and item_year == wanted_year:
            score += 1
        if score >= 0.55:
            ranked.append((score, item))
    if not ranked:
        return None, False
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    best = ranked[0][1]
    certain = bool(str(best.get("tmdb_id") or "") == str(tmdb_id) or
                   (normalized(best.get("name", "")) in seen and
                    wanted_year and year(best.get("release_date")) == wanted_year and
                    (len(ranked) == 1 or ranked[0][0] > ranked[1][0])))
    return best, certain


class Bridge:
    def __init__(self) -> None:
        self.seerr_url = required("SEERR_URL").rstrip("/")
        self.sc_url = required("STREAMINGCOMMUNITY_URL").rstrip("/")
        self.seerr_user_id = int(required("SEERR_REQUEST_USER_ID"))
        self.seerr_key = required("SEERR_API_KEY")
        self.jellyfin_token = required("BRIDGE_JELLYFIN_TOKEN")
        self.webhook_token = required("BRIDGE_WEBHOOK_TOKEN")
        self.db_path = Path(required("BRIDGE_DB"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS work (
            seerr_id INTEGER PRIMARY KEY, state TEXT NOT NULL, media_type TEXT NOT NULL,
            sc_ids TEXT NOT NULL DEFAULT '[]', missing INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL
        )""")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(work)")}
        if "missing" not in columns:
            self.db.execute("ALTER TABLE work ADD COLUMN missing INTEGER NOT NULL DEFAULT 0")
        self.db.execute("""CREATE TABLE IF NOT EXISTS source_failures (
            seerr_id INTEGER PRIMARY KEY, attempts INTEGER NOT NULL
        )""")
        self.db.commit()
        self.seerr_db = sqlite3.connect(required("SEERR_DB"), timeout=10)
        self.seerr_db.execute("PRAGMA busy_timeout=10000")
        request_columns = {row[1] for row in self.seerr_db.execute(
            "PRAGMA table_info(media_request)")}
        if not {"id", "status", "requestedById"} <= request_columns:
            raise RuntimeError("Unsupported Seerr media_request schema")
        self.seerr = requests.Session()
        self.seerr.headers["X-Api-Key"] = self.seerr_key
        self.sc = requests.Session()
        self.csrf = ""

    def _request(self, session: requests.Session, base: str, method: str,
                 path: str, **kwargs):
        response = session.request(method, base + path, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def seerr_api(self, method: str, path: str, **kwargs):
        return self._request(self.seerr, self.seerr_url, method, "/api/v1" + path, **kwargs)

    def sc_login(self) -> None:
        data = self._request(self.sc, self.sc_url, "POST", "/api/auth/jellyfin-token",
                             json={"token": self.jellyfin_token})
        self.csrf = data["csrf_token"]
        # The panel correctly sets Secure for browser sessions behind HTTPS.
        # This client talks only to its private Docker HTTP endpoint, where
        # requests otherwise refuses to return that cookie on later calls.
        for cookie in self.sc.cookies:
            cookie.secure = False

    def sc_api(self, method: str, path: str, **kwargs):
        if not self.csrf:
            self.sc_login()
        if method not in ("GET", "HEAD"):
            kwargs.setdefault("headers", {})["X-CSRF-Token"] = self.csrf
        try:
            return self._request(self.sc, self.sc_url, method, path, **kwargs)
        except requests.HTTPError as error:
            if error.response.status_code not in (401, 403):
                raise
            self.sc_login()
            if method not in ("GET", "HEAD"):
                kwargs["headers"]["X-CSRF-Token"] = self.csrf
            return self._request(self.sc, self.sc_url, method, path, **kwargs)

    def state(self, request_id: int) -> tuple[str, list[int], bool] | None:
        row = self.db.execute("SELECT state,sc_ids,missing FROM work WHERE seerr_id=?",
                              (request_id,)).fetchone()
        return (row[0], json.loads(row[1]), bool(row[2])) if row else None

    def save(self, request_id: int, state: str, media_type: str,
             sc_ids: list[int] | None = None, missing: bool = False) -> None:
        self.db.execute("""INSERT INTO work(seerr_id,state,media_type,sc_ids,missing,updated_at)
            VALUES(?,?,?,?,?,?) ON CONFLICT(seerr_id) DO UPDATE SET
            state=excluded.state,media_type=excluded.media_type,
            sc_ids=excluded.sc_ids,missing=excluded.missing,
            updated_at=excluded.updated_at""",
            (request_id, state, media_type, json.dumps(sc_ids or []),
             int(missing), int(time.time())))
        self.db.commit()

    def hold_seerr(self, request_id: int) -> bool:
        """Keep Seerr from auto-approving a pending request during library scan.

        Seerr v3.4.1 promotes PENDING requests when media becomes AVAILABLE,
        which invokes Radarr/Sonarr before the bridge can observe completion.
        Use a guarded update for this one request; the bridge DB retains its
        actual download state and restores PENDING only for a real fallback.
        """
        with self.seerr_db:
            changed = self.seerr_db.execute("""UPDATE media_request
                SET status=5, updatedAt=CURRENT_TIMESTAMP
                WHERE id=? AND status=1 AND requestedById=?""",
                (request_id, self.seerr_user_id)).rowcount
        if changed:
            LOG.info("Seerr request %s reserved for StreamingCommunity", request_id)
            return True
        row = self.seerr_db.execute("SELECT status,requestedById FROM media_request WHERE id=?",
                                    (request_id,)).fetchone()
        if row and row == (5, self.seerr_user_id):
            return True
        LOG.warning("Seerr request %s changed outside bridge; SC approval deferred", request_id)
        return False

    def release_seerr(self, request_id: int) -> None:
        with self.seerr_db:
            self.seerr_db.execute("""UPDATE media_request
                SET status=1, updatedAt=CURRENT_TIMESTAMP
                WHERE id=? AND status=5 AND requestedById=?""",
                (request_id, self.seerr_user_id))

    def pending(self) -> list[dict]:
        results = []
        skip = 0
        while True:
            page = self.seerr_api("GET", "/request", params={
                "filter": "pending", "requestedBy": self.seerr_user_id,
                "take": 100, "skip": skip,
            })
            batch = page.get("results", [])
            results.extend(batch)
            if len(batch) < 100:
                return results
            skip += len(batch)

    def sc_candidates(self, names: list[str], media_type: str) -> list[dict]:
        candidates: dict[int, dict] = {}
        for name in names:
            for page in range(1, 4):
                found = self.sc_api("GET", "/api/search", params={
                    "q": name, "source": "streamingcommunity", "page": page,
                    "media_type": media_type,
                })
                for item in found:
                    candidates[int(item["id"])] = item
        wanted = [normalized(name) for name in names]
        ranked = sorted(candidates.values(), key=lambda item: max(
            (SequenceMatcher(None, normalized(item.get("name", "")), name).ratio()
             for name in wanted), default=0.0), reverse=True)[:12]
        for item in ranked:
            # Source metadata supplies TMDB IDs when available. Failure here
            # merely lowers certainty; it never turns a weak match into a grab.
            try:
                metadata = self.sc_api("GET", f"/api/metadata/{media_type}/{item['id']}",
                                       params={"slug": item.get("slug", "")})
                item["tmdb_id"] = metadata.get("tmdb_id")
            except requests.RequestException:
                item["tmdb_id"] = None
        return ranked

    def sc_requests_for(self, candidate: dict, seasons: list[int] | None) -> list[dict]:
        requests_list = self.sc_api("GET", "/api/requests")
        return [row for row in requests_list
                if row.get("source") == "streamingcommunity"
                and str(row.get("external_id")) == str(candidate["id"])
                and (seasons is None or row.get("season") in seasons)
                and row.get("audio_languages") == ["ita"]
                and row.get("subtitle_languages") == ["eng", "ita"]]

    def create_sc_requests(self, candidate: dict, media_type: str,
                           seasons: list[int], expected: dict[int, int]) -> tuple[list[int], bool]:
        base = {"source": "streamingcommunity", "external_id": str(candidate["id"]),
                "title": candidate["name"], "year": year(candidate.get("release_date")),
                "poster": candidate.get("poster"), "audio_languages": ["ita"],
                "subtitle_languages": ["eng", "ita"]}
        if media_type == "movie":
            try:
                result = self.sc_api("POST", "/api/requests", json={**base, "media_type": "film"})
            except requests.HTTPError as error:
                if error.response.status_code in (400, 404):
                    return [], False
                raise
            return [int(result["request"]["id"])], False
        missing = False
        created_seasons = []
        for season in seasons:
            try:
                result = self.sc_api("POST", "/api/requests/season", json={
                    **base, "slug": candidate.get("slug"), "season": season})
                created_seasons.append(season)
                if expected.get(season, 0) > int(result["total"]):
                    missing = True
            except requests.HTTPError as error:
                if error.response.status_code in (400, 404):
                    missing = True
                    continue
                raise
        if not created_seasons:
            return [], missing
        rows = self.sc_requests_for(candidate, created_seasons)
        ids = [int(row["id"]) for row in rows if row["status"] in OPEN | SUCCESS]
        return ids, missing or len(ids) < sum(
            expected.get(season, 0) for season in created_seasons)

    def fallback(self, request_id: int, media_type: str) -> None:
        self.release_seerr(request_id)
        self.seerr_api("POST", f"/request/{request_id}/approve")
        self.save(request_id, "fallback", media_type)
        LOG.info("Seerr request %s sent to %s", request_id,
                 "Sonarr" if media_type == "tv" else "Radarr")

    def source_failure(self, request_id: int, media_type: str,
                       error: requests.RequestException) -> None:
        self.db.execute("""INSERT INTO source_failures(seerr_id,attempts) VALUES(?,1)
            ON CONFLICT(seerr_id) DO UPDATE SET attempts=attempts+1""", (request_id,))
        attempts = self.db.execute("SELECT attempts FROM source_failures WHERE seerr_id=?",
                                   (request_id,)).fetchone()[0]
        self.db.commit()
        LOG.warning("StreamingCommunity unavailable for Seerr request %s (%s/3): %s",
                    request_id, attempts, error)
        if attempts >= 3:
            self.fallback(request_id, media_type)

    def clear_source_failures(self, request_id: int) -> None:
        self.db.execute("DELETE FROM source_failures WHERE seerr_id=?", (request_id,))
        self.db.commit()

    def new_request(self, request: dict) -> None:
        request_id = int(request["id"])
        media = request["media"]
        media_type = request.get("type") or media.get("mediaType")
        if media_type not in ("movie", "tv"):
            LOG.warning("Unsupported Seerr request %s type %s", request_id, media_type)
            return
        tmdb_id = int(media["tmdbId"])
        details = self.seerr_api("GET", f"/{media_type}/{tmdb_id}")
        title, wanted_year, names = seerr_title(details, media_type)
        if not names:
            LOG.warning("No title for Seerr request %s", request_id)
            return
        try:
            candidates = self.sc_candidates(names, media_type)
        except (requests.ConnectionError, requests.Timeout) as error:
            self.source_failure(request_id, media_type, error)
            return
        except requests.HTTPError as error:
            if error.response.status_code not in (502, 503, 504):
                raise
            self.source_failure(request_id, media_type, error)
            return
        best, certain = choose(candidates, names, wanted_year, tmdb_id)
        if best is None:
            self.fallback(request_id, media_type)
            return
        seasons = [int(s["seasonNumber"]) for s in request.get("seasons", [])]
        if media_type == "tv" and not seasons:
            LOG.warning("No seasons in TV request %s", request_id)
            return
        expected = {int(s["seasonNumber"]): int(s.get("episodeCount") or 0)
                    for s in details.get("seasons", [])}
        try:
            ids, missing = self.create_sc_requests(best, media_type, seasons, expected)
        except (requests.ConnectionError, requests.Timeout) as error:
            self.source_failure(request_id, media_type, error)
            return
        except requests.HTTPError as error:
            if error.response.status_code not in (502, 503, 504):
                raise
            self.source_failure(request_id, media_type, error)
            return
        self.clear_source_failures(request_id)
        if not ids:
            self.fallback(request_id, media_type)
            return
        self.save(request_id, "running" if certain else "review", media_type,
                  ids, missing)
        if not self.hold_seerr(request_id):
            return
        if certain:
            for sc_id in ids:
                row = self.sc_api("GET", f"/api/requests/{sc_id}")
                if row["status"] == "pending":
                    self.sc_api("POST", f"/api/requests/{sc_id}/approve", json={})
        else:
            LOG.info("Seerr request %s awaits confirmation in StreamingCommunity", request_id)

    def update_request(self, request: dict, state: str, ids: list[int],
                       missing: bool) -> None:
        request_id = int(request["id"])
        media_type = request.get("type") or request["media"].get("mediaType")
        if not self.hold_seerr(request_id):
            return
        rows = [self.sc_api("GET", f"/api/requests/{sc_id}") for sc_id in ids]
        if state == "running":
            for row in rows:
                if row["status"] == "pending":
                    self.sc_api("POST", f"/api/requests/{row['id']}/approve", json={})
            rows = [self.sc_api("GET", f"/api/requests/{sc_id}") for sc_id in ids]
        statuses = [row["status"] for row in rows]
        if state == "review" and all(status == "pending" for status in statuses):
            return
        if any(status in ("needs_attention", "pending") for status in statuses):
            return
        if any(status in OPEN for status in statuses):
            self.save(request_id, "running", media_type, ids, missing)
            return
        if missing or any(status in FAILURE for status in statuses):
            self.fallback(request_id, media_type)
        elif all(status in SUCCESS for status in statuses):
            self.save(request_id, "done", media_type, ids, missing)

    def tick(self) -> None:
        for request in self.pending():
            request_id = int(request["id"])
            state = self.state(request_id)
            try:
                if state is None:
                    self.new_request(request)
            except requests.RequestException as error:
                LOG.warning("Request %s deferred after API error: %s", request_id, error)
            except (KeyError, TypeError, ValueError) as error:
                LOG.exception("Request %s needs operator review: %s", request_id, error)
        for (request_id,) in self.db.execute(
                "SELECT seerr_id FROM work WHERE state IN ('running','review')").fetchall():
            try:
                request = self.seerr_api("GET", f"/request/{request_id}")
                self.update_request(request, *self.state(request_id))
            except requests.RequestException as error:
                LOG.warning("Request %s monitoring deferred: %s", request_id, error)
            except (KeyError, TypeError, ValueError) as error:
                LOG.exception("Request %s needs operator review: %s", request_id, error)


def start_webhook(token: str, wakeups: queue.Queue) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/webhook":
                self.send_error(404)
                return
            if not hmac.compare_digest(self.headers.get("Authorization", ""),
                                       "Bearer " + token):
                self.send_error(401)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            if not 0 < size <= 16384:
                self.send_error(400)
                return
            try:
                event = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeDecodeError):
                self.send_error(400)
                return
            if isinstance(event, dict) and event.get("notification_type") == "MEDIA_PENDING":
                try:
                    wakeups.put_nowait(True)
                except queue.Full:
                    pass
            self.send_response(202)
            self.end_headers()

        def log_message(self, format, *args):
            LOG.info("Webhook: " + format, *args)

    server = ThreadingHTTPServer(("0.0.0.0", 8765), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bridge = Bridge()
    wakeups = queue.Queue(maxsize=1)
    start_webhook(bridge.webhook_token, wakeups)
    while True:
        try:
            bridge.tick()
        except requests.RequestException as error:
            LOG.warning("Poll deferred after API error: %s", error)
        try:
            wakeups.get(timeout=30)
        except queue.Empty:
            pass
