#!/usr/bin/env python3
"""Route pending Seerr requests through StreamingCommunity before *arr.

Only requests from the configured, non-auto-approving Seerr user are handled.
Uncertain matches remain in StreamingCommunity's native approval queue.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import unicodedata
from difflib import SequenceMatcher
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
        self.db_path = Path(required("BRIDGE_DB"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS work (
            seerr_id INTEGER PRIMARY KEY, state TEXT NOT NULL, media_type TEXT NOT NULL,
            sc_ids TEXT NOT NULL DEFAULT '[]', updated_at INTEGER NOT NULL
        )""")
        self.db.commit()
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

    def state(self, request_id: int) -> tuple[str, list[int]] | None:
        row = self.db.execute("SELECT state,sc_ids FROM work WHERE seerr_id=?",
                              (request_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def save(self, request_id: int, state: str, media_type: str,
             sc_ids: list[int] | None = None) -> None:
        self.db.execute("""INSERT INTO work(seerr_id,state,media_type,sc_ids,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(seerr_id) DO UPDATE SET
            state=excluded.state,media_type=excluded.media_type,
            sc_ids=excluded.sc_ids,updated_at=excluded.updated_at""",
            (request_id, state, media_type, json.dumps(sc_ids or []), int(time.time())))
        self.db.commit()

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
                           seasons: list[int]) -> list[int]:
        base = {"source": "streamingcommunity", "external_id": str(candidate["id"]),
                "title": candidate["name"], "year": year(candidate.get("release_date")),
                "poster": candidate.get("poster"), "audio_languages": ["ita"],
                "subtitle_languages": ["eng", "ita"]}
        if media_type == "movie":
            try:
                result = self.sc_api("POST", "/api/requests", json={**base, "media_type": "film"})
            except requests.HTTPError as error:
                if error.response.status_code in (400, 404):
                    return []
                raise
            return [int(result["request"]["id"])]
        missing = 0
        created_seasons = []
        for season in seasons:
            try:
                self.sc_api("POST", "/api/requests/season", json={
                    **base, "slug": candidate.get("slug"), "season": season})
                created_seasons.append(season)
            except requests.HTTPError as error:
                if error.response.status_code in (400, 404):
                    missing += 1
                    continue
                raise
        if not created_seasons and missing:
            return []
        rows = self.sc_requests_for(candidate, created_seasons)
        return [int(row["id"]) for row in rows
                if row["status"] in OPEN | SUCCESS]

    def fallback(self, request_id: int, media_type: str) -> None:
        self.seerr_api("POST", f"/request/{request_id}/approve")
        self.save(request_id, "fallback", media_type)
        LOG.info("Seerr request %s sent to %s", request_id,
                 "Sonarr" if media_type == "tv" else "Radarr")

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
        candidates = self.sc_candidates(names, media_type)
        best, certain = choose(candidates, names, wanted_year, tmdb_id)
        if best is None:
            self.fallback(request_id, media_type)
            return
        seasons = [int(s["seasonNumber"]) for s in request.get("seasons", [])]
        if media_type == "tv" and not seasons:
            LOG.warning("No seasons in TV request %s", request_id)
            return
        ids = self.create_sc_requests(best, media_type, seasons)
        if not ids:
            self.fallback(request_id, media_type)
            return
        self.save(request_id, "running" if certain else "review", media_type, ids)
        if certain:
            for sc_id in ids:
                row = self.sc_api("GET", f"/api/requests/{sc_id}")
                if row["status"] == "pending":
                    self.sc_api("POST", f"/api/requests/{sc_id}/approve", json={})
        else:
            LOG.info("Seerr request %s awaits confirmation in StreamingCommunity", request_id)

    def update_request(self, request: dict, state: str, ids: list[int]) -> None:
        request_id = int(request["id"])
        media_type = request.get("type") or request["media"].get("mediaType")
        rows = [self.sc_api("GET", f"/api/requests/{sc_id}") for sc_id in ids]
        statuses = [row["status"] for row in rows]
        if state == "review" and all(status == "pending" for status in statuses):
            return
        if any(status in ("needs_attention", "pending") for status in statuses):
            return
        if any(status in OPEN for status in statuses):
            self.save(request_id, "running", media_type, ids)
            return
        if media_type == "tv" or any(status in FAILURE for status in statuses):
            self.fallback(request_id, media_type)
        elif all(status in SUCCESS for status in statuses):
            self.save(request_id, "done", media_type, ids)

    def tick(self) -> None:
        for request in self.pending():
            request_id = int(request["id"])
            state = self.state(request_id)
            try:
                if state is None:
                    self.new_request(request)
                elif state[0] in ("running", "review"):
                    self.update_request(request, *state)
            except requests.RequestException as error:
                LOG.warning("Request %s deferred after API error: %s", request_id, error)
            except (KeyError, TypeError, ValueError) as error:
                LOG.exception("Request %s needs operator review: %s", request_id, error)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bridge = Bridge()
    while True:
        try:
            bridge.tick()
        except requests.RequestException as error:
            LOG.warning("Poll deferred after API error: %s", error)
        time.sleep(60)
