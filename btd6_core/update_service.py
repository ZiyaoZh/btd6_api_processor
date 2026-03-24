from __future__ import annotations

from api_raw_fetcher import ApiClient
from btd6_core.detail_service import resolve_detail
from btd6_core.leaderboard_service import resolve_leaderboard


def update_all_data(client: ApiClient, trans: dict[str, dict[str, str]]) -> str:
    lines = ["# 数据更新结果", ""]

    detail_types = ["race", "boss", "odyssey", "daily"]
    for detail_type in detail_types:
        path, _content, _cached = resolve_detail(client, trans, detail_type, refresh=True)
        lines.append(f"- 已更新详细信息: {detail_type} -> {path}")

    leaderboard_types = ["race", "boss-standard", "boss-elite"]
    for lb_type in leaderboard_types:
        path, _content, _cached = resolve_leaderboard(client, lb_type, page=1, output_format="markdown", refresh=True)
        lines.append(f"- 已更新排行榜: {lb_type} p1 -> {path}")

    lines.extend(["", "默认排行榜页数: 1", "---", "数据来源: Ninja Kiwi Open Data API"])
    return "\n".join(lines)
