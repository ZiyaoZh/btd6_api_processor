from __future__ import annotations

from api_raw_fetcher import ApiClient
from btd6_core.collection_event_service import resolve_collection_event
from btd6_core.detail_service import resolve_detail
from btd6_core.leaderboard_service import resolve_leaderboard
from btd6_core.summary_service import resolve_summary


def update_all_data(client: ApiClient, trans: dict[str, dict[str, str]]) -> str:
    lines = ["# 数据更新结果", ""]

    summary_path, _summary_content, _summary_cached = resolve_summary(client, trans, refresh=True)
    lines.append(f"- 已更新简报缓存: summary -> {summary_path}")

    detail_types = ["race", "boss", "odyssey", "daily"]
    for detail_type in detail_types:
        path, _content, _cached = resolve_detail(client, trans, detail_type, refresh=True)
        lines.append(f"- 已更新详细信息: {detail_type} -> {path}")

    leaderboard_types = ["race", "boss-standard", "boss-elite"]
    for lb_type in leaderboard_types:
        md_path, _content, _cached = resolve_leaderboard(client, lb_type, page=1, output_format="markdown", refresh=True)
        lines.append(f"- 已更新排行榜: {lb_type} p1 -> {md_path}")
        image_path, _content, _cached = resolve_leaderboard(client, lb_type, page=1, output_format="image", refresh=True)
        lines.append(f"- 已更新排行榜图片: {lb_type} -> {image_path}")

    collection_json_path, _content, collection_image_path, _cached = resolve_collection_event(client, only_upcoming=False, refresh=True)
    lines.append(f"- 已更新收集活动缓存: full -> {collection_json_path} | {collection_image_path}")

    upcoming_json_path, _content, upcoming_image_path, _cached = resolve_collection_event(client, only_upcoming=True, refresh=True)
    lines.append(f"- 已更新收集活动缓存: upcoming -> {upcoming_json_path} | {upcoming_image_path}")

    lines.extend(["", "默认排行榜页数: 1", "---", "数据来源: Ninja Kiwi Open Data API"])
    return "\n".join(lines)
