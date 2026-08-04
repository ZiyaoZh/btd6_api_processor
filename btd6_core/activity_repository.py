from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
from urllib import request
from urllib.parse import urlparse
from uuid import uuid4

from PIL import Image

from api_raw_fetcher import (
    ApiClient,
    fetch_bosses,
    fetch_daily_challenges,
    fetch_odyssey,
    fetch_races,
)
from btd6_core.activity_models import (
    ActivityAsset,
    ActivitySnapshot,
    BloonModifiers,
    ChallengeConfig,
    InventoryItem,
    OdysseyConfig,
    PowerRule,
    TowerRule,
)
from btd6_core.cache_store import (
    OUTPUT_DIR,
    PROJECT_ROOT,
    get_cached_content,
    index_put,
    load_index,
    save_cached_file,
    save_index,
)
from btd6_core.common import sanitize_id, tr, tr_level_label, tr_reward_item


ACTIVITY_TYPES = {"race", "boss", "odyssey", "daily"}
EVENT_SCOPES = {"current", "upcoming", "latest"}
ODYSSEY_DIFFICULTIES = {"easy", "medium", "hard"}
SNAPSHOT_SCHEMA_VERSION = 1
ASSET_MAX_BYTES = 10 * 1024 * 1024

TOWER_CATEGORIES: dict[str, str] = {
    "DartMonkey": "primary",
    "BoomerangMonkey": "primary",
    "BombShooter": "primary",
    "TackShooter": "primary",
    "IceMonkey": "primary",
    "GlueGunner": "primary",
    "Desperado": "primary",
    "SniperMonkey": "military",
    "MonkeySub": "military",
    "MonkeyBuccaneer": "military",
    "MonkeyAce": "military",
    "HeliPilot": "military",
    "MortarMonkey": "military",
    "DartlingGunner": "military",
    "WizardMonkey": "magic",
    "SuperMonkey": "magic",
    "NinjaMonkey": "magic",
    "Alchemist": "magic",
    "Druid": "magic",
    "Mermonkey": "magic",
    "MerMonkey": "magic",
    "BananaFarm": "support",
    "SpikeFactory": "support",
    "MonkeyVillage": "support",
    "EngineerMonkey": "support",
    "BeastHandler": "support",
}


class AssetFetcher(Protocol):
    def fetch(self, url: str) -> ActivityAsset: ...


class MapAssetCache:
    def __init__(
        self,
        root: Path | None = None,
        *,
        timeout: int = 30,
        max_bytes: int = ASSET_MAX_BYTES,
    ) -> None:
        self.root = (root or (OUTPUT_DIR / "assets" / "maps")).resolve()
        self.timeout = max(1, int(timeout))
        self.max_bytes = max(1024, int(max_bytes))

    def fetch(self, url: str) -> ActivityAsset:
        source_url = str(url or "").strip()
        if not source_url:
            return ActivityAsset()

        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ActivityAsset(
                source_url=source_url,
                status="failed",
                error="invalid asset URL",
            )

        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".img"
        cache_name = f"{hashlib.sha256(source_url.encode('utf-8')).hexdigest()}{suffix}"
        destination = self.root / cache_name
        try:
            if destination.is_file() and 0 < destination.stat().st_size <= self.max_bytes:
                content = destination.read_bytes()
                try:
                    _validate_image(content)
                    return self._ready_asset(source_url, destination, content)
                except (OSError, ValueError):
                    destination.unlink(missing_ok=True)

            req = request.Request(
                source_url,
                headers={
                    "Accept": "image/*",
                    "User-Agent": "btd6-api-processor/2.0",
                },
            )
            with request.urlopen(req, timeout=self.timeout) as response:
                content = response.read(self.max_bytes + 1)
            if not content:
                raise RuntimeError("empty asset response")
            if len(content) > self.max_bytes:
                raise RuntimeError("asset exceeds size limit")
            _validate_image(content)

            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_bytes(content)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            return self._ready_asset(source_url, destination, content)
        except Exception as exc:  # noqa: BLE001
            return ActivityAsset(
                source_url=source_url,
                status="failed",
                fetched_at=_now_iso(),
                error=f"{type(exc).__name__}: {exc}"[:240],
            )

    @staticmethod
    def _ready_asset(source_url: str, path: Path, content: bytes) -> ActivityAsset:
        try:
            local_path = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            local_path = str(path)
        return ActivityAsset(
            source_url=source_url,
            local_path=local_path,
            sha256=hashlib.sha256(content).hexdigest(),
            fetched_at=_now_iso(),
            status="ready",
        )


