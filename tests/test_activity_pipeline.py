from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from PIL import Image, ImageStat

from btd6_core.activity_formatter import (
    challenge_limit_label,
    format_activity_snapshot,
    format_activity_time,
)
from btd6_core.activity_models import ActivityAsset, BloonModifiers
from btd6_core.activity_renderer import render_activity_brief
from btd6_core.activity_repository import (
    ActivityRepository,
    MapAssetCache,
    resolve_activity_snapshot,
    select_event,
)
from btd6_core.common import parse_translation_tables


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TRANSLATIONS = parse_translation_tables(ROOT / "translate.md")


class FixtureClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, path_or_url: str) -> dict[str, Any]:
        self.calls.append(path_or_url)
        if path_or_url not in self.responses:
            raise RuntimeError(f"unexpected fixture URL: {path_or_url}")
        return self.responses[path_or_url]


class FailingClient:
    def get(self, path_or_url: str) -> dict[str, Any]:
        raise RuntimeError("offline")


class StaticAssetFetcher:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.urls: list[str] = []

    def fetch(self, url: str) -> ActivityAsset:
        self.urls.append(url)
        if self.path is None:
            return ActivityAsset(source_url=url, status="failed", error="fixture")
        content = self.path.read_bytes()
        return ActivityAsset(
            source_url=url,
            local_path=str(self.path),
            sha256=hashlib.sha256(content).hexdigest(),
            fetched_at="2026-08-04T02:00:00+00:00",
            status="ready",
        )


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _race_client() -> FixtureClient:
    fixture = _fixture("race_end_of_line.json")
    event = fixture["list_response"]["body"][0]
    return FixtureClient(
        {
            "/btd6/races": fixture["list_response"],
            event["metadata"]: fixture["metadata_response"],
        }
    )


def _odyssey_client() -> FixtureClient:
    fixture = _fixture("odyssey_magicians_trick_hard.json")
    event = fixture["list_response"]["body"][0]
    metadata = fixture["metadata_response"]["body"]
    return FixtureClient(
        {
            "/btd6/odyssey": fixture["list_response"],
            event["metadata_hard"]: fixture["metadata_response"],
            metadata["maps"]: fixture["maps_response"],
        }
    )


