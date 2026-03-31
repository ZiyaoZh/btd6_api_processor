from __future__ import annotations

from pathlib import Path
from typing import Any

from api_raw_fetcher import ApiClient, fetch_raw_data
from btd6_core.cache_store import (
    get_cached_content,
    get_cached_path,
    index_put,
    load_index,
    save_cached_file,
    save_index,
)
from btd6_core.common import append_page, format_score_parts, pick_current_or_latest, sanitize_id, to_dt
from btd6_core.image_renderer import render_leaderboard_image


def _format_time_score_ms(value: Any) -> str:
    if not isinstance(value, int):
        return str(value)
    if value < 0:
        return str(value)

    hours = value // 3_600_000
    remainder = value % 3_600_000
    minutes = remainder // 60_000
    remainder %= 60_000
    seconds = remainder // 1_000
    millis = remainder % 1_000

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}:{millis:03d}"


def _score_label(scoring_type: str) -> str:
    mapping = {
        "GameTime": "少时",
        "LeastCash": "少金",
        "LeastTiers": "少阶",
    }
    return mapping.get(scoring_type, "得分")


def _format_hhmmss_from_ms(value: Any) -> str:
    if not isinstance(value, int):
        return str(value)
    if value < 0:
        return str(value)

    total_seconds = value // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _build_boss_score_from_parts(item: dict[str, Any]) -> str:
    parts = item.get("scoreParts", [])
    tier: int | None = None
    cash: int | None = None
    game_time_ms: int | None = None

    for part in parts:
        name = str(part.get("name", ""))
        score = part.get("score")
        if not isinstance(score, int):
            continue
        if name == "Boss Tier":
            tier = score
        elif name == "Least Cash":
            cash = score
        elif name == "Game Time":
            game_time_ms = score

    segs: list[str] = []
    if tier is not None:
        segs.append(f"{tier}阶")
    if cash is not None:
        segs.append(f"${cash}")
    if game_time_ms is not None:
        segs.append(_format_hhmmss_from_ms(game_time_ms))

    if segs:
        return "，".join(segs)
    return str(item.get("score", "?"))


def _normalize_scoring_type(value: Any) -> str:
    if value in {"GameTime", "LeastCash", "LeastTiers"}:
        return str(value)
    return "GameTime"


def _format_score_value(score: Any, scoring_type: str) -> str:
    if scoring_type == "GameTime":
        return _format_time_score_ms(score)
    return str(score)


def build_single_leaderboard_table_data(leaderboard_type: str, page: int, raw: dict[str, Any]) -> dict[str, Any]:
    if page < 1:
        raise ValueError("page 必须 >= 1")

    title = ""
    board_url = ""
    event_name = ""
    event_time = ""
    event_id = "unknown"
    folder = ""
    suffix = ""

    if leaderboard_type == "race":
        race = pick_current_or_latest(raw.get("races", []))
        if not race:
            raise RuntimeError("竞速数据为空")
        title = "竞速排行榜"
        board_url = race.get("leaderboard", "")
        event_name = race.get("name", "未知")
        event_time = f"{to_dt(race.get('start'))} ~ {to_dt(race.get('end'))}"
        event_id = sanitize_id(race.get("id"))
        folder = "race"
        suffix = "top100"
        scoring_type = "GameTime"
        score_label = "得分"
        is_boss = False
        total_submissions = race.get("totalScores")
    elif leaderboard_type == "boss-standard":
        boss = pick_current_or_latest(raw.get("bosses", []))
        if not boss:
            raise RuntimeError("Boss 数据为空")
        title = "Boss标准单人排行榜"
        board_url = boss.get("leaderboard_standard_players_1", "")
        event_name = boss.get("name", "未知")
        event_time = f"{to_dt(boss.get('start'))} ~ {to_dt(boss.get('end'))}"
        event_id = sanitize_id(boss.get("id"))
        folder = "boss"
        suffix = "standard_top150"
        scoring_type = _normalize_scoring_type(boss.get("normalScoringType") or boss.get("scoringType"))
        score_label = "得分"
        is_boss = True
        total_submissions = boss.get("totalScores_standard")
    elif leaderboard_type == "boss-elite":
        boss = pick_current_or_latest(raw.get("bosses", []))
        if not boss:
            raise RuntimeError("Boss 数据为空")
        title = "Boss精英单人排行榜"
        board_url = boss.get("leaderboard_elite_players_1", "")
        event_name = boss.get("name", "未知")
        event_time = f"{to_dt(boss.get('start'))} ~ {to_dt(boss.get('end'))}"
        event_id = sanitize_id(boss.get("id"))
        folder = "boss"
        suffix = "elite_top150"
        scoring_type = _normalize_scoring_type(boss.get("eliteScoringType") or boss.get("scoringType"))
        score_label = "得分"
        is_boss = True
        total_submissions = boss.get("totalScores_elite")
    else:
        raise ValueError(f"不支持的排行榜类型: {leaderboard_type}")

    if not board_url:
        raise RuntimeError("排行榜地址为空")

    return {
        "title": title,
        "board_url": board_url,
        "event_name": event_name,
        "event_time": event_time,
        "event_id": event_id,
        "folder": folder,
        "suffix": suffix,
        "page": page,
        "scoring_type": scoring_type,
        "score_label": score_label,
        "is_boss": is_boss,
        "total_submissions": total_submissions,
    }


