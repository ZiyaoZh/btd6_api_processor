from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from api_raw_fetcher import ApiClient
from btd6_core.activity_formatter import format_activity_snapshot
from btd6_core.activity_models import ActivitySnapshot
from btd6_core.activity_renderer import (
    ACTIVITY_BRIEF_RENDER_VERSION,
    ACTIVITY_OVERVIEW_RENDER_VERSION,
    render_activity_brief,
    render_activity_overview,
)
from btd6_core.activity_repository import (
    ActivityAvailabilityError,
    EVENT_SCOPES,
    activity_cache_ttl_seconds,
    resolve_activity_snapshot,
)
from btd6_core.cache_store import (
    OUTPUT_DIR,
    get_cached_path,
    index_put,
    load_index,
    save_cached_file,
    save_index,
)
from btd6_core.common import sanitize_id

SUPPORTED_BRIEF_TYPES = {"race", "boss", "odyssey", "daily"}
OVERVIEW_ACTIVITY_TYPES = ("race", "boss", "odyssey", "daily")
OVERVIEW_ACTIVITY_LABELS = {
    "race": "竞速",
    "boss": "Boss",
    "odyssey": "征程",
    "daily": "每日挑战",
}


def resolve_activity_brief(
    client: ApiClient,
    translations: dict[str, dict[str, str]],
    activity_type: str,
    *,
    difficulty: str = "hard",
    event_scope: str = "current",
    refresh: bool = False,
) -> tuple[Path, Path, str, bool]:
    normalized_type = str(activity_type or "").strip().lower()
    if normalized_type not in SUPPORTED_BRIEF_TYPES:
        raise ValueError("活动情报图仅支持 race、boss、odyssey、daily")

    snapshot_path, snapshot, snapshot_cached = resolve_activity_snapshot(
        client,
        translations,
        normalized_type,
        difficulty=difficulty,
        event_scope=event_scope,
        refresh=refresh,
    )
    variant = difficulty if normalized_type == "odyssey" else "default"
    image_key = (
        f"activity-brief:{ACTIVITY_BRIEF_RENDER_VERSION}:"
        f"{normalized_type}:{variant}:{event_scope}"
    )
    image_path = (
        OUTPUT_DIR
        / "briefs"
        / normalized_type
        / f"{sanitize_id(snapshot.event_id)}_{variant}_{event_scope}.png"
    )
    index_data = load_index()
    image_cached = False
    if not refresh and snapshot_cached:
        cached_path = get_cached_path(index_data, image_key)
        image_item = index_data.get("items", {}).get(image_key, {})
        if (
            cached_path is not None
            and isinstance(image_item, dict)
            and image_item.get("id") == snapshot.event_id
        ):
            image_path = cached_path
            image_cached = True

    if not image_cached:
        render_activity_brief(snapshot, image_path)
        index_put(
            index_data,
            image_key,
            snapshot.event_id,
            image_path,
            ttl_seconds=activity_cache_ttl_seconds(snapshot),
        )
        save_index(index_data)

    return (
        snapshot_path,
        image_path,
        format_activity_snapshot(snapshot),
        snapshot_cached and image_cached,
    )


