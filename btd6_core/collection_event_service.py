from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from api_raw_fetcher import ApiClient
from btd6_core.cache_store import OUTPUT_DIR, get_cached_content, get_cached_path, index_put, load_index, resolve_project_path, save_cached_file, save_index

EVENTS_URL = "/btd6/events"
ROTATION_MS = 28_800_000
TOWER_POOL = [
    "Alchemist",
    "BananaFarm",
    "BombShooter",
    "BoomerangMonkey",
    "DartMonkey",
    "Druid",
    "GlueGunner",
    "HeliPilot",
    "IceMonkey",
    "MonkeyAce",
    "MonkeyBuccaneer",
    "MonkeySub",
    "MonkeyVillage",
    "NinjaMonkey",
    "SniperMonkey",
    "SpikeFactory",
    "SuperMonkey",
    "TackShooter",
    "WizardMonkey",
    "MortarMonkey",
    "EngineerMonkey",
    "DartlingGunner",
    "BeastHandler",
    "Mermonkey",
    "Desperado",
]

ICON_NAME_OVERRIDES = {
    "WizardMonkey": "Wizard",
}

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets" / "InstaMonkeyIcon"
FONT_DIR = BASE_DIR / "assets" / "fonts"
FONT_CANDIDATES = [
    FONT_DIR / "LuckiestGuy-Regular.woff2",
    FONT_DIR / "Gardenia-Bold.woff2",
]
DEFAULT_CACHE_JSON_PATH = OUTPUT_DIR / "collection_event" / "latest_collection_event.json"
DEFAULT_CACHE_IMAGE_PATH = OUTPUT_DIR / "collection_event" / "latest_collection_event.png"
CACHE_JSON_KEY_PREFIX = "collection-event:json"
CACHE_IMAGE_KEY_PREFIX = "collection-event:image"


