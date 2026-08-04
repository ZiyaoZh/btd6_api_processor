from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActivityAsset:
    source_url: str = ""
    local_path: str = ""
    sha256: str = ""
    fetched_at: str = ""
    status: str = "missing"
    error: str = ""


@dataclass(frozen=True)
class BloonModifiers:
    speed: float = 1.0
    moab_speed: float = 1.0
    boss_speed: float = 1.0
    regrow_rate: float = 1.0
    bloon_health: float = 1.0
    moab_health: float = 1.0
    boss_health: float = 1.0
    all_camo: bool = False
    all_regen: bool = False
    unknown_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TowerRule:
    tower_id: str
    name: str
    category: str
    is_hero: bool
    is_available: bool
    max_count: int | None
    max_tiers: tuple[int, int, int]
    unknown_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChallengeConfig:
    label: str = ""
    map_id: str = ""
    map_name: str = ""
    map_asset: ActivityAsset = field(default_factory=ActivityAsset)
    difficulty_id: str = ""
    difficulty_name: str = ""
    mode_id: str = ""
    mode_name: str = ""
    start_round: int | None = None
    end_round: int | None = None
    starting_cash: int | None = None
    lives: int | None = None
    max_lives: int | None = None
    max_towers: int | None = None
    max_paragons: int | None = None
    disable_double_cash: bool = False
    disable_instas: bool = False
    disable_monkey_knowledge: bool = False
    disable_powers: bool = False
    disable_selling: bool = False
    no_continues: bool = False
    ability_cooldown_multiplier: float = 1.0
    removable_cost_multiplier: float = 1.0
    bloon_modifiers: BloonModifiers = field(default_factory=BloonModifiers)
    tower_rules: tuple[TowerRule, ...] = ()
    unknown_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventoryItem:
    item_id: str
    name: str
    quantity: int | None
    category: str = ""
    is_hero: bool = False
    unknown_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PowerRule:
    power_id: str
    name: str
    is_available: bool
    max_count: int | None
    unknown_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OdysseyConfig:
    difficulty: str
    difficulty_name: str
    is_extreme: bool = False
    max_hero_seats: int | None = None
    max_monkeys_on_boat: int | None = None
    max_power_slots: int | None = None
    starting_health: int | None = None
    rewards: tuple[InventoryItem, ...] = ()
    default_towers: tuple[InventoryItem, ...] = ()
    available_towers: tuple[TowerRule, ...] = ()
    default_powers: tuple[InventoryItem, ...] = ()
    available_powers: tuple[PowerRule, ...] = ()
    maps: tuple[ChallengeConfig, ...] = ()
    unknown_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActivitySnapshot:
    schema_version: int
    activity_type: str
    event_id: str
    name: str
    description: str
    start_at: int | None
    end_at: int | None
    status: str
    event_scope: str
    fetched_at: str
    score_counts: dict[str, int | None] = field(default_factory=dict)
    source_urls: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    challenges: tuple[ChallengeConfig, ...] = ()
    odyssey: OdysseyConfig | None = None
    unknown_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ActivitySnapshot:
        challenges = tuple(
            _challenge_from_dict(item)
            for item in _dict_list(value.get("challenges"))
        )
        odyssey_value = value.get("odyssey")
        odyssey = (
            _odyssey_from_dict(odyssey_value)
            if isinstance(odyssey_value, dict)
            else None
        )
        return cls(
            schema_version=_as_int(value.get("schema_version")) or 1,
            activity_type=str(value.get("activity_type", "")),
            event_id=str(value.get("event_id", "")),
            name=str(value.get("name", "")),
            description=str(value.get("description", "")),
            start_at=_as_int(value.get("start_at")),
            end_at=_as_int(value.get("end_at")),
            status=str(value.get("status", "unknown")),
            event_scope=str(value.get("event_scope", "latest")),
            fetched_at=str(value.get("fetched_at", "")),
            score_counts={
                str(key): _as_int(item)
                for key, item in _as_dict(value.get("score_counts")).items()
            },
            source_urls={
                str(key): str(item)
                for key, item in _as_dict(value.get("source_urls")).items()
            },
            attributes=_as_dict(value.get("attributes")),
            challenges=challenges,
            odyssey=odyssey,
            unknown_fields=_as_dict(value.get("unknown_fields")),
        )


def _asset_from_dict(value: Any) -> ActivityAsset:
    data = _as_dict(value)
    return ActivityAsset(
        source_url=str(data.get("source_url", "")),
        local_path=str(data.get("local_path", "")),
        sha256=str(data.get("sha256", "")),
        fetched_at=str(data.get("fetched_at", "")),
        status=str(data.get("status", "missing")),
        error=str(data.get("error", "")),
    )