class ActivityRepository:
    def __init__(
        self,
        client: ApiClient,
        translations: dict[str, dict[str, str]],
        *,
        asset_fetcher: AssetFetcher | None = None,
        now_ms: int | None = None,
    ) -> None:
        self.client = client
        self.translations = translations
        self.asset_fetcher = asset_fetcher or MapAssetCache()
        self.now_ms = now_ms if now_ms is not None else int(time.time() * 1000)

    def fetch_snapshot(
        self,
        activity_type: str,
        *,
        difficulty: str = "hard",
        event_scope: str = "latest",
    ) -> ActivitySnapshot:
        normalized_type = str(activity_type or "").strip().lower()
        normalized_scope = str(event_scope or "latest").strip().lower()
        normalized_difficulty = str(difficulty or "hard").strip().lower()
        if normalized_type not in ACTIVITY_TYPES:
            raise ValueError(f"不支持的活动类型: {activity_type}")
        if normalized_scope not in EVENT_SCOPES:
            raise ValueError(f"event_scope 仅支持: {', '.join(sorted(EVENT_SCOPES))}")
        if normalized_difficulty not in ODYSSEY_DIFFICULTIES:
            raise ValueError("difficulty 仅支持 easy、medium、hard")

        events = self._fetch_events(normalized_type)
        candidates = _event_candidates(events, normalized_scope, now_ms=self.now_ms)
        if not candidates:
            raise RuntimeError(f"{normalized_type} 没有符合 {normalized_scope} 范围的活动")

        errors: list[str] = []
        for event in candidates:
            try:
                if normalized_type == "race":
                    return self._build_race(event, normalized_scope)
                if normalized_type == "boss":
                    return self._build_boss(event, normalized_scope)
                if normalized_type == "odyssey":
                    return self._build_odyssey(event, normalized_scope, normalized_difficulty)
                return self._build_daily(event, normalized_scope)
            except RuntimeError as exc:
                errors.append(f"{_text(event.get('id')) or 'unknown'}: {exc}")
        last_error = errors[-1] if errors else "unknown error"
        raise RuntimeError(
            f"{normalized_type} 的 {len(candidates)} 个候选活动均不可用；最后错误: {last_error}"
        )

    def _fetch_events(self, activity_type: str) -> list[dict[str, Any]]:
        fetchers = {
            "race": fetch_races,
            "boss": fetch_bosses,
            "odyssey": fetch_odyssey,
            "daily": fetch_daily_challenges,
        }
        events = fetchers[activity_type](self.client)
        if not isinstance(events, list):
            raise RuntimeError(f"{activity_type} API body 不是数组")
        return [item for item in events if isinstance(item, dict)]

    def _build_race(self, event: dict[str, Any], event_scope: str) -> ActivitySnapshot:
        meta_url = _text(event.get("metadata"))
        challenge = self._fetch_challenge(meta_url, label="race")
        return self._base_snapshot(
            event,
            "race",
            event_scope,
            source_urls={
                "events": "/btd6/races",
                "metadata": meta_url,
                "leaderboard": _text(event.get("leaderboard")),
            },
            score_counts={"total": _int(event.get("totalScores"))},
            challenges=(challenge,) if challenge else (),
            known_event_fields={"id", "name", "start", "end", "totalScores", "leaderboard", "metadata"},
        )

    def _build_boss(self, event: dict[str, Any], event_scope: str) -> ActivitySnapshot:
        challenges: list[ChallengeConfig] = []
        source_urls: dict[str, str] = {"events": "/btd6/bosses"}
        for label, field_name in (
            ("standard", "metadataStandard"),
            ("elite", "metadataElite"),
        ):
            meta_url = _text(event.get(field_name))
            source_urls[f"metadata_{label}"] = meta_url
            challenge = self._fetch_challenge(meta_url, label=label)
            if challenge:
                challenges.append(challenge)
        source_urls["leaderboard_standard"] = _text(event.get("leaderboard_standard_players_1"))
        source_urls["leaderboard_elite"] = _text(event.get("leaderboard_elite_players_1"))
        boss_type_id = _text(event.get("bossType"))
        return self._base_snapshot(
            event,
            "boss",
            event_scope,
            source_urls=source_urls,
            score_counts={
                "standard": _int(event.get("totalScores_standard")),
                "elite": _int(event.get("totalScores_elite")),
            },
            challenges=tuple(challenges),
            attributes={
                "boss_type_id": boss_type_id,
                "boss_type_name": tr(boss_type_id, self.translations.get("boss_bloon", {})),
                "normal_scoring_type": _text(event.get("normalScoringType") or event.get("scoringType")),
                "elite_scoring_type": _text(event.get("eliteScoringType") or event.get("scoringType")),
            },
            known_event_fields={
                "id", "name", "start", "end", "bossType", "metadataStandard",
                "metadataElite", "totalScores_standard", "totalScores_elite",
                "normalScoringType", "eliteScoringType", "scoringType",
                "leaderboard_standard_players_1", "leaderboard_elite_players_1",
            },
        )

    def _build_odyssey(
        self,
        event: dict[str, Any],
        event_scope: str,
        difficulty: str,
    ) -> ActivitySnapshot:
        meta_field = f"metadata_{difficulty}"
        meta_url = _text(event.get(meta_field))
        if not meta_url:
            raise RuntimeError(f"征程缺少 {difficulty} metadata 地址")
        metadata = _body_dict(self.client.get(meta_url), meta_url)
        maps_url = _text(metadata.get("maps"))
        map_docs = _body_list(self.client.get(maps_url), maps_url) if maps_url else []
        maps = tuple(
            self._normalize_challenge(item, label=f"map_{index}")
            for index, item in enumerate(map_docs, start=1)
        )
        available_towers = tuple(self._normalize_towers(metadata.get("_availableTowers")))
        hero_ids = {item.tower_id for item in available_towers if item.is_hero}
        odyssey = OdysseyConfig(
            difficulty=difficulty,
            difficulty_name=tr_level_label(difficulty),
            is_extreme=bool(metadata.get("isExtreme", False)),
            max_hero_seats=_int(metadata.get("maxMonkeySeats")),
            max_monkeys_on_boat=_int(metadata.get("maxMonkeysOnBoat")),
            max_power_slots=_int(metadata.get("maxPowerSlots")),
            starting_health=_int(metadata.get("startingHealth")),
            rewards=tuple(self._normalize_rewards(metadata.get("_rewards"))),
            default_towers=tuple(
                self._normalize_inventory(
                    metadata.get("_defaultTowers"),
                    kind="tower",
                    hero_ids=hero_ids,
                )
            ),
            available_towers=available_towers,
            default_powers=tuple(self._normalize_inventory(metadata.get("_defaultPowers"), kind="power")),
            available_powers=tuple(self._normalize_powers(metadata.get("_availablePowers"))),
            maps=maps,
            unknown_fields=_unknown_fields(
                metadata,
                {
                    "id", "isExtreme", "maxMonkeySeats", "maxMonkeysOnBoat",
                    "maxPowerSlots", "startingHealth", "_rewards", "_availablePowers",
                    "_availableTowers", "_defaultPowers", "_defaultTowers", "maps",
                },
            ),
        )
        return self._base_snapshot(
            event,
            "odyssey",
            event_scope,
            source_urls={
                "events": "/btd6/odyssey",
                "metadata": meta_url,
                "maps": maps_url,
            },
            score_counts={},
            challenges=maps,
            odyssey=odyssey,
            known_event_fields={
                "id", "name", "description", "start", "end",
                "metadata_easy", "metadata_medium", "metadata_hard",
            },
        )

    def _build_daily(self, event: dict[str, Any], event_scope: str) -> ActivitySnapshot:
        meta_url = _text(event.get("metadata"))
        challenge = self._fetch_challenge(meta_url, label="daily")
        return self._base_snapshot(
            event,
            "daily",
            event_scope,
            source_urls={"events": "/btd6/challenges/filter/daily", "metadata": meta_url},
            score_counts={},
            challenges=(challenge,) if challenge else (),
            attributes={"created_at": _int(event.get("createdAt"))},
            known_event_fields={"id", "name", "description", "createdAt", "metadata"},
        )

    def _base_snapshot(
        self,
        event: dict[str, Any],
        activity_type: str,
        event_scope: str,
        *,
        source_urls: dict[str, str],
        score_counts: dict[str, int | None],
        challenges: tuple[ChallengeConfig, ...],
        known_event_fields: set[str],
        odyssey: OdysseyConfig | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> ActivitySnapshot:
        start_at = _int(event.get("start"))
        end_at = _int(event.get("end"))
        normalized_attributes = attributes or {}
        status_start_at = start_at
        if activity_type == "daily":
            status_start_at = _int(normalized_attributes.get("created_at"))
        return ActivitySnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            activity_type=activity_type,
            event_id=_text(event.get("id")) or "unknown",
            name=_text(event.get("name")) or "未知活动",
            description=_text(event.get("description")),
            start_at=start_at,
            end_at=end_at,
            status=event_status(status_start_at, end_at, now_ms=self.now_ms),
            event_scope=event_scope,
            fetched_at=_now_iso(),
            score_counts=score_counts,
            source_urls={key: value for key, value in source_urls.items() if value},
            attributes=normalized_attributes,
            challenges=challenges,
            odyssey=odyssey,
            unknown_fields=_unknown_fields(event, known_event_fields),
        )

    def _fetch_challenge(self, url: str, *, label: str) -> ChallengeConfig | None:
        if not url:
            return None
        return self._normalize_challenge(_body_dict(self.client.get(url), url), label=label)

    def _normalize_challenge(self, doc: dict[str, Any], *, label: str) -> ChallengeConfig:
        modifiers = doc.get("_bloonModifiers") if isinstance(doc.get("_bloonModifiers"), dict) else {}
        health = modifiers.get("healthMultipliers") if isinstance(modifiers.get("healthMultipliers"), dict) else {}
        map_id = _text(doc.get("map"))
        difficulty_id = _text(doc.get("difficulty"))
        mode_id = _text(doc.get("mode"))
        is_odyssey_map = label.startswith("map_")
        raw_lives = _int(doc.get("lives"))
        raw_max_lives = _int(doc.get("maxLives"))
        raw_max_towers = _int(doc.get("maxTowers"))
        raw_max_paragons = _int(doc.get("maxParagons"))
        unknown_fields = _unknown_fields(
            doc,
            {
                "map", "mapURL", "mode", "difficulty", "disableDoubleCash",
                "disableInstas", "disableMK", "disablePowers", "disableSelling",
                "startingCash", "abilityCooldownReductionMultiplier", "noContinues",
                "removeableCostMultiplier", "lives", "maxLives", "startRound",
                "endRound", "maxTowers", "maxParagons", "_bloonModifiers", "_towers",
            },
        )
        normalized_sentinels = {
            key: value
            for key, value in {
                "lives": raw_lives if is_odyssey_map and raw_lives == 0 else None,
                "maxLives": raw_max_lives if is_odyssey_map and raw_max_lives == 0 else None,
                "maxTowers": raw_max_towers if raw_max_towers in {-1, 0, 9999} else None,
                "maxParagons": (
                    raw_max_paragons
                    if raw_max_paragons in {-1, 9999}
                    or (is_odyssey_map and raw_max_paragons == 0)
                    else None
                ),
            }.items()
            if value is not None
        }
        if normalized_sentinels:
            unknown_fields["normalizedSentinels"] = normalized_sentinels
        return ChallengeConfig(
            label=label,
            map_id=map_id,
            map_name=tr(map_id, self.translations.get("map", {})),
            map_asset=self.asset_fetcher.fetch(_text(doc.get("mapURL"))),
            difficulty_id=difficulty_id,
            difficulty_name=tr(difficulty_id, self.translations.get("difficulty", {})),
            mode_id=mode_id,
            mode_name=tr(mode_id, self.translations.get("mode", {})),
            start_round=_int(doc.get("startRound")),
            end_round=_int(doc.get("endRound")),
            starting_cash=_int(doc.get("startingCash")),
            lives=None if is_odyssey_map and raw_lives == 0 else raw_lives,
            max_lives=None if is_odyssey_map and raw_max_lives == 0 else raw_max_lives,
            max_towers=_normalize_unlimited(raw_max_towers, zero_is_unlimited=True),
            max_paragons=(
                None
                if is_odyssey_map and raw_max_paragons == 0
                else _normalize_unlimited(raw_max_paragons)
            ),
            disable_double_cash=bool(doc.get("disableDoubleCash", False)),
            disable_instas=bool(doc.get("disableInstas", False)),
            disable_monkey_knowledge=bool(doc.get("disableMK", False)),
            disable_powers=bool(doc.get("disablePowers", False)),
            disable_selling=bool(doc.get("disableSelling", False)),
            no_continues=bool(doc.get("noContinues", False)),
            ability_cooldown_multiplier=_number(doc.get("abilityCooldownReductionMultiplier")),
            removable_cost_multiplier=_number(doc.get("removeableCostMultiplier")),
            bloon_modifiers=BloonModifiers(
                speed=_number(modifiers.get("speedMultiplier")),
                moab_speed=_number(modifiers.get("moabSpeedMultiplier")),
                boss_speed=_number(modifiers.get("bossSpeedMultiplier")),
                regrow_rate=_number(modifiers.get("regrowRateMultiplier")),
                bloon_health=_number(health.get("bloons")),
                moab_health=_number(health.get("moabs")),
                boss_health=_number(health.get("boss")),
                all_camo=bool(modifiers.get("allCamo", False)),
                all_regen=bool(modifiers.get("allRegen", False)),
                unknown_fields=_unknown_fields(
                    modifiers,
                    {
                        "speedMultiplier", "moabSpeedMultiplier", "bossSpeedMultiplier",
                        "regrowRateMultiplier", "healthMultipliers", "allCamo", "allRegen",
                    },
                ),
            ),
            tower_rules=tuple(self._normalize_towers(doc.get("_towers"))),
            unknown_fields=unknown_fields,
        )

    def _normalize_towers(self, value: Any) -> list[TowerRule]:
        if not isinstance(value, list):
            return []
        rules: list[TowerRule] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            tower_id = _text(item.get("tower"))
            if not tower_id:
                continue
            is_hero = bool(item.get("isHero", False))
            raw_max = _int(item.get("max"))
            max_tiers = tuple(
                max(0, min(5, 5 - (_int(item.get(field_name)) or 0)))
                for field_name in (
                    "path1NumBlockedTiers",
                    "path2NumBlockedTiers",
                    "path3NumBlockedTiers",
                )
            )
            unknown_fields = _unknown_fields(
                item,
                {
                    "tower", "max", "path1NumBlockedTiers",
                    "path2NumBlockedTiers", "path3NumBlockedTiers", "isHero",
                },
            )
            if raw_max is None:
                unknown_fields["maxMissing"] = True
            rules.append(
                TowerRule(
                    tower_id=tower_id,
                    name=tr(
                        tower_id,
                        self.translations.get("hero" if is_hero else "tower", {}),
                    ),
                    category="hero" if is_hero else TOWER_CATEGORIES.get(tower_id, "unknown"),
                    is_hero=is_hero,
                    is_available=raw_max is not None and raw_max != 0,
                    max_count=_normalize_unlimited(raw_max),
                    max_tiers=max_tiers,  # type: ignore[arg-type]
                    unknown_fields=unknown_fields,
                )
            )
        return rules

    def _normalize_inventory(
        self,
        value: Any,
        *,
        kind: str,
        hero_ids: set[str] | None = None,
    ) -> list[InventoryItem]:
        if not isinstance(value, list):
            return []
        items: list[InventoryItem] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            item_id = _text(item.get("name"))
            if not item_id:
                continue
            hero_name = tr(item_id, self.translations.get("hero", {}))
            is_hero = kind == "tower" and (
                item_id in (hero_ids or set()) or hero_name != item_id
            )
            table_name = "hero" if is_hero else ("tower" if kind == "tower" else "power")
            items.append(
                InventoryItem(
                    item_id=item_id,
                    name=tr(item_id, self.translations.get(table_name, {})),
                    quantity=_int(item.get("quantity")),
                    category=("hero" if is_hero else TOWER_CATEGORIES.get(item_id, "unknown")) if kind == "tower" else "power",
                    is_hero=is_hero,
                    unknown_fields=_unknown_fields(item, {"name", "quantity"}),
                )
            )
        return items

    def _normalize_powers(self, value: Any) -> list[PowerRule]:
        if not isinstance(value, list):
            return []
        rules: list[PowerRule] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            power_id = _text(item.get("power"))
            if not power_id:
                continue
            raw_max = _int(item.get("max"))
            rules.append(
                PowerRule(
                    power_id=power_id,
                    name=tr(power_id, self.translations.get("power", {})),
                    is_available=raw_max is not None and raw_max != 0,
                    max_count=_normalize_unlimited(raw_max),
                    unknown_fields=_unknown_fields(item, {"power", "max"}),
                )
            )
        return rules

    def _normalize_rewards(self, value: Any) -> list[InventoryItem]:
        if not isinstance(value, list):
            return []
        rewards: list[InventoryItem] = []
        for raw_item in value:
            raw = _text(raw_item)
            if not raw:
                continue
            item_id, _, payload = raw.partition(":")
            quantity = _int_string(payload) if item_id != "InstaMonkey" else None
            translated = tr_reward_item(raw, self.translations)
            display_name = translated.split(":", 1)[0] if quantity is not None else translated
            rewards.append(
                InventoryItem(
                    item_id=item_id or raw,
                    name=display_name,
                    quantity=quantity,
                    category="reward",
                    unknown_fields={"raw": raw},
                )
            )
        return rewards


