from __future__ import annotations

from pathlib import Path

from api_raw_fetcher import ApiClient
from btd6_core.activity_formatter import format_activity_snapshot
from btd6_core.activity_renderer import (
    ACTIVITY_BRIEF_RENDER_VERSION,
    render_activity_brief,
)
from btd6_core.activity_repository import resolve_activity_snapshot
from btd6_core.cache_store import (
    OUTPUT_DIR,
    get_cached_path,
    index_put,
    load_index,
    save_index,
)
from btd6_core.common import sanitize_id


SUPPORTED_BRIEF_TYPES = {"race", "boss", "odyssey", "daily"}


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
        index_put(index_data, image_key, snapshot.event_id, image_path)
        save_index(index_data)

    return (
        snapshot_path,
        image_path,
        format_activity_snapshot(snapshot),
        snapshot_cached and image_cached,
    )
