from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from api_raw_fetcher import ApiClient, fetch_raw_data
from btd6_core.cache_store import get_cached_content, index_put, load_index, save_cached_file, save_index
from btd6_core.common import (
    challenge_doc_detail,
    pick_current_or_latest,
    sanitize_id,
    scoring_type_to_label,
    to_dt,
    tr,
    tr_level_label,
    tr_reward_item,
)


def _normalize_scoring_type(value: Any) -> str:
    if value in {"GameTime", "LeastCash", "LeastTiers"}:
        return str(value)
    return "GameTime"


def get_latest_event(raw: dict[str, Any], detail_type: str) -> dict[str, Any] | None:
    mapping = {
        "race": "races",
        "boss": "bosses",
        "odyssey": "odyssey",
        "daily": "daily",
    }
    key = mapping.get(detail_type)
    if not key:
        return None
    events = raw.get(key, [])
    if detail_type == "daily":
        return events[0] if events else None
    return pick_current_or_latest(events)


def build_single_detail_report(client: ApiClient, trans: dict[str, dict[str, str]], detail_type: str, raw: dict[str, Any]) -> tuple[str, str, str]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event = get_latest_event(raw, detail_type)
    if not event:
        raise RuntimeError(f"{detail_type} 暂无数据")

    event_id = sanitize_id(event.get("id"))
    lines: list[str] = ["# BTD6 最新活动详细信息", "", f"生成时间: {now}", ""]

    if detail_type == "race":
        lines.append("## 竞速 Race")
        lines.extend(
            [
                f"- 名称: {event.get('name', '未知')}",
                f"- ID: {event.get('id', '未知')}",
                f"- 时间: {to_dt(event.get('start'))} ~ {to_dt(event.get('end'))}",
                f"- 参与成绩数: {event.get('totalScores', '未知')}",
                f"- 排行榜: {event.get('leaderboard', 'N/A')}",
            ]
        )
        meta_url = event.get("metadata")
        if meta_url:
            meta = client.get(meta_url).get("body", {})
            lines.append("- 详细信息:")
            for item in challenge_doc_detail(meta, trans):
                lines.append(f"  - {item}")
        folder = "race"
    elif detail_type == "boss":
        standard_scoring_type = _normalize_scoring_type(event.get("normalScoringType") or event.get("scoringType"))
        elite_scoring_type = _normalize_scoring_type(event.get("eliteScoringType") or event.get("scoringType"))
        lines.append("## Boss")
        lines.extend(
            [
                f"- 名称: {event.get('name', '未知')}",
                f"- ID: {event.get('id', '未知')}",
                f"- Boss 类型: {tr(event.get('bossType'), trans.get('boss_bloon', {}))}",
                f"- 时间: {to_dt(event.get('start'))} ~ {to_dt(event.get('end'))}",
                f"- 标准挑战类型: {scoring_type_to_label(standard_scoring_type)}",
                f"- 精英挑战类型: {scoring_type_to_label(elite_scoring_type)}",
                f"- 标准提交数: {event.get('totalScores_standard', '未知')}",
                f"- 精英提交数: {event.get('totalScores_elite', '未知')}",
            ]
        )
        standard_meta_url = event.get("metadataStandard")
        elite_meta_url = event.get("metadataElite")
        if standard_meta_url:
            standard_meta = client.get(standard_meta_url).get("body", {})
            lines.append(f"- {tr_level_label('standard')}详细信息:")
            for item in challenge_doc_detail(standard_meta, trans):
                lines.append(f"  - {item}")
        if elite_meta_url:
            elite_meta = client.get(elite_meta_url).get("body", {})
            lines.append(f"- {tr_level_label('elite')}详细信息:")
            for item in challenge_doc_detail(elite_meta, trans):
                lines.append(f"  - {item}")
        folder = "boss"
    elif detail_type == "odyssey":
        lines.append("## 奥德赛 Odyssey")
        lines.extend(
            [
                f"- 名称: {event.get('name', '未知')}",
                f"- ID: {event.get('id', '未知')}",
                f"- 时间: {to_dt(event.get('start'))} ~ {to_dt(event.get('end'))}",
                f"- 描述: {event.get('description', '无')}",
            ]
        )
        for difficulty, key in (("easy", "metadata_easy"), ("medium", "metadata_medium"), ("hard", "metadata_hard")):
            meta_url = event.get(key)
            if not meta_url:
                continue
            ody_meta = client.get(meta_url).get("body", {})
            lines.append(f"- {tr_level_label(difficulty)}详细信息:")
            lines.append(f"  - 最大英雄位: {ody_meta.get('maxMonkeySeats', '?')}")
            lines.append(f"  - 船上最大猴数: {ody_meta.get('maxMonkeysOnBoat', '?')}")
            lines.append(f"  - 最大道具槽: {ody_meta.get('maxPowerSlots', '?')}")
            lines.append(f"  - 初始血量: {ody_meta.get('startingHealth', '?')}")
            rewards = ody_meta.get("_rewards", [])
            if rewards:
                lines.append(f"  - 奖励: {', '.join(tr_reward_item(str(x), trans) for x in rewards)}")
        folder = "odyssey"
    elif detail_type == "daily":
        lines.append("## 每日挑战 Daily")
        lines.extend(
            [
                f"- 名称: {event.get('name', '未知')}",
                f"- ID: {event.get('id', '未知')}",
                f"- 发布时间: {to_dt(event.get('createdAt'))}",
            ]
        )
        detail_url = event.get("metadata")
        if detail_url:
            daily_doc = client.get(detail_url).get("body", {})
            lines.append("- 详细信息:")
            for item in challenge_doc_detail(daily_doc, trans):
                lines.append(f"  - {item}")
        folder = "daily"
    else:
        raise ValueError(f"不支持的 detail 类型: {detail_type}")

    lines.extend(["", "---", "数据来源: Ninja Kiwi Open Data API"])
    return event_id, folder, "\n".join(lines)


def resolve_detail(client: ApiClient, trans: dict[str, dict[str, str]], detail_type: str, refresh: bool = False) -> tuple[Path, str, bool]:
    key = f"detail:{detail_type}"
    index_data = load_index()
    if not refresh:
        cached_path, cached_content = get_cached_content(index_data, key)
        if cached_path and cached_content is not None:
            return cached_path, cached_content, True

    raw = fetch_raw_data(client)
    event_id, folder, content = build_single_detail_report(client, trans, detail_type, raw)
    file_path = Path(folder) / f"{event_id}_detail.md"
    save_cached_file(file_path, content)
    index_put(index_data, key, event_id, file_path)
    save_index(index_data)
    return file_path, content, False