def resolve_activity_overview(
    client: ApiClient,
    translations: dict[str, dict[str, str]],
    *,
    difficulty: str = "hard",
    event_scope: str = "relevant",
    refresh: bool = False,
) -> tuple[Path, Path, str, bool]:
    normalized_difficulty = str(difficulty or "hard").strip().lower()
    normalized_scope = str(event_scope or "relevant").strip().lower()
    if normalized_difficulty not in {"easy", "medium", "hard"}:
        raise ValueError("difficulty 仅支持 easy、medium、hard")
    if normalized_scope not in EVENT_SCOPES:
        raise ValueError(
            "event_scope 仅支持 current、upcoming、ended、relevant、latest"
        )

    snapshots: list[ActivitySnapshot] = []
    snapshot_cache_states: list[bool] = []
    errors: dict[str, str] = {}
    availability: dict[str, dict[str, str]] = {}
    for activity_type in OVERVIEW_ACTIVITY_TYPES:
        try:
            _path, snapshot, cached = resolve_activity_snapshot(
                client,
                translations,
                activity_type,
                difficulty=normalized_difficulty,
                event_scope=normalized_scope,
                refresh=refresh,
            )
            snapshots.append(snapshot)
            snapshot_cache_states.append(cached)
            availability[activity_type] = {
                "state": snapshot.availability,
                "source_checked_at": snapshot.source_checked_at,
                "stale_reason": snapshot.stale_reason,
                "event_id": snapshot.event_id,
                "status": snapshot.status,
            }
        except ActivityAvailabilityError as exc:
            availability[activity_type] = {
                "state": exc.availability,
                "source_checked_at": exc.source_checked_at,
                "stale_reason": exc.stale_reason,
                "error": str(exc)[:320],
            }
            if exc.availability != "not_published":
                errors[activity_type] = str(exc)[:320]
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"[:320]
            errors[activity_type] = error
            availability[activity_type] = {
                "state": "upstream_error",
                "source_checked_at": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
                "stale_reason": error,
                "error": error,
            }

    identity = {
        "difficulty": normalized_difficulty,
        "event_scope": normalized_scope,
        "events": [
            [
                activity_type,
                next(
                    (
                        f"{item.event_id}:{item.status}:{item.availability}"
                        for item in snapshots
                        if item.activity_type == activity_type
                    ),
                    "missing",
                ),
            ]
            for activity_type in OVERVIEW_ACTIVITY_TYPES
        ],
        "availability": availability,
    }
    overview_id = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    manifest = {
        "schema_version": 2,
        "activity_type": "all",
        "overview_id": overview_id,
        "difficulty": normalized_difficulty,
        "event_scope": normalized_scope,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "activities": [item.to_dict() for item in snapshots],
        "partial": any(
            item.get("state") != "fresh" for item in availability.values()
        ),
        "availability": availability,
        "errors": errors,
    }
    manifest_path = (
        OUTPUT_DIR
        / "snapshots"
        / "all"
        / f"{overview_id}_{normalized_difficulty}_{normalized_scope}.json"
    )
    save_cached_file(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )

    image_key = (
        f"activity-overview:{ACTIVITY_OVERVIEW_RENDER_VERSION}:"
        f"{normalized_difficulty}:{normalized_scope}"
    )
    image_path = (
        OUTPUT_DIR
        / "briefs"
        / "all"
        / f"{overview_id}_{normalized_difficulty}_{normalized_scope}.png"
    )
    index_data = load_index()
    all_snapshots_cached = (
        len(snapshot_cache_states) == len(OVERVIEW_ACTIVITY_TYPES)
        and all(snapshot_cache_states)
        and not errors
        and all(
            item.get("state") == "fresh" for item in availability.values()
        )
    )
    image_cached = False
    if not refresh and all_snapshots_cached:
        cached_path = get_cached_path(index_data, image_key)
        image_item = index_data.get("items", {}).get(image_key, {})
        if (
            cached_path is not None
            and isinstance(image_item, dict)
            and image_item.get("id") == overview_id
        ):
            image_path = cached_path
            image_cached = True

    if not image_cached:
        render_errors = {
            activity_type: (
                "not_published"
                if item.get("state") == "not_published"
                else item.get("error", item.get("stale_reason", ""))
            )
            for activity_type, item in availability.items()
            if item.get("state") in {"not_published", "upstream_error"}
        }
        render_activity_overview(
            snapshots,
            image_path,
            errors=render_errors,
            difficulty=normalized_difficulty,
            event_scope=normalized_scope,
        )
        overview_ttl = min(
            (activity_cache_ttl_seconds(item) for item in snapshots),
            default=120,
        )
        index_put(
            index_data,
            image_key,
            overview_id,
            image_path,
            ttl_seconds=overview_ttl,
        )
        save_index(index_data)

    return (
        manifest_path,
        image_path,
        _format_activity_overview(
            snapshots,
            availability,
            normalized_scope,
        ),
        all_snapshots_cached and image_cached,
    )


def _format_activity_overview(
    snapshots: Iterable[ActivitySnapshot],
    availability: dict[str, dict[str, str]],
    event_scope: str,
) -> str:
    snapshot_by_type = {item.activity_type: item for item in snapshots}
    scope_label = {
        "current": "当前",
        "upcoming": "下一期",
        "ended": "最近结束",
        "relevant": "当前相关",
        "latest": "最新发布",
    }.get(event_scope, event_scope)
    lines = [f"# BTD6 {scope_label}活动总览", ""]
    for activity_type in OVERVIEW_ACTIVITY_TYPES:
        label = OVERVIEW_ACTIVITY_LABELS[activity_type]
        snapshot = snapshot_by_type.get(activity_type)
        if snapshot is None:
            state = availability.get(activity_type, {}).get("state", "upstream_error")
            missing_label = (
                "官方暂未发布"
                if state == "not_published"
                else "上游数据暂不可用"
            )
            lines.append(f"- {label}: {missing_label}")
            continue
        map_name = (
            snapshot.challenges[0].map_name
            if snapshot.challenges
            else "地图待公布"
        )
        status_label = {
            "upcoming": "未开始",
            "current": "正在进行",
            "ended": "已结束",
        }.get(snapshot.status, "状态未知")
        stale_label = " | 陈旧缓存" if snapshot.availability == "stale" else ""
        lines.append(
            f"- {label}: [{status_label}] {snapshot.name} | {map_name}{stale_label}"
        )
    unavailable = [
        item
        for item, record in availability.items()
        if record.get("state") != "fresh"
    ]
    if unavailable:
        missing_labels = "、".join(
            OVERVIEW_ACTIVITY_LABELS[item] for item in unavailable
        )
        lines.extend(["", f"非完整数据类型: {missing_labels}"])
    return "\n".join(lines)
