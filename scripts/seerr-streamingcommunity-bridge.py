#!/usr/bin/env python3
"""Give StreamingCommunity first refusal on Seerr requests from two real users.

Seerr has no configured Arr services in priority mode. Its admin requests are
already approved at insertion, so a webhook cannot stop Seerr's Arr subscriber.
The bridge reserves each new request in Seerr's SQLite database, tracks source
episodes durably, and calls the real Arr APIs only for confirmed gaps/failures.
"""

from __future__ import annotations

import hmac
import json
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

from seerr_arr_fallback import ArrFallback, UncertainSeries


LOG = logging.getLogger("seerr-bridge")
OPEN = {"pending", "approved", "downloading", "needs_attention"}
SUCCESS = {"completed", "available"}
FAILURE = {"failed", "denied", "cancelled"}
ACTIVE = {"matching", "running", "review", "fallback_prepare",
          "fallback_command_intent"}


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}")
    return value


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def title_score(candidate: str, wanted: str) -> float:
    if not candidate or not wanted:
        return 0.0
    similarity = SequenceMatcher(None, candidate, wanted).ratio()
    # Localized releases often append a subtitle, e.g. the Italian release
    # name of a movie. Keep them for manual review even without year/ID.
    if candidate.startswith(wanted + " ") or wanted.startswith(candidate + " "):
        return max(similarity, 0.7)
    return similarity


def year(value: str | None) -> str:
    match = re.match(r"^\d{4}", str(value or ""))
    return match.group() if match else ""


def seerr_title(details: dict, media_type: str) -> tuple[str, str, list[str]]:
    if media_type == "movie":
        title = details.get("title") or details.get("originalTitle") or ""
        other = details.get("originalTitle") or ""
        release = details.get("releaseDate")
    else:
        title = details.get("name") or details.get("originalName") or ""
        other = details.get("originalName") or ""
        release = details.get("firstAirDate")
    return title, year(release), list(dict.fromkeys(x for x in (title, other) if x))


def choose(candidates: list[dict], names: list[str], wanted_year: str,
           tmdb_id: int) -> tuple[dict | None, bool]:
    """An ID match, or a unique exact title/year without conflicting ID, is certain."""
    seen = {normalized(name) for name in names if name}
    ranked = []
    for item in candidates:
        title = normalized(item.get("name", ""))
        source_id = item.get("tmdb_id")
        if source_id and str(source_id) != str(tmdb_id):
            continue
        similarity = max((title_score(title, name)
                          for name in seen), default=0.0)
        id_match = str(source_id or "") == str(tmdb_id)
        exact = title in seen and bool(title)
        year_match = bool(wanted_year and year(item.get("release_date")) == wanted_year)
        score = (10 if id_match else 0) + (3 if exact else similarity) + year_match
        if score >= 0.55:
            ranked.append((score, item, id_match, exact, year_match))
    if not ranked:
        return None, False
    ranked.sort(key=lambda row: row[0], reverse=True)
    top = ranked[0]
    unique = len(ranked) == 1 or top[0] > ranked[1][0]
    return top[1], bool(unique and (top[2] or (top[3] and top[4])))


