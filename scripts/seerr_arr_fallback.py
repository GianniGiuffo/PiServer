"""Direct, idempotent Arr fallback for Seerr requests claimed by the bridge.

Seerr never talks to these services. This module only receives a movie or the
specific TV episodes that StreamingCommunity did not deliver.
"""

from __future__ import annotations

import os
import re
import unicodedata
from difflib import SequenceMatcher

import requests


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}")
    return value


def _name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    return re.sub(r"[^a-z0-9]+", " ", "".join(
        c for c in value if not unicodedata.combining(c)
    ).casefold()).strip()


class UncertainSeries(ValueError):
    """A TVDB match needs a human decision; no Arr write has occurred."""


class ArrFallback:
    def __init__(self) -> None:
        self.radarr_url = _required("RADARR_URL").rstrip("/") + "/api/v3"
        self.sonarr_url = _required("SONARR_URL").rstrip("/") + "/api/v3"
        self.radarr_key = _required("RADARR_API_KEY")
        self.sonarr_key = _required("SONARR_API_KEY")
        self.movie_root = _required("RADARR_ROOT_FOLDER")
        self.series_root = _required("SONARR_ROOT_FOLDER")
        self.movie_profile = int(_required("RADARR_PROFILE_ID"))
        self.series_profile = int(_required("SONARR_PROFILE_ID"))
        self.minimum_availability = os.getenv("RADARR_MINIMUM_AVAILABILITY", "released")

    def call(self, kind: str, method: str, path: str, **kwargs):
        base, key = ((self.radarr_url, self.radarr_key) if kind == "movie" else
                     (self.sonarr_url, self.sonarr_key))
        headers = dict(kwargs.pop("headers", {}))
        headers["X-Api-Key"] = key
        response = requests.request(method, base + path, headers=headers,
                                    timeout=30, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def movie(self, tmdb_id: int, details: dict) -> tuple[int, bool]:
        """Add or reuse the unique TMDB movie; report if it still needs search."""
        matches = self.call("movie", "GET", "/movie/lookup",
                            params={"term": f"tmdb:{tmdb_id}"})
        movie = next((row for row in matches if row.get("tmdbId") == tmdb_id), None)
        if not movie:
            raise LookupError(f"Radarr has no TMDB result for {tmdb_id}")
        if movie.get("id"):
            return int(movie["id"]), not bool(movie.get("hasFile"))
        title = details.get("title") or movie.get("title")
        release = details.get("releaseDate") or movie.get("releaseDate") or ""
        payload = {
            "title": title,
            "tmdbId": tmdb_id,
            "year": int(str(release)[:4]) if str(release)[:4].isdigit() else movie.get("year"),
            "qualityProfileId": self.movie_profile,
            "rootFolderPath": self.movie_root,
            "minimumAvailability": self.minimum_availability,
            "monitored": True,
            "tags": [],
            "addOptions": {"searchForMovie": True},
        }
        try:
            added = self.call("movie", "POST", "/movie", json=payload)
        except requests.RequestException:
            # The POST can have succeeded despite a lost response. Re-read by
            # TMDB ID before allowing another attempt on the next poll.
            matches = self.call("movie", "GET", "/movie/lookup",
                                params={"term": f"tmdb:{tmdb_id}"})
            found = next((row for row in matches if row.get("tmdbId") == tmdb_id
                          and row.get("id")), None)
            if found:
                # A lost POST response may have launched its own search. Never
                # launch a second one without an operator reconciling it.
                return int(found["id"]), False
            raise
        if not added.get("id"):
            raise RuntimeError("Radarr returned no movie ID")
        return int(added["id"]), False

    def search_movie(self, movie_id: int) -> None:
        self.call("movie", "POST", "/command",
                  json={"name": "MoviesSearch", "movieIds": [movie_id]})

    def lookup_series(self, title: str, year: str, tvdb_id: int | None) -> dict:
        if tvdb_id:
            rows = self.call("tv", "GET", "/series/lookup",
                             params={"term": f"tvdb:{tvdb_id}"})
            match = next((row for row in rows if row.get("tvdbId") == tvdb_id), None)
            if not match:
                raise LookupError(f"Sonarr has no TVDB result for {tvdb_id}")
            return match
        rows = self.call("tv", "GET", "/series/lookup", params={"term": title})
        exact = [row for row in rows if _name(row.get("title", "")) == _name(title)
                 and (not year or str(row.get("year") or "") == year)
                 and row.get("tvdbId")]
        if len({row["tvdbId"] for row in exact}) != 1:
            raise UncertainSeries("TVDB ID absent and Sonarr title/year is ambiguous")
        return exact[0]

    def series(self, title: str, year: str, tvdb_id: int | None,
               missing: dict[int, set[int]]) -> tuple[int, list[int]]:
        """Create/reuse the series without triggering a whole-season search.

        Return the real Sonarr series ID and only the episode IDs still needed.
        The caller persists the command intent before submitting EpisodeSearch.
        """
        metadata = self.lookup_series(title, year, tvdb_id)
        tvdb_id = int(metadata["tvdbId"])
        existing = self.call("tv", "GET", "/series", params={"tvdbId": tvdb_id})
        record = next((row for row in existing if row.get("tvdbId") == tvdb_id), None)
        if not record:
            seasons = [{"seasonNumber": int(row["seasonNumber"]), "monitored": False}
                       for row in metadata.get("seasons", [])]
            payload = {
                "title": metadata["title"],
                "tvdbId": tvdb_id,
                "qualityProfileId": self.series_profile,
                "rootFolderPath": self.series_root,
                "seasonFolder": True,
                "seriesType": metadata.get("seriesType") or "standard",
                "monitored": True,
                "monitorNewItems": "none",
                "seasons": seasons,
                "tags": [],
                "addOptions": {"searchForMissingEpisodes": False,
                               "ignoreEpisodesWithFiles": True},
            }
            try:
                record = self.call("tv", "POST", "/series", json=payload)
            except requests.RequestException:
                existing = self.call("tv", "GET", "/series", params={"tvdbId": tvdb_id})
                record = next((row for row in existing if row.get("tvdbId") == tvdb_id), None)
                if not record:
                    raise
        if not record.get("id"):
            raise RuntimeError("Sonarr returned no series ID")
        series_id = int(record["id"])
        episodes = self.call("tv", "GET", "/episode", params={"seriesId": series_id})
        wanted = {(season, episode) for season, numbers in missing.items()
                  for episode in numbers}
        matched = {(int(row["seasonNumber"]), int(row["episodeNumber"])): row
                   for row in episodes if row.get("episodeNumber") is not None}
        if wanted - matched.keys():
            raise RuntimeError("Sonarr has not indexed all requested episodes yet")
        ids = [int(matched[key]["id"]) for key in sorted(wanted)
               if not matched[key].get("hasFile")]
        if ids:
            self.call("tv", "PUT", "/episode/monitor",
                      json={"episodeIds": ids, "monitored": True})
        return series_id, ids

    def search_episodes(self, episode_ids: list[int]) -> None:
        if episode_ids:
            self.call("tv", "POST", "/command",
                      json={"name": "EpisodeSearch", "episodeIds": episode_ids})