def render_markdown_report(table_data: dict[str, Any], payload: dict[str, Any]) -> str:
    page = int(table_data["page"])
    entries = payload.get("body", [])
    max_pages = payload.get("maxPages", "?")
    next_url = payload.get("next")
    prev_url = payload.get("prev")

    lines = [
        f"# {table_data['title']}",
        "",
        f"活动: {table_data['event_name']}",
        f"ID: {table_data['event_id']}",
        f"时间: {table_data['event_time']}",
        f"页码: {page}/{max_pages}",
        "",
    ]

    if not entries:
        lines.append("当前页无数据")
    else:
        rank_base = (page - 1) * 50
        for idx, item in enumerate(entries, start=1):
            rank = rank_base + idx
            if table_data.get("is_boss"):
                score_show = _build_boss_score_from_parts(item)
                lines.append(f"{rank}. {item.get('displayName', 'Unknown')} | 得分: {score_show}")
            else:
                score_show = _format_score_value(item.get("score", "?"), table_data.get("scoring_type", "GameTime"))
                lines.append(
                    f"{rank}. {item.get('displayName', 'Unknown')} | {table_data.get('score_label', '得分')}: {score_show} | 细分: {format_score_parts(item)}"
                )

    lines.extend(["", f"上一页: {prev_url or '无'}", f"下一页: {next_url or '无'}", "---", "数据来源: Ninja Kiwi Open Data API"])
    return "\n".join(lines)


def _is_no_scores_error(exc: Exception) -> bool:
    msg = str(exc)
    return "No Scores Available" in msg


def _render_no_scores_markdown(table_data: dict[str, Any], page: int) -> str:
    lines = [
        f"# {table_data['title']}",
        "",
        f"活动: {table_data['event_name']}",
        f"ID: {table_data['event_id']}",
        f"时间: {table_data['event_time']}",
        f"页码: {page}/1",
        "",
        "排行榜暂无可用成绩（活动可能尚未开始）。",
        "",
        "上一页: 无",
        "下一页: 无",
        "---",
        "数据来源: Ninja Kiwi Open Data API",
    ]
    return "\n".join(lines)


def resolve_leaderboard(
    client: ApiClient,
    leaderboard_type: str,
    page: int,
    output_format: str = "markdown",
    refresh: bool = False,
) -> tuple[Path, str, bool]:
    # 入口不再分页：统一锁定第一页作为起点，图片按活动类型拉取固定人数。
    page = 1
    format_key = output_format if output_format == "markdown" else "image-fixed"
    key = f"leaderboard:{leaderboard_type}:{format_key}"
    index_data = load_index()
    if not refresh:
        if output_format == "markdown":
            cached_path, cached_content = get_cached_content(index_data, key)
            if cached_path and cached_content is not None:
                return cached_path, cached_content, True
            raise RuntimeError(f"未找到 {leaderboard_type} markdown 缓存，请先运行 refresh-service 刷新数据")
        else:
            cached_path = get_cached_path(index_data, key)
            if cached_path:
                return cached_path, "", True
            raise RuntimeError(f"未找到 {leaderboard_type} image 缓存，请先运行 refresh-service 刷新数据")

    raw = fetch_raw_data(client)
    table_data = build_single_leaderboard_table_data(leaderboard_type, page, raw)
    if output_format == "markdown":
        try:
            payload = client.get(append_page(table_data["board_url"], page))
            content = render_markdown_report(table_data, payload)
        except RuntimeError as exc:
            if not _is_no_scores_error(exc):
                raise
            content = _render_no_scores_markdown(table_data, page)
        file_path = Path(table_data["folder"]) / f"{table_data['event_id']}_{table_data['suffix']}.md"
        save_cached_file(file_path, content)
    elif output_format == "image":
        entries: list[dict[str, Any]] = []
        image_total_pages = 1
        try:
            if table_data.get("is_boss"):
                # Boss 每页 25 条，固定尝试拉取前 6 页，最多 150 人。
                payload_1 = client.get(append_page(table_data["board_url"], 1))
                api_max_pages = int(payload_1.get("maxPages", 1) or 1)
                entries = list(payload_1.get("body", []))
                for p in range(2, min(api_max_pages, 6) + 1):
                    payload_p = client.get(append_page(table_data["board_url"], p))
                    entries.extend(list(payload_p.get("body", [])))
                entries = entries[:150]
                image_total_pages = 1
            else:
                # 竞速固定前 100 人：第一页和第二页。
                payload_1 = client.get(append_page(table_data["board_url"], 1))
                payload_2 = client.get(append_page(table_data["board_url"], 2))
                entries = list(payload_1.get("body", [])) + list(payload_2.get("body", []))
                entries = entries[:100]
                image_total_pages = 1
        except RuntimeError as exc:
            if not _is_no_scores_error(exc):
                raise
            table_data["total_submissions"] = 0

        rendered_entries = [
            {
                "displayName": item.get("displayName", "Unknown"),
                "displayScore": _build_boss_score_from_parts(item)
                if table_data.get("is_boss")
                else _format_score_value(item.get("score", "?"), table_data.get("scoring_type", "GameTime")),
            }
            for item in entries
        ]
        file_path = Path(table_data["folder"]) / f"{table_data['event_id']}_{table_data['suffix']}.png"
        render_leaderboard_image(table_data, rendered_entries, image_total_pages, file_path)
        content = ""
    else:
        raise ValueError(f"不支持的排行榜输出格式: {output_format}")

    index_put(index_data, key, table_data["event_id"], file_path)
    save_index(index_data)
    return file_path, content, False