def select_event(
    events: list[dict[str, Any]],
    event_scope: str,
    *,
    now_ms: int | None = None,
) -> dict[str, Any] | None:
    candidates = _event_candidates(events, event_scope, now_ms=now_ms)
    return candidates[0] if candidates else None


def _event_candidates(
    events: list[dict[str, Any]],
    event_scope: str,
    *,
    now_ms: int | None = None,
) -> list[dict[str, Any]]:
    if not events:
        return []
    scope = str(event_scope or "latest").strip().lower()
    if scope not in EVENT_SCOPES:
        raise ValueError(f"不支持的 event_scope: {event_scope}")
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    timed = [
        item
        for item in events
        if _int(item.get("start")) is not None
    ]
    created = [item for item in events if _int(item.get("createdAt")) is not None]
    if scope == "current":
        matches = [
            item
            for item in timed
            if (_int(item.get("start")) or 0) <= current_ms
            and (_int(item.get("end")) is None or current_ms <= (_int(item.get("end")) or 0))
        ]
        if matches:
            return sorted(matches, key=lambda item: _int(item.get("start")) or -1, reverse=True)
        if not timed:
            published = [item for item in created if (_int(item.get("createdAt")) or 0) <= current_ms]
            return sorted(published, key=lambda item: _int(item.get("createdAt")) or -1, reverse=True)
        return []
    if scope == "upcoming":
        matches = [item for item in timed if (_int(item.get("start")) or 0) > current_ms]
        if matches:
            return sorted(matches, key=lambda item: _int(item.get("start")) or 10**30)
        if not timed:
            announced = [item for item in created if (_int(item.get("createdAt")) or 0) > current_ms]
            return sorted(announced, key=lambda item: _int(item.get("createdAt")) or 10**30)
        return []

    if timed:
        return sorted(timed, key=lambda item: _int(item.get("start")) or -1, reverse=True)
    return sorted(events, key=lambda item: _int(item.get("createdAt")) or -1, reverse=True)