class Bridge:
    def __init__(self) -> None:
        self.seerr_url = required("SEERR_URL").rstrip("/")
        self.sc_url = required("STREAMINGCOMMUNITY_URL").rstrip("/")
        self.normal_id = int(required("SEERR_REQUEST_USER_ID"))
        self.admin_id = int(required("SEERR_ADMIN_USER_ID"))
        self.admin_min_request_id = int(required("SEERR_ADMIN_MIN_REQUEST_ID"))
        self.seerr_key = required("SEERR_API_KEY")
        self.jellyfin_token = required("BRIDGE_JELLYFIN_TOKEN")
        self.webhook_token = required("BRIDGE_WEBHOOK_TOKEN")
        self.settings_path = Path(required("SEERR_SETTINGS"))
        self.arr = ArrFallback()
        db_path = Path(required("BRIDGE_DB"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS work (
            seerr_id INTEGER PRIMARY KEY, state TEXT NOT NULL, media_type TEXT NOT NULL,
            sc_ids TEXT NOT NULL DEFAULT '[]', missing INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL)""")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(work)")}
        if "missing" not in columns:
            self.db.execute("ALTER TABLE work ADD COLUMN missing INTEGER NOT NULL DEFAULT 0")
        if "context" not in columns:
            self.db.execute("ALTER TABLE work ADD COLUMN context TEXT NOT NULL DEFAULT '{}'")
        self.db.commit()
        self.seerr_db = sqlite3.connect(required("SEERR_DB"), timeout=10)
        self.seerr_db.execute("PRAGMA busy_timeout=10000")
        columns = {row[1] for row in self.seerr_db.execute(
            "PRAGMA table_info(media_request)")}
        if not {"id", "status", "requestedById", "type"} <= columns:
            raise RuntimeError("Unsupported Seerr media_request schema")
        self.seerr = requests.Session()
        self.seerr.headers["X-Api-Key"] = self.seerr_key
        self.sc = requests.Session()
        self.csrf = ""
        self.assert_arr_disconnected()

    def assert_arr_disconnected(self) -> None:
        settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        if settings.get("radarr") or settings.get("sonarr"):
            raise RuntimeError("Priority mode requires zero Arr services in Seerr")

    @staticmethod
    def _request(session: requests.Session, base: str, method: str,
                 path: str, **kwargs):
        response = session.request(method, base + path, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def seerr_api(self, method: str, path: str, **kwargs):
        return self._request(self.seerr, self.seerr_url, method,
                             "/api/v1" + path, **kwargs)

    def sc_login(self) -> None:
        data = self._request(self.sc, self.sc_url, "POST", "/api/auth/jellyfin-token",
                             json={"token": self.jellyfin_token})
        self.csrf = data["csrf_token"]
        for cookie in self.sc.cookies:
            cookie.secure = False  # private HTTP Docker network

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

    def work(self, request_id: int) -> tuple[str, str, list[int], dict] | None:
        row = self.db.execute(
            "SELECT state,media_type,sc_ids,context FROM work WHERE seerr_id=?",
            (request_id,)).fetchone()
        return (row[0], row[1], json.loads(row[2]), json.loads(row[3])) if row else None

    def save(self, request_id: int, state: str, media_type: str,
             ids: list[int] | None = None, context: dict | None = None) -> None:
        self.db.execute("""INSERT INTO work
            (seerr_id,state,media_type,sc_ids,missing,updated_at,context)
            VALUES(?,?,?,?,0,?,?) ON CONFLICT(seerr_id) DO UPDATE SET
            state=excluded.state,media_type=excluded.media_type,
            sc_ids=excluded.sc_ids,updated_at=excluded.updated_at,
            context=excluded.context""",
            (request_id, state, media_type, json.dumps(ids or []),
             int(time.time()), json.dumps(context or {})))
        self.db.commit()

    def hold_seerr(self, request_id: int, user_id: int) -> bool:
        """Guarded status claim; SQLite bypasses Seerr's Arr subscriber."""
        with self.seerr_db:
            changed = self.seerr_db.execute("""UPDATE media_request
                SET status=5, updatedAt=CURRENT_TIMESTAMP
                WHERE id=? AND status IN (1,2) AND requestedById=?""",
                (request_id, user_id)).rowcount
        if changed:
            LOG.info("Seerr request %s reserved", request_id)
            return True
        row = self.seerr_db.execute(
            "SELECT status,requestedById FROM media_request WHERE id=?",
            (request_id,)).fetchone()
        return row == (5, user_id)

    def new_ids(self) -> list[int]:
        rows = self.seerr_db.execute("""
            SELECT id FROM media_request WHERE status IN (1,2)
              AND (requestedById=? OR (requestedById=? AND id>=?))
            ORDER BY id""", (self.normal_id, self.admin_id,
                              self.admin_min_request_id)).fetchall()
        return [row[0] for row in rows if self.work(row[0]) is None]

    def sc_candidates(self, names: list[str], media_type: str) -> list[dict]:
        candidates: dict[int, dict] = {}
        for name in names:
            for page in range(1, 4):
                found = self.sc_api("GET", "/api/search", params={
                    "q": name, "source": "streamingcommunity", "page": page,
                    "media_type": media_type})
                for item in found:
                    candidates[int(item["id"])] = item
        wanted = [normalized(name) for name in names]
        ranked = sorted(candidates.values(), key=lambda item: max(
            (title_score(normalized(item.get("name", "")), name)
             for name in wanted), default=0.0), reverse=True)[:12]
        for item in ranked:
            try:
                metadata = self.sc_api("GET", f"/api/metadata/{media_type}/{item['id']}",
                                       params={"slug": item.get("slug", "")})
                item["tmdb_id"] = metadata.get("tmdb_id")
            except requests.RequestException:
                item["tmdb_id"] = None
        return ranked

    def sc_rows_for(self, candidate: dict, seasons: list[int] | None) -> list[dict]:
        rows = self.sc_api("GET", "/api/requests")
        return [row for row in rows
                if row.get("source") == "streamingcommunity"
                and str(row.get("external_id")) == str(candidate["id"])
                and (seasons is None or row.get("season") in seasons)
                and row.get("audio_languages") == ["ita"]
                and row.get("subtitle_languages") == ["eng", "ita"]]

    @staticmethod
    def source_success(row: dict) -> bool:
        if row.get("status") not in SUCCESS:
            return False
        output = row.get("output_path")
        return bool(output and Path(output).is_file()) or row.get("status") == "available"

    def requested_episodes(self, tmdb_id: int, seasons: list[int]) -> dict[int, set[int]]:
        expected = {}
        for season in seasons:
            data = self.seerr_api("GET", f"/tv/{tmdb_id}/season/{season}")
            expected[season] = {int(row["episodeNumber"]) for row in data["episodes"]
                                if int(row.get("episodeNumber") or 0) > 0}
            if not expected[season]:
                raise RuntimeError(f"No episode metadata for season {season}")
        return expected

    def create_sc(self, candidate: dict, media_type: str,
                  seasons: list[int]) -> list[int]:
        base = {"source": "streamingcommunity", "external_id": str(candidate["id"]),
                "title": candidate["name"], "year": year(candidate.get("release_date")),
                "poster": candidate.get("poster"), "audio_languages": ["ita"],
                "subtitle_languages": ["eng", "ita"]}
        if media_type == "movie":
            if not self.sc_rows_for(candidate, None):
                try:
                    self.sc_api("POST", "/api/requests", json={**base, "media_type": "film"})
                except requests.HTTPError as error:
                    if error.response.status_code not in (400, 404):
                        raise
        else:
            for season in seasons:
                if not self.sc_rows_for(candidate, [season]):
                    try:
                        self.sc_api("POST", "/api/requests/season", json={
                            **base, "slug": candidate.get("slug"), "season": season})
                    except requests.HTTPError as error:
                        if error.response.status_code not in (400, 404):
                            raise
        rows = self.sc_rows_for(candidate, None if media_type == "movie" else seasons)
        return sorted({int(row["id"]) for row in rows
                       if row.get("status") in OPEN | SUCCESS | FAILURE})

    def source_failure(self, request_id: int, media_type: str,
                       ids: list[int], context: dict, error: Exception) -> None:
        # A season call can fail after earlier seasons created requests. Never
        # hand those same episodes to Sonarr while they are still in flight.
        if context.get("candidate"):
            try:
                seasons = ([int(s) for s in context.get("expected", {})]
                           if media_type == "tv" else None)
                rows = self.sc_rows_for(context["candidate"], seasons)
                recovered = sorted({int(row["id"]) for row in rows
                                    if row.get("status") in OPEN | SUCCESS | FAILURE})
                if recovered:
                    self.save(request_id, "running" if context.get("certain")
                              else "review", media_type, recovered, context)
                    return
            except requests.RequestException:
                pass
        attempts = int(context.get("source_attempts", 0)) + 1
        context["source_attempts"] = attempts
        self.save(request_id, "matching", media_type, ids, context)
        LOG.warning("Source unavailable for request %s (%s/3): %s",
                    request_id, attempts, type(error).__name__)
        if attempts >= 3:
            self.prepare_fallback(request_id, media_type, ids, context)

    def start_request(self, request: dict) -> None:
        request_id = int(request["id"])
        media_type = request.get("type") or request["media"].get("mediaType")
        if media_type not in ("movie", "tv") or request.get("is4k"):
            self.save(request_id, "needs_attention", media_type or "unknown",
                      context={"reason": "unsupported type or 4K"})
            LOG.warning("Request %s needs operator review (type/4K)", request_id)
            return
        requester = int(request["requestedBy"]["id"])
        if requester not in (self.admin_id, self.normal_id):
            return
        context = {"requester": requester, "tmdb_id": int(request["media"]["tmdbId"])}
        self.save(request_id, "matching", media_type, context=context)
        self.match_request(request, context)

    def match_request(self, request: dict, context: dict) -> None:
        request_id = int(request["id"])
        media_type = request.get("type") or request["media"].get("mediaType")
        if not self.hold_seerr(request_id, int(context["requester"])):
            self.save(request_id, "needs_attention", media_type, context=context)
            return
        tmdb_id = int(context["tmdb_id"])
        details = self.seerr_api("GET", f"/{media_type}/{tmdb_id}")
        title, wanted_year, names = seerr_title(details, media_type)
        if not names:
            self.save(request_id, "needs_attention", media_type, context=context)
            return
        context.update({"title": title, "year": wanted_year,
                        "tvdb_id": request["media"].get("tvdbId")})
        seasons = ([int(s["seasonNumber"]) for s in request.get("seasons", [])]
                   if media_type == "tv" else [])
        if media_type == "tv":
            if not seasons:
                self.save(request_id, "needs_attention", media_type, context=context)
                return
            expected = self.requested_episodes(tmdb_id, seasons)
            context["expected"] = {str(s): sorted(numbers)
                                   for s, numbers in expected.items()}
        self.save(request_id, "matching", media_type, context=context)
        try:
            candidates = self.sc_candidates(names, media_type)
            best, certain = choose(candidates, names, wanted_year, tmdb_id)
            if best is None:
                self.prepare_fallback(request_id, media_type, [], context)
                return
            context["candidate"] = {key: best.get(key) for key in
                                    ("id", "name", "slug", "release_date", "poster")}
            context["certain"] = certain
            self.save(request_id, "matching", media_type, context=context)
            ids = self.create_sc(best, media_type, seasons)
        except (requests.RequestException, OSError) as error:
            self.source_failure(request_id, media_type, [], context, error)
            return
        if not ids:
            self.prepare_fallback(request_id, media_type, [], context)
            return
        self.save(request_id, "running" if certain else "review", media_type,
                  ids, context)
        self.monitor_sc(request_id, media_type, ids, context)

    def prepare_fallback(self, request_id: int, media_type: str,
                         ids: list[int], context: dict,
                         missing: dict[int, set[int]] | None = None) -> None:
        if media_type == "tv":
            missing = missing if missing is not None else {
                int(season): set(numbers)
                for season, numbers in context.get("expected", {}).items()}
            context["missing"] = {str(season): sorted(numbers)
                                  for season, numbers in missing.items() if numbers}
            if not context["missing"]:
                self.save(request_id, "done", media_type, ids, context)
                return
        self.save(request_id, "fallback_prepare", media_type, ids, context)
        self.dispatch_fallback(request_id, media_type, ids, context)

    def dispatch_fallback(self, request_id: int, media_type: str,
                          ids: list[int], context: dict) -> None:
        self.assert_arr_disconnected()
        try:
            if media_type == "movie":
                details = self.seerr_api("GET", f"/movie/{context['tmdb_id']}")
                movie_id, needs_search = self.arr.movie(int(context["tmdb_id"]), details)
                context["arr_id"] = movie_id
                if needs_search:
                    context["command_kind"] = "movie"
                    self.save(request_id, "fallback_command_intent", media_type,
                              ids, context)
                    self.arr.search_movie(movie_id)
                self.save(request_id, "fallback_done", media_type, ids, context)
                LOG.info("Request %s handed to Radarr", request_id)
                return
            missing = {int(season): set(numbers)
                       for season, numbers in context["missing"].items()}
            series_id, episode_ids = self.arr.series(
                context["title"], context["year"],
                int(context["tvdb_id"]) if context.get("tvdb_id") else None,
                missing)
            context.update({"arr_id": series_id, "episode_ids": episode_ids})
            if not episode_ids:
                self.save(request_id, "fallback_done", media_type, ids, context)
                return
            # At-most-once search command across restarts. A crash in this
            # narrow interval is reconciled from Sonarr's command history.
            context["command_kind"] = "tv"
            self.save(request_id, "fallback_command_intent", media_type, ids, context)
            self.arr.search_episodes(episode_ids)
            self.save(request_id, "fallback_done", media_type, ids, context)
            LOG.info("Request %s handed %s episode(s) to Sonarr",
                     request_id, len(episode_ids))
        except UncertainSeries:
            self.save(request_id, "needs_attention", media_type, ids, context)
            LOG.warning("Request %s needs a TVDB match before Sonarr fallback", request_id)
        except (requests.RequestException, LookupError, RuntimeError) as error:
            LOG.warning("Fallback for request %s deferred: %s",
                        request_id, type(error).__name__)

    def reconcile_command(self, request_id: int, media_type: str,
                          ids: list[int], context: dict) -> None:
        try:
            kind = context.get("command_kind", "tv")
            commands = self.arr.call(kind, "GET", "/command",
                                     params={"pageSize": 100})
            rows = commands.get("records", []) if isinstance(commands, dict) else commands
            field = "movieIds" if kind == "movie" else "episodeIds"
            wanted = ({context["arr_id"]} if kind == "movie" else
                      set(context.get("episode_ids", [])))
            name = "moviessearch" if kind == "movie" else "episodesearch"
            if any(str(row.get("name", "")).lower() == name
                   and set((row.get("body") or {}).get(field, [])) == wanted
                   for row in rows):
                self.save(request_id, "fallback_done", media_type, ids, context)
            else:
                self.save(request_id, "needs_attention", media_type, ids, context)
                LOG.warning("Request %s: Arr search acknowledgement uncertain", request_id)
        except requests.RequestException:
            LOG.warning("Request %s: Arr command reconciliation deferred", request_id)

    def monitor_sc(self, request_id: int, media_type: str,
                   ids: list[int], context: dict) -> None:
        if not self.hold_seerr(request_id, int(context["requester"])):
            self.save(request_id, "needs_attention", media_type, ids, context)
            return
        rows = [self.sc_api("GET", f"/api/requests/{sc_id}") for sc_id in ids]
        if context.get("certain"):
            for row in rows:
                if row.get("status") == "pending":
                    self.sc_api("POST", f"/api/requests/{row['id']}/approve", json={})
            rows = [self.sc_api("GET", f"/api/requests/{sc_id}") for sc_id in ids]
        elif any(row.get("status") == "pending" for row in rows):
            self.save(request_id, "review", media_type, ids, context)
            return
        if any(row.get("status") in OPEN for row in rows):
            self.save(request_id, "running", media_type, ids, context)
            return
        if media_type == "movie":
            if any(self.source_success(row) for row in rows):
                self.save(request_id, "done", media_type, ids, context)
            else:
                self.prepare_fallback(request_id, media_type, ids, context)
            return
        delivered = {(int(row["season"]), int(row["episode_number"]))
                     for row in rows if self.source_success(row)
                     and row.get("season") is not None
                     and str(row.get("episode_number") or "").isdigit()}
        expected = {int(season): set(numbers)
                    for season, numbers in context["expected"].items()}
        missing = {season: numbers - {ep for s, ep in delivered if s == season}
                   for season, numbers in expected.items()}
        if any(missing.values()):
            self.prepare_fallback(request_id, media_type, ids, context, missing)
        else:
            self.save(request_id, "done", media_type, ids, context)

    def tick(self) -> None:
        self.assert_arr_disconnected()
        for request_id in self.new_ids():
            try:
                self.start_request(self.seerr_api("GET", f"/request/{request_id}"))
            except (requests.RequestException, KeyError, TypeError, ValueError,
                    RuntimeError) as error:
                LOG.warning("Request %s deferred: %s", request_id, type(error).__name__)
        rows = self.db.execute("SELECT seerr_id FROM work WHERE state IN "
                               "('matching','running','review','fallback_prepare',"
                               "'fallback_command_intent')").fetchall()
        for (request_id,) in rows:
            try:
                state, media_type, ids, context = self.work(request_id)
                if state == "matching":
                    request = self.seerr_api("GET", f"/request/{request_id}")
                    self.match_request(request, context)
                elif state in ("running", "review"):
                    self.monitor_sc(request_id, media_type, ids, context)
                elif state == "fallback_prepare":
                    self.dispatch_fallback(request_id, media_type, ids, context)
                elif state == "fallback_command_intent":
                    self.reconcile_command(request_id, media_type, ids, context)
            except (requests.RequestException, KeyError, TypeError, ValueError,
                    RuntimeError,
                    sqlite3.Error, OSError) as error:
                LOG.warning("Request %s monitoring deferred: %s",
                            request_id, type(error).__name__)

    def tvdb_lookup(self, tmdb_id: int, cookie: str) -> list[dict]:
        identity = requests.get(self.seerr_url + "/api/v1/auth/me",
                                headers={"Cookie": cookie}, timeout=10)
        if identity.status_code != 200:
            raise PermissionError("Seerr session required")
        details = requests.get(self.seerr_url + f"/api/v1/tv/{tmdb_id}",
                               headers={"X-Api-Key": self.seerr_key}, timeout=20)
        details.raise_for_status()
        title = details.json().get("name")
        if not title:
            return []
        rows = self.arr.call("tv", "GET", "/series/lookup",
                             params={"term": title})
        return [row for row in rows if row.get("tvdbId")]


def start_webhook(bridge: Bridge, wakeups: queue.Queue) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.end_headers()
                return
            match = re.fullmatch(r"/api/v1/service/sonarr/lookup/(\d+)", self.path)
            if not match:
                self.send_error(404)
                return
            try:
                rows = bridge.tvdb_lookup(int(match.group(1)),
                                          self.headers.get("Cookie", ""))
            except PermissionError:
                self.send_error(401)
                return
            except requests.RequestException:
                self.send_error(502)
                return
            payload = json.dumps(rows).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            if self.path != "/webhook":
                self.send_error(404)
                return
            if not hmac.compare_digest(self.headers.get("Authorization", ""),
                                       "Bearer " + bridge.webhook_token):
                self.send_error(401)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    raise ValueError("Invalid size")
                event = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeDecodeError):
                self.send_error(400)
                return
            if isinstance(event, dict) and event.get("notification_type") in (
                    "MEDIA_PENDING", "MEDIA_AUTO_APPROVED", "MEDIA_APPROVED"):
                try:
                    wakeups.put_nowait(True)
                except queue.Full:
                    pass
            self.send_response(202)
            self.end_headers()

        def log_message(self, _format, *_args):
            return  # never log session cookies, URLs or tokens

    server = ThreadingHTTPServer(("0.0.0.0", 8765), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    bridge = Bridge()
    wakeups: queue.Queue = queue.Queue(maxsize=1)
    start_webhook(bridge, wakeups)
    while True:
        try:
            bridge.tick()
        except (requests.RequestException, OSError, sqlite3.Error) as error:
            LOG.warning("Poll deferred: %s", type(error).__name__)
        try:
            wakeups.get(timeout=10)
        except queue.Empty:
            pass
