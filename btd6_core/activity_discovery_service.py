from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from api_raw_fetcher import (
    ApiClient,
    fetch_bosses,
    fetch_daily_challenges,
    fetch_odyssey,
    fetch_races,
)
from btd6_core.activity_repository import (
    ActivityNotPublishedError,
    ActivityRepository,
    cache_activity_snapshot,
    classify_event,
    select_event,
)
from btd6_core.cache_store import OUTPUT_DIR, load_index, save_cached_file, save_index


DISCOVERY_PATH = OUTPUT_DIR / "activity_discovery.json"
DISCOVERY_TYPES = ("race", "boss", "odyssey", "daily")


def discover_activities(
    client: ApiClient,
    translations: dict[str, dict[str, str]],
    *,
    now_ms: int | None = None,
) -> tuple[Path, dict[str, Any]]:
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    previous = _load_discovery(DISCOVERY_PATH)
    previous_types = previous.get("types", {})
    if not isinstance(previous_types, dict):
        previous_types = {}

    fetchers: dict[str, Callable[[ApiClient], list[dict[str, Any]]]] = {
        "race": fetch_races,
        "boss": fetch_bosses,
        "odyssey": fetch_odyssey,
        "daily": fetch_daily_challenges,
    }
    event_lists: dict[str, list[dict[str, Any]]] = {}
    type_records: dict[str, dict[str, Any]] = {}
    changed_types: list[str] = []

    for activity_type in DISCOVERY_TYPES:
        try:
            events = fetchers[activity_type](client)
            event_lists[activity_type] = events
            record = _timeline_record(events, current_ms)
            record["availability"] = "fresh"
            type_records[activity_type] = record
            previous_record = previous_types.get(activity_type)
            if not isinstance(previous_record, dict) or _timeline_identity(
                previous_record
            ) != _timeline_identity(record):
                changed_types.append(activity_type)
        except Exception as exc:  # noqa: BLE001
            previous_record = previous_types.get(activity_type)
            preserved = dict(previous_record) if isinstance(previous_record, dict) else {}
            preserved.update(
                {
                    "availability": "upstream_error",
                    "error": f"{type(exc).__name__}: {exc}"[:320],
                }
            )
            type_records[activity_type] = preserved

    index_data = load_index()
    invalidated_keys = _invalidate_changed_cache(index_data, changed_types)
    metadata: dict[str, dict[str, str]] = {}
    for activity_type in changed_types:
        try:
            snapshot = ActivityRepository(
                client,
                translations,
                now_ms=current_ms,
            ).fetch_snapshot_from_events(
                activity_type,
                event_lists[activity_type],
                difficulty="hard",
                event_scope="relevant",
            )
            cache_activity_snapshot(
                snapshot,
                difficulty="hard",
                event_scope="relevant",
                index_data=index_data,
                save=False,
            )
            metadata[activity_type] = {
                "availability": "fresh",
                "event_id": snapshot.event_id,
                "status": snapshot.status,
            }
        except ActivityNotPublishedError as exc:
            metadata[activity_type] = {
                "availability": "not_published",
                "error": str(exc)[:320],
            }
        except Exception as exc:  # noqa: BLE001
            metadata[activity_type] = {
                "availability": "upstream_error",
                "error": f"{type(exc).__name__}: {exc}"[:320],
            }
    if changed_types:
        save_index(index_data)

    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    manifest = {
        "schema_version": 1,
        "checked_at": checked_at,
        "changed_types": changed_types,
        "invalidated_cache_keys": invalidated_keys,
        "types": type_records,
        "metadata": metadata,
        "partial": any(
            item.get("availability") != "fresh" for item in type_records.values()
        )
        or any(item.get("availability") != "fresh" for item in metadata.values()),
    }
    save_cached_file(
        DISCOVERY_PATH,
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )
    return DISCOVERY_PATH, manifest


def _timeline_record(events: list[dict[str, Any]], now_ms: int) -> dict[str, Any]:
    slots: dict[str, dict[str, Any] | None] = {}
    for scope in ("upcoming", "current", "ended", "relevant"):
        event = select_event(events, scope, now_ms=now_ms)
        slots[scope] = _event_record(event, now_ms) if event is not None else None
    return {"event_count": len(events), "slots": slots}


def _event_record(event: dict[str, Any], now_ms: int) -> dict[str, Any]:
    start_at = _as_int(event.get("start"))
    if start_at is None:
        start_at = _as_int(event.get("createdAt"))
    end_at = _as_int(event.get("end"))
    return {
        "event_id": str(event.get("id", "") or ""),
        "start_at": start_at,
        "end_at": end_at,
        "status": classify_event(start_at, end_at, now_ms=now_ms),
    }


def _timeline_identity(record: dict[str, Any]) -> Any:
    return record.get("slots")


def _invalidate_changed_cache(
    index_data: dict[str, Any],
    changed_types: list[str],
) -> list[str]:
    items = index_data.get("items", {})
    if not isinstance(items, dict) or not changed_types:
        return []
    invalidated: list[str] = []
    for key in list(items):
        is_overview = key.startswith("activity-overview:")
        is_changed_snapshot = any(
            key.startswith(f"activity-snapshot:{activity_type}:")
            for activity_type in changed_types
        )
        is_changed_brief = key.startswith("activity-brief:") and any(
            f":{activity_type}:" in key for activity_type in changed_types
        )
        if is_changed_snapshot:
            item = items.get(key)
            if isinstance(item, dict):
                item_ttl = item.get("ttlSeconds")
                ttl_seconds = (
                    item_ttl
                    if isinstance(item_ttl, int) and item_ttl > 0
                    else 600
                )
                item["updatedAtEpoch"] = int(time.time()) - ttl_seconds
            invalidated.append(key)
        elif is_overview or is_changed_brief:
            items.pop(key, None)
            invalidated.append(key)
    return sorted(invalidated)


def _load_discovery(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