def event_status(start_at: int | None, end_at: int | None, *, now_ms: int | None = None) -> str:
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    if start_at is not None and current_ms < start_at:
        return "upcoming"
    if end_at is not None and current_ms > end_at:
        return "ended"
    if start_at is not None and (end_at is None or current_ms <= end_at):
        return "current"
    return "unknown"


def resolve_activity_snapshot(
    client: ApiClient,
    translations: dict[str, dict[str, str]],
    activity_type: str,
    *,
    difficulty: str = "hard",
    event_scope: str = "latest",
    refresh: bool = False,
) -> tuple[Path, ActivitySnapshot, bool]:
    normalized_type = str(activity_type or "").strip().lower()
    normalized_difficulty = str(difficulty or "hard").strip().lower()
    normalized_scope = str(event_scope or "latest").strip().lower()
    variant = normalized_difficulty if normalized_type == "odyssey" else "default"
    key = f"activity-snapshot:{normalized_type}:{variant}:{normalized_scope}"
    index_data = load_index()
    if not refresh:
        cached_path, cached_content = get_cached_content(index_data, key)
        cached_snapshot = _load_snapshot(cached_content)
        if cached_path and cached_snapshot is not None:
            desired_path = _snapshot_output_path(
                cached_snapshot,
                normalized_type,
                variant,
                normalized_scope,
            )
            if cached_path != desired_path:
                save_cached_file(desired_path, cached_content or "")
                index_put(index_data, key, cached_snapshot.event_id, desired_path)
                save_index(index_data)
                cached_path = desired_path
            return cached_path, cached_snapshot, True
    stale_path, stale_content = get_cached_content(index_data, key, allow_stale=True)
    stale_snapshot = _load_snapshot(stale_content)

    try:
        snapshot = ActivityRepository(client, translations).fetch_snapshot(
            normalized_type,
            difficulty=normalized_difficulty,
            event_scope=normalized_scope,
        )
        file_path = _snapshot_output_path(
            snapshot,
            normalized_type,
            variant,
            normalized_scope,
        )
        content = json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2)
        save_cached_file(file_path, content)
        index_put(index_data, key, snapshot.event_id, file_path)
        save_index(index_data)
        return file_path, snapshot, False
    except Exception as exc:  # noqa: BLE001
        if stale_path and stale_snapshot is not None:
            return stale_path, stale_snapshot, True
        raise RuntimeError(f"{normalized_type} 活动快照刷新失败且无可用缓存: {exc}") from exc


