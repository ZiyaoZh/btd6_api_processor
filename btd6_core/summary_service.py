from __future__ import annotations

from datetime import datetime
from pathlib import Path

from api_raw_fetcher import ApiClient, fetch_bosses, fetch_daily_challenges, fetch_odyssey, fetch_races
from btd6_core.cache_store import get_cached_content, index_put, load_index, save_cached_file, save_index
from btd6_core.common import challenge_doc_brief, pick_current_or_latest, to_dt, tr, tr_level_label


def build_report(client: ApiClient, trans: dict[str, dict[str, str]]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = ["# BTD6 活动简报", "", f"生成时间: {now}", ""]

    lines.append("## 竞速 Race")
    race_ok = False
    try:
        race = pick_current_or_latest(fetch_races(client))
        if race:
            race_meta: dict[str, object] = {}
            if race.get("metadata"):
                race_meta = client.get(race["metadata"]).get("body", {})
            lines.extend(
                [
                    f"- 名称: {race.get('name', '未知')}",
                    f"- 时间: {to_dt(race.get('start'))} ~ {to_dt(race.get('end'))}",
                    f"- 参与成绩数: {race.get('totalScores', '未知')}",
                    f"- 地图: {tr(race_meta.get('map'), trans.get('map', {}))}",
                    f"- 模式: {tr(race_meta.get('mode'), trans.get('mode', {}))}",
                    f"- 难度: {tr(race_meta.get('difficulty'), trans.get('difficulty', {}))}",
                    f"- 排行榜: {race.get('leaderboard', 'N/A')}",
                ]
            )
        else:
            lines.append("- 暂无数据")
        race_ok = True
    except Exception as exc:  # noqa: BLE001
        lines.append(f"- 获取失败: {exc}")
    lines.append("")

    lines.append("## Boss 活动")
    boss_ok = False
    try:
        boss = pick_current_or_latest(fetch_bosses(client))
        if boss:
            lines.extend(
                [
                    f"- 名称: {boss.get('name', '未知')}",
                    f"- Boss: {tr(boss.get('bossType'), trans.get('boss_bloon', {}))}",
                    f"- 时间: {to_dt(boss.get('start'))} ~ {to_dt(boss.get('end'))}",
                    f"- 标准提交数: {boss.get('totalScores_standard', '未知')}",
                    f"- 精英提交数: {boss.get('totalScores_elite', '未知')}",
                    f"- 标准榜: {boss.get('leaderboard_standard_players_1', 'N/A')}",
                    f"- 精英榜: {boss.get('leaderboard_elite_players_1', 'N/A')}",
                ]
            )
        else:
            lines.append("- 暂无数据")
        boss_ok = True
    except Exception as exc:  # noqa: BLE001
        lines.append(f"- 获取失败: {exc}")
    lines.append("")

    lines.append("## 奥德赛 Odyssey")
    odyssey_ok = False
    try:
        ody = pick_current_or_latest(fetch_odyssey(client))
        if ody:
            lines.extend(
                [
                    f"- 名称: {ody.get('name', '未知')}",
                    f"- 时间: {to_dt(ody.get('start'))} ~ {to_dt(ody.get('end'))}",
                    f"- 描述: {ody.get('description', '无')}",
                    f"- {tr_level_label('easy')}详细信息: {ody.get('metadata_easy', 'N/A')}",
                    f"- {tr_level_label('medium')}详细信息: {ody.get('metadata_medium', 'N/A')}",
                    f"- {tr_level_label('hard')}详细信息: {ody.get('metadata_hard', 'N/A')}",
                ]
            )
        else:
            lines.append("- 暂无数据")
        odyssey_ok = True
    except Exception as exc:  # noqa: BLE001
        lines.append(f"- 获取失败: {exc}")
    lines.append("")

    lines.append("## 每日挑战 Daily")
    daily_ok = False
    try:
        daily_list = fetch_daily_challenges(client)
        daily = daily_list[0] if daily_list else None
        if daily:
            lines.extend(
                [
                    f"- 名称: {daily.get('name', '未知')}",
                    f"- 发布时间: {to_dt(daily.get('createdAt'))}",
                    f"- 详情: {daily.get('metadata', 'N/A')}",
                ]
            )
            detail_url = daily.get("metadata")
            if detail_url:
                daily_doc = client.get(detail_url).get("body", {})
                for item in challenge_doc_brief(daily_doc, trans):
                    lines.append(f"- {item}")
        else:
            lines.append("- 暂无数据")
        daily_ok = True
    except Exception as exc:  # noqa: BLE001
        lines.append(f"- 获取失败: {exc}")
    lines.append("")

    if not any((race_ok, boss_ok, odyssey_ok, daily_ok)):
        raise RuntimeError("全部活动接口获取失败")

    lines.append("---")
    lines.append("数据来源: Ninja Kiwi Open Data API")
    return "\n".join(lines)


def resolve_summary(client: ApiClient, trans: dict[str, dict[str, str]], refresh: bool = False) -> tuple[Path, str, bool]:
    key = "summary:main"
    index_data = load_index()
    if not refresh:
        cached_path, cached_content = get_cached_content(index_data, key)
        if cached_path and cached_content is not None:
            return cached_path, cached_content, True
    stale_path, stale_content = get_cached_content(index_data, key, allow_stale=True)

    try:
        content = build_report(client, trans)
        file_path = Path("output") / "summary" / "latest_summary.md"
        save_cached_file(file_path, content)
        index_put(index_data, key, "latest", file_path)
        save_index(index_data)
        return file_path, content, False
    except Exception as exc:  # noqa: BLE001
        if stale_path and stale_content is not None:
            return stale_path, stale_content, True
        raise RuntimeError(f"summary 刷新失败且无可用缓存: {exc}") from exc
