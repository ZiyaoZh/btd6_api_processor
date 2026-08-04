from __future__ import annotations

from pathlib import Path

from api_raw_fetcher import ApiClient
from btd6_core.activity_formatter import format_activity_snapshot
from btd6_core.activity_repository import resolve_activity_snapshot
from btd6_core.cache_store import OUTPUT_DIR, save_cached_file
from btd6_core.common import sanitize_id


def resolve_detail(
    client: ApiClient,
    trans: dict[str, dict[str, str]],
    detail_type: str,
    refresh: bool = False,
    *,
    difficulty: str = "hard",
    event_scope: str = "latest",
) -> tuple[Path, str, bool]:
    _, snapshot, cached = resolve_activity_snapshot(
        client,
        trans,
        detail_type,
        difficulty=difficulty,
        event_scope=event_scope,
        refresh=refresh,
    )
    variant = f"_{difficulty}" if detail_type == "odyssey" else ""
    scope_suffix = "" if event_scope == "latest" else f"_{event_scope}"
    file_path = (
        OUTPUT_DIR
        / detail_type
        / f"{sanitize_id(snapshot.event_id)}{variant}{scope_suffix}_detail.md"
    )
    content = format_activity_snapshot(snapshot)
    save_cached_file(file_path, content)
    return file_path, content, cached
