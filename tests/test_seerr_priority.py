"""Targeted routing checks; these never contact services or start downloads."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "seerr_priority_bridge", ROOT / "scripts/seerr-streamingcommunity-bridge.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PriorityRoutingTests(unittest.TestCase):
    def bridge(self):
        bridge = module.Bridge.__new__(module.Bridge)
        bridge.hold_seerr = Mock(return_value=True)
        bridge.sc_api = Mock()
        bridge.save = Mock()
        bridge.prepare_fallback = Mock()
        bridge.assert_arr_disconnected = Mock()
        bridge.seerr_api = Mock(return_value={"title": "Example"})
        return bridge

    def test_admin_movie_completed_by_source_never_reaches_arr(self):
        bridge = self.bridge()
        bridge.sc_api.return_value = {"id": 71, "status": "available"}
        bridge.arr = SimpleNamespace(movie=Mock(), series=Mock())
        bridge.monitor_sc(10, "movie", [71], {"requester": 1, "certain": True})
        bridge.prepare_fallback.assert_not_called()
        bridge.arr.movie.assert_not_called()
        self.assertEqual(bridge.save.call_args.args[1], "done")

    def test_localized_subtitle_is_manual_match_instead_of_arr_fallback(self):
        source = {"id": 842,
                  "name": "Toy Story 2 - Woody & Buzz alla riscossa",
                  "release_date": None, "tmdb_id": None}
        chosen, certain = module.choose([source], ["Toy Story 2"], "1999", 863)
        self.assertEqual(chosen, source)
        self.assertFalse(certain)

    def test_only_failed_tv_episode_is_handed_to_fallback(self):
        bridge = self.bridge()
        rows = [
            {"id": 71, "status": "available", "season": 2, "episode_number": 1},
            {"id": 72, "status": "failed", "season": 2, "episode_number": 2},
        ]
        bridge.sc_api.side_effect = rows + rows
        context = {"requester": 1, "certain": True, "expected": {"2": [1, 2]}}
        bridge.monitor_sc(11, "tv", [71, 72], context)
        self.assertEqual(bridge.prepare_fallback.call_args.args[4], {2: {2}})

    def test_movie_failure_goes_to_radarr_once(self):
        bridge = self.bridge()
        bridge.arr = SimpleNamespace(movie=Mock(return_value=(21, False)),
                                     search_movie=Mock())
        context = {"tmdb_id": 123}
        bridge.dispatch_fallback(12, "movie", [71], context)
        bridge.arr.movie.assert_called_once()
        bridge.arr.search_movie.assert_not_called()
        self.assertEqual(bridge.save.call_args.args[1], "fallback_done")

    def test_new_radarr_movie_defers_search_until_intent_is_saved(self):
        from seerr_arr_fallback import ArrFallback

        arr = ArrFallback.__new__(ArrFallback)
        arr.movie_profile = 7
        arr.movie_root = "/data/Films"
        arr.minimum_availability = "released"

        def api(_kind, method, path, **kwargs):
            if method == "GET" and path == "/movie/lookup":
                return [{"tmdbId": 863, "title": "Toy Story 2", "year": 1999}]
            if method == "POST" and path == "/movie":
                self.assertEqual(kwargs["json"]["addOptions"],
                                 {"searchForMovie": False})
                return {"id": 201}
            self.fail(f"Unexpected API call {method} {path}")

        arr.call = Mock(side_effect=api)
        self.assertEqual(arr.movie(863, {"title": "Toy Story 2",
                                         "releaseDate": "1999-11-24"}),
                         (201, True))

    def test_movie_command_is_recorded_before_search(self):
        bridge = self.bridge()
        bridge.arr = SimpleNamespace(movie=Mock(return_value=(201, True)),
                                     search_movie=Mock())
        context = {"tmdb_id": 863}
        bridge.dispatch_fallback(13, "movie", [], context)
        self.assertEqual([call.args[1] for call in bridge.save.call_args_list],
                         ["fallback_command_intent", "fallback_done"])
        bridge.arr.search_movie.assert_called_once_with(201)

    def test_series_without_tvdb_id_uses_real_sonarr_lookup(self):
        from seerr_arr_fallback import ArrFallback

        arr = ArrFallback.__new__(ArrFallback)
        arr.call = Mock(return_value=[
            {"id": 22, "title": "Example", "year": 2024, "tvdbId": 54321},
            {"title": "Unrelated", "year": 2024, "tvdbId": 99},
        ])
        result = arr.lookup_series("Example", "2024", None)
        self.assertEqual(result["tvdbId"], 54321)
        self.assertEqual(arr.call.call_args.kwargs["params"], {"term": "Example"})

    def test_sonarr_searches_only_missing_episode_without_tvdb_id(self):
        from seerr_arr_fallback import ArrFallback

        arr = ArrFallback.__new__(ArrFallback)
        arr.lookup_series = Mock(return_value={
            "id": 30, "tvdbId": 54321, "title": "Example", "year": 2024})

        def api(_kind, method, path, **_kwargs):
            if method == "GET" and path == "/series":
                return [{"id": 30, "tvdbId": 54321, "monitored": True}]
            if method == "GET" and path == "/episode":
                return [{"id": 101, "seasonNumber": 2, "episodeNumber": 1,
                         "hasFile": True},
                        {"id": 102, "seasonNumber": 2, "episodeNumber": 2,
                         "hasFile": False}]
            if method == "PUT" and path == "/episode/monitor":
                return {}
            self.fail(f"Unexpected API call {method} {path}")

        arr.call = Mock(side_effect=api)
        arr.series_profile = 7
        arr.series_root = "/data/Series"
        series_id, episodes = arr.series("Example", "2024", None, {2: {2}})
        self.assertEqual((series_id, episodes), (30, [102]))
        arr.call.assert_any_call("tv", "PUT", "/episode/monitor",
                                 json={"episodeIds": [102], "monitored": True})

    def test_new_sonarr_series_does_not_search_whole_season(self):
        from seerr_arr_fallback import ArrFallback

        arr = ArrFallback.__new__(ArrFallback)
        arr.series_profile = 7
        arr.series_root = "/data/Series"
        arr.lookup_series = Mock(return_value={
            "title": "Example", "tvdbId": 54321,
            "seasons": [{"seasonNumber": 1}, {"seasonNumber": 2}]})

        def api(_kind, method, path, **kwargs):
            if method == "GET" and path == "/series":
                return []
            if method == "POST" and path == "/series":
                self.assertFalse(kwargs["json"]["addOptions"]
                                 ["searchForMissingEpisodes"])
                self.assertTrue(all(not season["monitored"] for season in
                                    kwargs["json"]["seasons"]))
                return {"id": 30, "monitored": True}
            if method == "GET" and path == "/episode":
                return [{"id": 102, "seasonNumber": 2,
                         "episodeNumber": 2, "hasFile": False}]
            if method == "PUT" and path == "/episode/monitor":
                return {}
            self.fail(f"Unexpected API call {method} {path}")

        arr.call = Mock(side_effect=api)
        self.assertEqual(arr.series("Example", "2024", None, {2: {2}}),
                         (30, [102]))


if __name__ == "__main__":
    unittest.main()