def _load_snapshot(content: str | None) -> ActivitySnapshot | None:
    if not content:
        return None
    try:
        value = json.loads(content)
        return ActivitySnapshot.from_dict(value) if isinstance(value, dict) else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _snapshot_output_path(
    snapshot: ActivitySnapshot,
    activity_type: str,
    variant: str,
    event_scope: str,
) -> Path:
    filename = f"{sanitize_id(snapshot.event_id)}_{variant}_{event_scope}.json"
    return OUTPUT_DIR / "snapshots" / activity_type / filename


def _body_dict(payload: dict[str, Any], url: str) -> dict[str, Any]:
    body = payload.get("body")
    if not isinstance(body, dict):
        raise RuntimeError(f"端点未返回对象: {url}")
    return body


def _body_list(payload: dict[str, Any], url: str) -> list[dict[str, Any]]:
    body = payload.get("body")
    if not isinstance(body, list):
        raise RuntimeError(f"端点未返回数组: {url}")
    return [item for item in body if isinstance(item, dict)]


def _unknown_fields(value: dict[str, Any], known: set[str]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in known}


def _normalize_unlimited(value: Any, *, zero_is_unlimited: bool = False) -> int | None:
    parsed = _int(value)
    if parsed is None or parsed == -1 or parsed == 9999 or (zero_is_unlimited and parsed == 0):
        return None
    return parsed


def _number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 1.0


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _int_string(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _validate_image(content: bytes) -> None:
    with Image.open(BytesIO(content)) as image:
        if image.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError(f"unsupported map image format: {image.format}")
        image.verify()