def _js_remainder(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a - math.trunc(a / b) * b


def _to_long(value: int) -> int:
    two64 = 1 << 64
    two63 = 1 << 63
    masked = value & (two64 - 1)
    if masked >= two63:
        masked -= two64
    return masked


def _long_abs(value: int) -> int:
    return value if value >= 0 else -value


def _i64(decimal_digits: str) -> int:
    out = 0
    for ch in decimal_digits:
        digit = ord(ch) - 48
        out = _to_long(_to_long(10 * out) + digit)
    return out


def _get_seed_long(event_id: str) -> int:
    encoded = "".join(str(ord(ch)) for ch in event_id)
    if len(encoded) > 18:
        encoded = encoded[:18]
    return _long_abs(_i64(encoded))


class SeededRandom:
    def __init__(self, seed: int) -> None:
        if seed < 0:
            seed = _long_abs(seed)
        self.seed = seed

    def next(self) -> int:
        self.seed = _to_long(16807 * self.seed)
        self.seed = _js_remainder(self.seed, 2_147_483_647)
        return int(self.seed)

    def range(self, start: int, end: int) -> int:
        if start == end:
            return start
        span = end - start
        return start + _js_remainder(self.next(), span)


def _shuffle_seeded(seed: int, items: list[str]) -> list[str]:
    rng = SeededRandom(seed)
    out = items[:]
    length = len(out)
    for idx in range(length):
        swap_idx = rng.range(idx, length)
        if 0 <= swap_idx < length:
            out[idx], out[swap_idx] = out[swap_idx], out[idx]
    return out


def _get_possible_instas(insta_list: list[str], page: int) -> list[str]:
    if not insta_list:
        return []

    total = len(insta_list)
    quarter = math.ceil(0.25 * total)

    n = page
    s = 0
    while quarter < n:
        n -= quarter
        s += 1

    picks: list[str] = []
    for i in range(4):
        pos = (i + s + 4 * n) % total
        picks.append(insta_list[pos])
    return picks


def fetch_events(client: ApiClient) -> list[dict[str, Any]]:
    body = client.get(EVENTS_URL).get("body", [])
    if not isinstance(body, list):
        raise RuntimeError("Unexpected events response shape: body is not a list")
    return body


def get_latest_collection_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") == "collectableEvent":
            return event
    return None


def process_collection_event(event: dict[str, Any]) -> dict[str, Any]:
    seed = _get_seed_long(str(event["id"]))
    start = int(event["start"])
    end = int(event["end"])

    rotation_count = math.ceil((end - start) / ROTATION_MS)
    shuffled_towers = _shuffle_seeded(seed, TOWER_POOL)

    rotations: dict[str, Any] = {}
    for page in range(rotation_count):
        towers = _get_possible_instas(shuffled_towers, page)
        slot_start = start + page * ROTATION_MS
        slot_end = min(end, slot_start + ROTATION_MS)
        rotations[str(page)] = {
            "index": page,
            "start": slot_start,
            "end": slot_end,
            "towers": towers,
        }

    return {
        "id": event["id"],
        "start": start,
        "end": end,
        "rotations": rotations,
    }


def _ms_to_local(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).astimezone().isoformat()


def _format_local_short(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).astimezone().strftime("%Y/%m/%d\n%H:%M")


def _load_font(size: int) -> Any:
    try:
        from PIL import ImageFont
    except ImportError:
        raise RuntimeError("缺少 Pillow 依赖，请先安装：pip install pillow") from None

    candidates = [
        str(path) for path in FONT_CANDIDATES
    ] + [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if not path:
            continue
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _resolve_tower_icon_path(tower_name: str) -> Path | None:
    base = ICON_NAME_OVERRIDES.get(tower_name, tower_name)
    candidate = ASSETS_DIR / f"000-{base}Insta.webp"
    if candidate.exists():
        return candidate

    fallback = sorted(ASSETS_DIR.glob(f"*-{base}Insta*.webp"))
    if fallback:
        return fallback[0]
    return None


def _cache_variant_suffix(only_upcoming: bool) -> str:
    return "upcoming" if only_upcoming else "full"


def _cache_json_path(only_upcoming: bool) -> Path:
    suffix = _cache_variant_suffix(only_upcoming)
    if suffix == "full":
        return DEFAULT_CACHE_JSON_PATH
    return DEFAULT_CACHE_JSON_PATH.with_name(f"latest_collection_event.{suffix}.json")


def _cache_image_path(only_upcoming: bool) -> Path:
    suffix = _cache_variant_suffix(only_upcoming)
    if suffix == "full":
        return DEFAULT_CACHE_IMAGE_PATH
    return DEFAULT_CACHE_IMAGE_PATH.with_name(f"latest_collection_event.{suffix}.png")


def _cache_keys(only_upcoming: bool) -> tuple[str, str]:
    suffix = _cache_variant_suffix(only_upcoming)
    return f"{CACHE_JSON_KEY_PREFIX}:{suffix}", f"{CACHE_IMAGE_KEY_PREFIX}:{suffix}"


def build_display_rotations(schedule: dict[str, Any], now_ms: int, max_groups: int = 10) -> list[dict[str, Any]]:
    ordered = [schedule["rotations"][key] for key in sorted(schedule["rotations"].keys(), key=lambda value: int(value))]

    current_idx = None
    for idx, slot in enumerate(ordered):
        if slot["start"] <= now_ms < slot["end"]:
            current_idx = idx
            break

    if current_idx is None:
        raise RuntimeError("当前不在收集活动时间范围内")

    selected = ordered[current_idx : current_idx + max_groups]
    enriched: list[dict[str, Any]] = []
    for idx, slot in enumerate(selected):
        enriched.append(
            {
                **slot,
                "is_current": idx == 0,
                "start_local": _ms_to_local(slot["start"]),
                "end_local": _ms_to_local(slot["end"]),
                "time_local": _format_local_short(slot["start"]),
            }
        )
    return enriched


def draw_schedule_image(display_rotations: list[dict[str, Any]], image_output: Path) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise RuntimeError("缺少 Pillow 依赖，请先安装：pip install pillow") from None

    if not display_rotations:
        raise RuntimeError("没有可绘制的轮换数据")

    rows = len(display_rotations)
    icon_size = 112
    icon_gap = 10
    row_h = icon_size + 16
    time_col_w = 255
    time_col_gap = 6
    row_gap = 8
    margin = 12

    width = margin * 2 + time_col_w + time_col_gap + 4 * icon_size + 3 * icon_gap
    height = margin * 2 + rows * row_h + (rows - 1) * row_gap

    img = Image.new("RGB", (width, height), "#0f1724")
    draw = ImageDraw.Draw(img)
    font_time = _load_font(42)

    for idx, slot in enumerate(display_rotations):
        y = margin + idx * (row_h + row_gap)

        row_bg = "#1e2e45" if slot["is_current"] else "#152437"
        row_border = "#7fc6ff" if slot["is_current"] else "#2f4765"
        draw.rounded_rectangle(
            (margin, y, width - margin, y + row_h),
            radius=10,
            fill=row_bg,
            outline=row_border,
            width=2,
        )

        time_bbox = draw.multiline_textbbox((0, 0), slot["time_local"], font=font_time, spacing=2)
        time_w = time_bbox[2] - time_bbox[0]
        time_h = time_bbox[3] - time_bbox[1]
        time_x = margin + (time_col_w - time_w) // 2
        time_y = y + (row_h - time_h) // 2
        draw.multiline_text((time_x, time_y), slot["time_local"], fill="#ecf4ff", font=font_time, spacing=2)

        icon_y = y + 8
        for icon_idx, tower in enumerate(slot["towers"]):
            icon_x = margin + time_col_w + time_col_gap + icon_idx * (icon_size + icon_gap)
            icon_path = _resolve_tower_icon_path(tower)
            if icon_path is not None:
                try:
                    icon = Image.open(icon_path).convert("RGBA")
                    icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    img.paste(icon, (icon_x, icon_y), icon)
                except Exception:
                    draw.rectangle(
                        (icon_x, icon_y, icon_x + icon_size, icon_y + icon_size),
                        fill="#2d405e",
                        outline="#4f6a90",
                        width=2,
                    )
            else:
                draw.rectangle(
                    (icon_x, icon_y, icon_x + icon_size, icon_y + icon_size),
                    fill="#2d405e",
                    outline="#4f6a90",
                    width=2,
                )

    abs_output = resolve_project_path(image_output)
    abs_output.parent.mkdir(parents=True, exist_ok=True)
    img.save(abs_output)


def _cache_collection_event(result: dict[str, Any], json_path: Path, image_path: Path, only_upcoming: bool) -> None:
    json_text = dump_collection_event_output(result)
    save_cached_file(json_path, json_text)
    draw_schedule_image(result["display_rotations"], image_output=image_path)

    index_data = load_index()
    json_key, image_key = _cache_keys(only_upcoming)
    index_put(index_data, json_key, str(result["event"]["id"]), json_path)
    index_put(index_data, image_key, str(result["event"]["id"]), image_path)
    save_index(index_data)


def build_collection_event_output(client: ApiClient, only_upcoming: bool = False) -> dict[str, Any]:
    events = fetch_events(client)
    event = get_latest_collection_event(events)
    if not event:
        raise RuntimeError("No collectableEvent found in /btd6/events response")

    schedule = process_collection_event(event)
    now_ms = int(time.time() * 1000)

    if not (schedule["start"] <= now_ms < schedule["end"]):
        raise RuntimeError("当前不在收集活动时间范围内")

    enriched_rotations: list[dict[str, Any]] = []
    for key in sorted(schedule["rotations"].keys(), key=lambda value: int(value)):
        slot = schedule["rotations"][key]
        if only_upcoming and slot["end"] <= now_ms:
            continue
        enriched_rotations.append(
            {
                **slot,
                "start_local": _ms_to_local(slot["start"]),
                "end_local": _ms_to_local(slot["end"]),
            }
        )

    display_rotations = build_display_rotations(schedule, now_ms=now_ms, max_groups=10)

    return {
        "source": {
            "events_api": EVENTS_URL,
            "selection_logic": "first event with type == collectableEvent",
            "rotation_interval_hours": 8,
        },
        "event": {
            "id": schedule["id"],
            "start": schedule["start"],
            "end": schedule["end"],
            "start_local": _ms_to_local(schedule["start"]),
            "end_local": _ms_to_local(schedule["end"]),
        },
        "generated_at_local": datetime.now().astimezone().isoformat(),
        "rotation_count": len(enriched_rotations),
        "rotations": enriched_rotations,
        "display_rotation_count": len(display_rotations),
        "display_rotations": display_rotations,
    }


def dump_collection_event_output(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


def resolve_collection_event(
    client: ApiClient,
    only_upcoming: bool = False,
    refresh: bool = False,
) -> tuple[Path, str, Path, bool]:
    index_data = load_index()
    json_key, image_key = _cache_keys(only_upcoming)
    json_path = _cache_json_path(only_upcoming)
    image_path = _cache_image_path(only_upcoming)

    if not refresh:
        cached_json_path, cached_json_content = get_cached_content(index_data, json_key)
        cached_image_path = get_cached_path(index_data, image_key)
        if cached_json_path and cached_json_content is not None and cached_image_path:
            return cached_json_path, cached_json_content, cached_image_path, True

    result = build_collection_event_output(client, only_upcoming=only_upcoming)
    _cache_collection_event(result, json_path, image_path, only_upcoming=only_upcoming)
    return json_path, dump_collection_event_output(result), image_path, False


def refresh_collection_event_cache(client: ApiClient, only_upcoming: bool = False) -> tuple[Path, str, Path]:
    result = build_collection_event_output(client, only_upcoming=only_upcoming)
    json_path = _cache_json_path(only_upcoming)
    image_path = _cache_image_path(only_upcoming)
    _cache_collection_event(result, json_path, image_path, only_upcoming=only_upcoming)
    return json_path, dump_collection_event_output(result), image_path