class ActivityPipelineTests(unittest.TestCase):
    def test_activity_time_defaults_to_sample_utc_plus_eight(self) -> None:
        with patch.dict("os.environ", {"BTD6_DISPLAY_UTC_OFFSET_HOURS": "8"}):
            self.assertEqual(format_activity_time(1784253600001), "2026-07-17 10:00")

    def test_map_asset_cache_records_invalid_image_as_failure(self) -> None:
        class InvalidResponse:
            def __enter__(self) -> InvalidResponse:
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def read(self, size: int) -> bytes:
                return b"not an image"

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = MapAssetCache(Path(temp_dir))
            with patch(
                "btd6_core.activity_repository.request.urlopen",
                return_value=InvalidResponse(),
            ):
                asset = cache.fetch("https://example.test/map.png")

        self.assertEqual(asset.status, "failed")
        self.assertIn("UnidentifiedImageError", asset.error)
        self.assertEqual(asset.source_url, "https://example.test/map.png")

    def test_event_selector_distinguishes_current_upcoming_and_latest(self) -> None:
        events = [
            {"id": "ended", "start": 100, "end": 200},
            {"id": "current", "start": 300, "end": 500},
            {"id": "next", "start": 600, "end": 700},
            {"id": "latest", "start": 800, "end": 900},
        ]

        self.assertEqual(select_event(events, "current", now_ms=400)["id"], "current")  # type: ignore[index]
        self.assertEqual(select_event(events, "upcoming", now_ms=400)["id"], "next")  # type: ignore[index]
        self.assertEqual(select_event(events, "latest", now_ms=400)["id"], "latest")  # type: ignore[index]
        self.assertIsNone(select_event(events, "current", now_ms=1000))

        daily_events = [
            {"id": "published", "createdAt": 300},
            {"id": "announced", "createdAt": 600},
        ]
        self.assertEqual(select_event(daily_events, "current", now_ms=400)["id"], "published")  # type: ignore[index]
        self.assertEqual(select_event(daily_events, "upcoming", now_ms=400)["id"], "announced")  # type: ignore[index]

    def test_race_fixture_preserves_map_bans_categories_and_unknown_fields(self) -> None:
        fixture = _fixture("race_end_of_line.json")
        event = fixture["list_response"]["body"][0]
        assets = StaticAssetFetcher()
        snapshot = ActivityRepository(
            _race_client(),  # type: ignore[arg-type]
            TRANSLATIONS,
            asset_fetcher=assets,
            now_ms=event["start"] + 1,
        ).fetch_snapshot("race", event_scope="current")

        self.assertEqual(snapshot.event_id, "End_of_the_Line_mrkd24wf")
        self.assertEqual(len(snapshot.challenges), 1)
        challenge = snapshot.challenges[0]
        self.assertEqual(challenge.map_id, "EndOfTheRoad")
        self.assertEqual(challenge.map_name, "路的尽头")
        self.assertTrue(challenge.map_asset.source_url.endswith("MapSelectEndOfTheRoadButton.png"))
        self.assertIsNone(challenge.max_towers)
        self.assertEqual(challenge_limit_label(challenge, "max_towers"), "无限制")
        self.assertEqual(len(challenge.tower_rules), 44)
        self.assertIn("roundSets", challenge.unknown_fields)
        self.assertIn("_powers", challenge.unknown_fields)

        available_heroes = [item.name for item in challenge.tower_rules if item.is_hero and item.is_available]
        banned_monkeys = [item.name for item in challenge.tower_rules if not item.is_hero and not item.is_available]
        self.assertEqual(available_heroes, ["格温多琳"])
        self.assertEqual(len(banned_monkeys), 17)
        self.assertIn("炼金术士", banned_monkeys)
        self.assertNotIn("昆西", banned_monkeys)
        self.assertEqual(assets.urls, [challenge.map_asset.source_url])

    def test_odyssey_fixture_parses_all_inventory_groups_and_ordered_maps(self) -> None:
        fixture = _fixture("odyssey_magicians_trick_hard.json")
        event = fixture["list_response"]["body"][0]
        assets = StaticAssetFetcher()
        snapshot = ActivityRepository(
            _odyssey_client(),  # type: ignore[arg-type]
            TRANSLATIONS,
            asset_fetcher=assets,
            now_ms=event["start"] + 1,
        ).fetch_snapshot("odyssey", difficulty="hard", event_scope="current")

        odyssey = snapshot.odyssey
        self.assertIsNotNone(odyssey)
        assert odyssey is not None
        self.assertEqual(odyssey.difficulty, "hard")
        self.assertEqual(odyssey.difficulty_name, "困难")
        self.assertEqual(odyssey.max_hero_seats, 6)
        self.assertEqual(len(odyssey.default_towers), 7)
        self.assertEqual(len(odyssey.available_towers), 16)
        self.assertEqual(len(odyssey.default_powers), 8)
        self.assertEqual(len(odyssey.available_powers), 19)
        self.assertEqual([item.map_id for item in odyssey.maps], ["SkullTweak", "TheCabin", "Carved", "AdorasTemple", "DarkPath"])
        self.assertEqual(odyssey.maps[0].map_name, "骷髅变奏")
        self.assertEqual(odyssey.maps[-1].map_name, "黑暗之径")
        self.assertEqual(
            challenge_limit_label(odyssey.maps[0], "max_paragons"),
            "10",
        )
        self.assertEqual(len(assets.urls), 5)
        self.assertTrue(all(item.startswith("https://static-api.nkstatic.com/") for item in assets.urls))
        self.assertEqual(odyssey.rewards[0].name, "猴钞")
        self.assertEqual(odyssey.rewards[0].quantity, 400)

    def test_missing_fields_and_unknown_tower_fail_soft(self) -> None:
        event = {
            "id": "future_event",
            "name": "Future",
            "start": 100,
            "end": 200,
            "metadata": "https://example.test/meta",
        }
        client = FixtureClient(
            {
                "/btd6/races": {"success": True, "body": [event]},
                event["metadata"]: {
                    "success": True,
                    "body": {
                        "map": "FutureMap",
                        "futureRule": {"enabled": True},
                        "_towers": [{"tower": "FutureMonkey", "isHero": False}],
                    },
                },
            }
        )
        repository = ActivityRepository(
            client,  # type: ignore[arg-type]
            TRANSLATIONS,
            asset_fetcher=StaticAssetFetcher(),
            now_ms=150,
        )
        snapshot = repository.fetch_snapshot("race", event_scope="current")

        challenge = snapshot.challenges[0]
        self.assertEqual(challenge.map_name, "FutureMap")
        self.assertEqual(challenge.unknown_fields["futureRule"], {"enabled": True})
        self.assertEqual(challenge.tower_rules[0].category, "unknown")
        self.assertFalse(challenge.tower_rules[0].is_hero)
        self.assertFalse(challenge.tower_rules[0].is_available)
        self.assertTrue(challenge.tower_rules[0].unknown_fields["maxMissing"])
        self.assertEqual(challenge_limit_label(challenge, "max_towers"), "未知")
        self.assertNotIn("禁用防御塔", format_activity_snapshot(snapshot))
        unset_odyssey_map = repository._normalize_challenge(  # noqa: SLF001
            {"maxParagons": 0},
            label="map_1",
        )
        self.assertEqual(
            challenge_limit_label(unset_odyssey_map, "max_paragons"),
            "未设置",
        )

    def test_repository_skips_dangling_latest_daily_metadata(self) -> None:
        events = [
            {"id": "broken", "name": "Broken", "createdAt": 200, "metadata": "https://example.test/broken"},
            {"id": "valid", "name": "Valid", "createdAt": 100, "metadata": "https://example.test/valid"},
        ]
        client = FixtureClient(
            {
                "/btd6/challenges/filter/daily": {"success": True, "body": events},
                "https://example.test/valid": {
                    "success": True,
                    "body": {"map": "Logs", "mode": "Standard", "difficulty": "Easy"},
                },
            }
        )

        snapshot = ActivityRepository(
            client,  # type: ignore[arg-type]
            TRANSLATIONS,
            asset_fetcher=StaticAssetFetcher(),
        ).fetch_snapshot("daily", event_scope="latest")

        self.assertEqual(snapshot.event_id, "valid")
        self.assertEqual(snapshot.status, "unknown")
        self.assertIsNone(snapshot.start_at)
        self.assertEqual(snapshot.attributes["created_at"], 100)
        self.assertEqual(client.calls[-2:], ["https://example.test/broken", "https://example.test/valid"])

    def test_snapshot_cache_uses_stale_json_when_refresh_fails(self) -> None:
        fixture = _fixture("race_end_of_line.json")
        event = fixture["list_response"]["body"][0]
        snapshot = ActivityRepository(
            _race_client(),  # type: ignore[arg-type]
            TRANSLATIONS,
            asset_fetcher=StaticAssetFetcher(),
            now_ms=event["start"] + 1,
        ).fetch_snapshot("race", event_scope="current")
        content = json.dumps(snapshot.to_dict(), ensure_ascii=False)

        with tempfile.TemporaryDirectory() as temp_dir:
            stale_path = Path(temp_dir) / "stale.json"
            stale_path.write_text(content, encoding="utf-8")
            with (
                patch("btd6_core.activity_repository.load_index", return_value={"items": {}}),
                patch(
                    "btd6_core.activity_repository.get_cached_content",
                    side_effect=[(None, None), (stale_path, content)],
                ),
            ):
                path, restored, cached = resolve_activity_snapshot(
                    FailingClient(),  # type: ignore[arg-type]
                    TRANSLATIONS,
                    "race",
                    event_scope="current",
                )

        self.assertTrue(cached)
        self.assertEqual(path, stale_path)
        self.assertEqual(restored.event_id, snapshot.event_id)
        self.assertEqual(restored.challenges[0].tower_rules, snapshot.challenges[0].tower_rules)

    def test_renderers_create_deterministic_nonblank_dynamic_images(self) -> None:
        race_fixture = _fixture("race_end_of_line.json")
        odyssey_fixture = _fixture("odyssey_magicians_trick_hard.json")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset = root / "map.png"
            source = Image.new("RGB", (510, 510), "#35a76f")
            source.paste(Image.new("RGB", (240, 240), "#f3c544"), (135, 135))
            source.save(asset)
            fetcher = StaticAssetFetcher(asset)
            race_event = race_fixture["list_response"]["body"][0]
            odyssey_event = odyssey_fixture["list_response"]["body"][0]
            race = ActivityRepository(
                _race_client(),  # type: ignore[arg-type]
                TRANSLATIONS,
                asset_fetcher=fetcher,
                now_ms=race_event["start"] + 1,
            ).fetch_snapshot("race", event_scope="current")
            odyssey = ActivityRepository(
                _odyssey_client(),  # type: ignore[arg-type]
                TRANSLATIONS,
                asset_fetcher=fetcher,
                now_ms=odyssey_event["start"] + 1,
            ).fetch_snapshot("odyssey", difficulty="hard", event_scope="current")

            race_a = root / "race_a.png"
            race_b = root / "race_b.png"
            odyssey_path = root / "odyssey.png"
            odyssey_base_path = root / "odyssey_base.png"
            odyssey_rules_path = root / "odyssey_rules.png"
            render_activity_brief(race, race_a)
            render_activity_brief(race, race_b)
            render_activity_brief(odyssey, odyssey_path)

            assert odyssey.odyssey is not None
            base_map = odyssey.odyssey.maps[0]
            base_odyssey = replace(odyssey.odyssey, maps=(base_map,))
            render_activity_brief(
                replace(odyssey, odyssey=base_odyssey, challenges=(base_map,)),
                odyssey_base_path,
            )
            rules_map = replace(
                base_map,
                disable_double_cash=True,
                disable_instas=True,
                disable_monkey_knowledge=True,
                disable_powers=True,
                disable_selling=True,
                no_continues=True,
                ability_cooldown_multiplier=0.5,
                removable_cost_multiplier=2.0,
                bloon_modifiers=BloonModifiers(
                    speed=1.1,
                    moab_speed=1.2,
                    boss_speed=1.3,
                    regrow_rate=1.4,
                    bloon_health=1.5,
                    moab_health=1.6,
                    boss_health=1.7,
                    all_camo=True,
                    all_regen=True,
                ),
            )
            rules_odyssey = replace(odyssey.odyssey, maps=(rules_map,))
            render_activity_brief(
                replace(odyssey, odyssey=rules_odyssey, challenges=(rules_map,)),
                odyssey_rules_path,
            )

            self.assertEqual(hashlib.sha256(race_a.read_bytes()).digest(), hashlib.sha256(race_b.read_bytes()).digest())
            with Image.open(race_a) as image:
                self.assertEqual(image.width, 1080)
                self.assertGreater(image.height, 900)
                self.assertGreater(sum(ImageStat.Stat(image).var), 100)
            with Image.open(odyssey_path) as image:
                self.assertEqual(image.width, 1080)
                self.assertGreater(image.height, 2000)
                self.assertGreater(sum(ImageStat.Stat(image).var), 100)
            with Image.open(odyssey_base_path) as base_image, Image.open(
                odyssey_rules_path
            ) as rules_image:
                self.assertGreater(rules_image.height, base_image.height)


if __name__ == "__main__":
    unittest.main()