def _modifiers_from_dict(value: Any) -> BloonModifiers:
    data = _as_dict(value)
    return BloonModifiers(
        speed=_as_float(data.get("speed")),
        moab_speed=_as_float(data.get("moab_speed")),
        boss_speed=_as_float(data.get("boss_speed")),
        regrow_rate=_as_float(data.get("regrow_rate")),
        bloon_health=_as_float(data.get("bloon_health")),
        moab_health=_as_float(data.get("moab_health")),
        boss_health=_as_float(data.get("boss_health")),
        all_camo=bool(data.get("all_camo", False)),
        all_regen=bool(data.get("all_regen", False)),
        unknown_fields=_as_dict(data.get("unknown_fields")),
    )


def _tower_from_dict(value: dict[str, Any]) -> TowerRule:
    raw_tiers = value.get("max_tiers", (5, 5, 5))
    tiers = tuple(_as_int(item) or 0 for item in raw_tiers) if isinstance(raw_tiers, (list, tuple)) else (5, 5, 5)
    normalized_tiers = tuple((list(tiers) + [5, 5, 5])[:3])
    return TowerRule(
        tower_id=str(value.get("tower_id", "")),
        name=str(value.get("name", "")),
        category=str(value.get("category", "unknown")),
        is_hero=bool(value.get("is_hero", False)),
        is_available=bool(value.get("is_available", False)),
        max_count=_as_int(value.get("max_count")),
        max_tiers=normalized_tiers,  # type: ignore[arg-type]
        unknown_fields=_as_dict(value.get("unknown_fields")),
    )


def _challenge_from_dict(value: dict[str, Any]) -> ChallengeConfig:
    return ChallengeConfig(
        label=str(value.get("label", "")),
        map_id=str(value.get("map_id", "")),
        map_name=str(value.get("map_name", "")),
        map_asset=_asset_from_dict(value.get("map_asset")),
        difficulty_id=str(value.get("difficulty_id", "")),
        difficulty_name=str(value.get("difficulty_name", "")),
        mode_id=str(value.get("mode_id", "")),
        mode_name=str(value.get("mode_name", "")),
        start_round=_as_int(value.get("start_round")),
        end_round=_as_int(value.get("end_round")),
        starting_cash=_as_int(value.get("starting_cash")),
        lives=_as_int(value.get("lives")),
        max_lives=_as_int(value.get("max_lives")),
        max_towers=_as_int(value.get("max_towers")),
        max_paragons=_as_int(value.get("max_paragons")),
        disable_double_cash=bool(value.get("disable_double_cash", False)),
        disable_instas=bool(value.get("disable_instas", False)),
        disable_monkey_knowledge=bool(value.get("disable_monkey_knowledge", False)),
        disable_powers=bool(value.get("disable_powers", False)),
        disable_selling=bool(value.get("disable_selling", False)),
        no_continues=bool(value.get("no_continues", False)),
        ability_cooldown_multiplier=_as_float(value.get("ability_cooldown_multiplier")),
        removable_cost_multiplier=_as_float(value.get("removable_cost_multiplier")),
        bloon_modifiers=_modifiers_from_dict(value.get("bloon_modifiers")),
        tower_rules=tuple(
            _tower_from_dict(item)
            for item in _dict_list(value.get("tower_rules"))
        ),
        unknown_fields=_as_dict(value.get("unknown_fields")),
    )


def _inventory_from_dict(value: dict[str, Any]) -> InventoryItem:
    return InventoryItem(
        item_id=str(value.get("item_id", "")),
        name=str(value.get("name", "")),
        quantity=_as_int(value.get("quantity")),
        category=str(value.get("category", "")),
        is_hero=bool(value.get("is_hero", False)),
        unknown_fields=_as_dict(value.get("unknown_fields")),
    )


def _power_from_dict(value: dict[str, Any]) -> PowerRule:
    return PowerRule(
        power_id=str(value.get("power_id", "")),
        name=str(value.get("name", "")),
        is_available=bool(value.get("is_available", False)),
        max_count=_as_int(value.get("max_count")),
        unknown_fields=_as_dict(value.get("unknown_fields")),
    )


def _odyssey_from_dict(value: dict[str, Any]) -> OdysseyConfig:
    return OdysseyConfig(
        difficulty=str(value.get("difficulty", "hard")),
        difficulty_name=str(value.get("difficulty_name", "")),
        is_extreme=bool(value.get("is_extreme", False)),
        max_hero_seats=_as_int(value.get("max_hero_seats")),
        max_monkeys_on_boat=_as_int(value.get("max_monkeys_on_boat")),
        max_power_slots=_as_int(value.get("max_power_slots")),
        starting_health=_as_int(value.get("starting_health")),
        rewards=tuple(_inventory_from_dict(item) for item in _dict_list(value.get("rewards"))),
        default_towers=tuple(_inventory_from_dict(item) for item in _dict_list(value.get("default_towers"))),
        available_towers=tuple(_tower_from_dict(item) for item in _dict_list(value.get("available_towers"))),
        default_powers=tuple(_inventory_from_dict(item) for item in _dict_list(value.get("default_powers"))),
        available_powers=tuple(_power_from_dict(item) for item in _dict_list(value.get("available_powers"))),
        maps=tuple(_challenge_from_dict(item) for item in _dict_list(value.get("maps"))),
        unknown_fields=_as_dict(value.get("unknown_fields")),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_float(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 1.0
