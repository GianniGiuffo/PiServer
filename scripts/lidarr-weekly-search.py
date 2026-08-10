#!/usr/bin/env python3
"""Refresh monitored Lidarr artists and search their recent missing releases."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TERMINAL_COMMAND_STATES = {"completed", "failed", "aborted", "cancelled", "orphaned"}
SUCCESS_COMMAND_STATE = "completed"


def parse_args() -> argparse.Namespace:
    repo_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description=(
            "Refresh monitored Lidarr artists, then search recent monitored "
            "albums, EPs and singles that still have missing tracks."
        )
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=repo_dir / ".env",
        help="Compose environment file used to locate DATA_DIR",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8686",
        help="Lidarr base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--lookback-days",
        type=positive_int,
        default=14,
        help="search releases no older than this many days (default: %(default)s)",
    )
    parser.add_argument(
        "--future-days",
        type=non_negative_int,
        default=1,
        help="also include releases this many days ahead (default: %(default)s)",
    )
    parser.add_argument(
        "--types",
        default="Album,EP,Single",
        help="comma-separated Lidarr album types to search (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=positive_int,
        default=1800,
        help="seconds to wait for each Lidarr command (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show releases that would be searched without changing Lidarr",
    )
    return parser.parse_args()


def positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return value


def read_env_value(path: Path, key: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError(f"cannot read {path}: {error}") from error

    prefix = f"{key}="
    for line in lines:
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            return value
        break
    raise RuntimeError(f"missing {key} in {path}")


def read_api_key(config_path: Path) -> str:
    try:
        root = ET.parse(config_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise RuntimeError(f"cannot read Lidarr configuration {config_path}: {error}") from error

    api_key = root.findtext("ApiKey", default="").strip()
    if not api_key:
        raise RuntimeError(f"missing ApiKey in {config_path}")
    return api_key


class LidarrClient:
    def __init__(self, base_url: str, api_key: str, command_timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.command_timeout = command_timeout

    def request(self, method: str, path: str, payload: Any | None = None) -> Any:
        body = None
        headers = {"Accept": "application/json", "X-Api-Key": self.api_key}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{self.base_url}/api/v1/{path.lstrip('/')}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Lidarr API {method} {path} returned HTTP {error.code}: {detail[:500]}"
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"cannot reach Lidarr at {self.base_url}: {error.reason}") from error

        if not response_body:
            return None
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Lidarr API {method} {path} returned invalid JSON") from error

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def run_command(self, name: str, **arguments: Any) -> dict[str, Any]:
        command = self.request("POST", "command", {"name": name, **arguments})
        if not isinstance(command, dict) or not command.get("id"):
            raise RuntimeError(f"Lidarr did not return an id for command {name}")
        command_id = command["id"]
        print(f"Lidarr command {name} queued as id {command_id}.")
        return self.wait_for_command(command_id, name)

    def wait_for_command(self, command_id: int, name: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.command_timeout
        last_state = ""
        while time.monotonic() < deadline:
            command = self.get(f"command/{command_id}")
            if not isinstance(command, dict):
                raise RuntimeError(f"invalid status for Lidarr command {command_id}")
            state = str(command.get("status", "")).lower()
            if state and state != last_state:
                print(f"Lidarr command {name} is {state}.")
                last_state = state
            if state in TERMINAL_COMMAND_STATES:
                if state != SUCCESS_COMMAND_STATE:
                    message = command.get("message") or command.get("errorMessage") or "no detail"
                    raise RuntimeError(f"Lidarr command {name} ended as {state}: {message}")
                return command
            time.sleep(5)
        raise RuntimeError(
            f"timed out after {self.command_timeout}s waiting for Lidarr command {name}"
        )


def parse_lidarr_date(raw: Any) -> date | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def release_is_missing(album: dict[str, Any]) -> bool:
    statistics = album.get("statistics")
    if not isinstance(statistics, dict):
        return True
    track_count = statistics.get("trackCount")
    file_count = statistics.get("trackFileCount")
    if not isinstance(track_count, int) or not isinstance(file_count, int):
        return True
    return track_count > 0 and file_count < track_count


def select_recent_releases(
    albums: Any,
    monitored_artist_ids: set[int],
    allowed_types: set[str],
    first_day: date,
    last_day: date,
) -> list[dict[str, Any]]:
    if not isinstance(albums, list):
        raise RuntimeError("Lidarr returned an invalid album list")

    selected: list[dict[str, Any]] = []
    for album in albums:
        if not isinstance(album, dict):
            continue
        album_id = album.get("id")
        artist_id = album.get("artistId")
        album_type = str(album.get("albumType", ""))
        release_day = parse_lidarr_date(album.get("releaseDate"))
        if not isinstance(album_id, int) or artist_id not in monitored_artist_ids:
            continue
        if album.get("monitored") is not True:
            continue
        if album_type.casefold() not in allowed_types:
            continue
        if release_day is None or not first_day <= release_day <= last_day:
            continue
        if not release_is_missing(album):
            continue
        selected.append(album)

    selected.sort(key=lambda item: (item.get("releaseDate", ""), item.get("title", "")))
    return selected


def album_artist_name(album: dict[str, Any], artists_by_id: dict[int, str]) -> str:
    artist = album.get("artist")
    if isinstance(artist, dict) and artist.get("artistName"):
        return str(artist["artistName"])
    return artists_by_id.get(album.get("artistId"), "unknown artist")


def main() -> int:
    args = parse_args()
    try:
        data_dir = Path(read_env_value(args.env_file, "DATA_DIR"))
        api_key = read_api_key(data_dir / "lidarr" / "config.xml")
        client = LidarrClient(args.url, api_key, args.timeout)

        artists = client.get("artist")
        if not isinstance(artists, list):
            raise RuntimeError("Lidarr returned an invalid artist list")
        monitored_artists = [
            artist
            for artist in artists
            if isinstance(artist, dict)
            and artist.get("monitored") is True
            and isinstance(artist.get("id"), int)
        ]
        monitored_artist_ids = {artist["id"] for artist in monitored_artists}
        artists_by_id = {
            artist["id"]: str(artist.get("artistName", "unknown artist"))
            for artist in monitored_artists
        }
        if not monitored_artist_ids:
            print("No monitored artists found; nothing to refresh or search.")
            return 0
        print(f"Found {len(monitored_artist_ids)} monitored Lidarr artists.")

        if not args.dry_run:
            client.run_command("RefreshArtist", artistIds=sorted(monitored_artist_ids))

        today = datetime.now(timezone.utc).date()
        first_day = today - timedelta(days=args.lookback_days)
        last_day = today + timedelta(days=args.future_days)
        allowed_types = {
            value.strip().casefold() for value in args.types.split(",") if value.strip()
        }
        if not allowed_types:
            raise RuntimeError("--types must contain at least one album type")

        releases = select_recent_releases(
            client.get("album"),
            monitored_artist_ids,
            allowed_types,
            first_day,
            last_day,
        )
        if not releases:
            print(
                f"No incomplete monitored releases dated {first_day} through {last_day}; "
                "nothing to search."
            )
            return 0

        print(f"Selected {len(releases)} recent incomplete releases:")
        for album in releases:
            print(
                "- "
                f"{album.get('releaseDate', 'unknown date')}: "
                f"{album_artist_name(album, artists_by_id)} - "
                f"{album.get('title', 'unknown title')} [{album.get('albumType', 'unknown type')}]"
            )

        if args.dry_run:
            print("Dry run: no Lidarr search was started.")
            return 0

        album_ids = [album["id"] for album in releases]
        for offset in range(0, len(album_ids), 100):
            client.run_command("AlbumSearch", albumIds=album_ids[offset : offset + 100])
        print("Weekly Lidarr refresh and recent-release search completed.")
        return 0
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
