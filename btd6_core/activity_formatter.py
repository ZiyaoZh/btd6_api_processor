from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import os
from typing import Iterable

from btd6_core.activity_models import (
    ActivitySnapshot,
    ChallengeConfig,
    InventoryItem,
    PowerRule,
    TowerRule,
)
ACTIVITY_LABELS = {
    "race": "竞速 Race",
    "boss": "Boss",
    "odyssey": "征程 Odyssey",
    "daily": "每日挑战 Daily",
}
CATEGORY_LABELS = {
    "hero": "英雄",
    "primary": "初级",
    "military": "军事",
    "magic": "魔法",
    "support": "支持",
    "unknown": "未分类",
}


def format_activity_snapshot(snapshot: ActivitySnapshot) -> str:
    lines = [
        f"# BTD6 {ACTIVITY_LABELS.get(snapshot.activity_type, snapshot.activity_type)}活动详情",
        "",
        f"- 名称: {snapshot.name}",
        f"- ID: {snapshot.event_id}",
        f"- 状态: {_status_label(snapshot.status)}",
        f"- 数据可用性: {_availability_label(snapshot.availability)}",
    ]
    if snapshot.source_checked_at:
        lines.append(f"- 来源检查时间: {snapshot.source_checked_at}")
    if snapshot.stale_reason:
        lines.append(f"- 陈旧缓存原因: {snapshot.stale_reason}")
    if snapshot.start_at is not None or snapshot.end_at is not None:
        lines.append(
            f"- 时间 (UTC{activity_timezone_label()}): "
            f"{format_activity_time(snapshot.start_at)} ~ {format_activity_time(snapshot.end_at)}"
        )
    if snapshot.activity_type == "daily":
        lines.append(
            f"- 发布时间 (UTC{activity_timezone_label()}): "
            f"{format_activity_time(snapshot.attributes.get('created_at'))}"
        )
    if snapshot.description:
        lines.append(f"- 描述: {snapshot.description}")
    if snapshot.activity_type == "boss":
        boss_name = str(snapshot.attributes.get("boss_type_name", "") or "未知")
        lines.append(f"- Boss 类型: {boss_name}")
        lines.append(
            f"- 标准计分: {_scoring_label(snapshot.attributes.get('normal_scoring_type'))}"
        )
        lines.append(
            f"- 精英计分: {_scoring_label(snapshot.attributes.get('elite_scoring_type'))}"
        )
    for label, count in snapshot.score_counts.items():
        count_label = {"total": "参与成绩数", "standard": "标准提交数", "elite": "精英提交数"}.get(label, label)
        lines.append(f"- {count_label}: {count if count is not None else '未知'}")

    if snapshot.activity_type == "odyssey" and snapshot.odyssey is not None:
        lines.extend(_format_odyssey(snapshot))
    else:
        for challenge in snapshot.challenges:
            heading = "挑战配置" if len(snapshot.challenges) == 1 else f"{_challenge_label(challenge.label)}配置"
            lines.extend(["", f"## {heading}", ""])
            lines.extend(_format_challenge(challenge, include_towers=True))

    lines.extend(["", "---", "数据来源: Ninja Kiwi Open Data API", f"快照时间: {snapshot.fetched_at}"])
    return "\n".join(lines)


def _format_odyssey(snapshot: ActivitySnapshot) -> list[str]:
    odyssey = snapshot.odyssey
    if odyssey is None:
        return []
    lines = [
        "",
        f"## {odyssey.difficulty_name}配置",
        "",
        f"- 极限模式: {'是' if odyssey.is_extreme else '否'}",
        f"- 最大英雄位: {_display_value(odyssey.max_hero_seats)}",
        f"- 船上最大猴数: {_display_value(odyssey.max_monkeys_on_boat)}",
        f"- 最大力量槽: {_display_value(odyssey.max_power_slots)}",
        f"- 初始生命: {_display_value(odyssey.starting_health)}",
    ]
    if odyssey.rewards:
        lines.append(f"- 奖励: {_format_inventory(odyssey.rewards)}")

    lines.extend(["", "## 船员与力量", ""])
    lines.append(f"- 默认船员: {_format_inventory(odyssey.default_towers) or '无'}")
    lines.extend(_format_tower_groups(odyssey.available_towers, available_only=True, prefix="- 可用"))
    lines.append(f"- 默认力量: {_format_inventory(odyssey.default_powers) or '无'}")
    available_powers = [item for item in odyssey.available_powers if item.is_available]
    lines.append(f"- 可用力量: {_format_power_rules(available_powers) or '无'}")

    lines.extend(["", "## 地图列表", ""])
    for index, challenge in enumerate(odyssey.maps, start=1):
        lines.append(f"### 第 {index} 岛: {challenge.map_name} ({challenge.map_id})")
        lines.extend(_format_challenge(challenge, include_towers=False))
        lines.append("")
    if not odyssey.maps:
        lines.append("暂无地图数据")
    return lines


def _format_challenge(challenge: ChallengeConfig, *, include_towers: bool) -> list[str]:
    lines = [
        f"- 地图: {challenge.map_name} ({challenge.map_id or '未知'})",
        f"- 地图缩略图: {challenge.map_asset.source_url or '无'}",
        f"- 难度: {challenge.difficulty_name or challenge.difficulty_id or '未知'}",
        f"- 模式: {challenge.mode_name or challenge.mode_id or '未知'}",
        f"- 回合: {_display_value(challenge.start_round)} - {_display_value(challenge.end_round)}",
        f"- 初始资金: {_display_value(challenge.starting_cash)}",
        f"- 生命: {_display_value(challenge.lives)} / 最大生命: {_display_value(challenge.max_lives)}",
        f"- 最大塔数: {challenge_limit_label(challenge, 'max_towers')}",
        f"- 模范上限: {challenge_limit_label(challenge, 'max_paragons')}",
    ]
    rule_labels = _challenge_rule_labels(challenge)
    if rule_labels:
        lines.append(f"- 特殊规则: {'、'.join(rule_labels)}")
    modifier_labels = challenge_modifier_labels(challenge)
    if modifier_labels:
        lines.append(f"- 气球调整: {'、'.join(modifier_labels)}")
    if include_towers and challenge.tower_rules:
        lines.extend(_format_tower_groups(challenge.tower_rules, available_only=True, prefix="- 可用"))
        banned = [
            item
            for item in challenge.tower_rules
            if not item.is_available
            and not item.is_hero
            and not item.unknown_fields.get("maxMissing")
        ]
        if banned:
            lines.append(f"- 禁用防御塔: {', '.join(item.name for item in banned)}")
    return lines


def _format_tower_groups(
    rules: Iterable[TowerRule],
    *,
    available_only: bool,
    prefix: str,
) -> list[str]:
    groups: dict[str, list[TowerRule]] = defaultdict(list)
    for rule in rules:
        if available_only and not rule.is_available:
            continue
        groups[rule.category].append(rule)
    lines: list[str] = []
    for category in ("hero", "primary", "military", "magic", "support", "unknown"):
        items = groups.get(category, [])
        if not items:
            continue
        rendered = ", ".join(_format_tower_rule(item) for item in items)
        lines.append(f"{prefix}{CATEGORY_LABELS[category]}: {rendered}")
    return lines


def _format_tower_rule(rule: TowerRule) -> str:
    extras: list[str] = []
    if rule.max_count is not None:
        extras.append(f"最多{rule.max_count}")
    if not rule.is_hero and rule.max_tiers != (5, 5, 5):
        extras.append("-".join(str(item) for item in rule.max_tiers))
    return rule.name if not extras else f"{rule.name}（{'，'.join(extras)}）"


def _format_inventory(items: Iterable[InventoryItem]) -> str:
    rendered: list[str] = []
    for item in items:
        rendered.append(item.name if item.quantity is None else f"{item.name} x{item.quantity}")
    return ", ".join(rendered)


def _format_power_rules(items: Iterable[PowerRule]) -> str:
    rendered: list[str] = []
    for item in items:
        rendered.append(item.name if item.max_count is None else f"{item.name}（最多{item.max_count}）")
    return ", ".join(rendered)


def challenge_modifier_labels(challenge: ChallengeConfig) -> list[str]:
    modifiers = challenge.bloon_modifiers
    values = (
        ("气球速度", modifiers.speed),
        ("MOAB速度", modifiers.moab_speed),
        ("BOSS速度", modifiers.boss_speed),
        ("重生速率", modifiers.regrow_rate),
        ("气球生命", modifiers.bloon_health),
        ("MOAB生命", modifiers.moab_health),
        ("BOSS生命", modifiers.boss_health),
    )
    labels = [f"{label} x{_format_multiplier(value)}" for label, value in values if abs(value - 1.0) > 1e-9]
    if modifiers.all_camo:
        labels.append("全迷彩")
    if modifiers.all_regen:
        labels.append("全重生")
    if abs(challenge.ability_cooldown_multiplier - 1.0) > 1e-9:
        labels.append(f"技能冷却 x{_format_multiplier(challenge.ability_cooldown_multiplier)}")
    if abs(challenge.removable_cost_multiplier - 1.0) > 1e-9:
        labels.append(f"障碍移除费用 x{_format_multiplier(challenge.removable_cost_multiplier)}")
    return labels


def _challenge_rule_labels(challenge: ChallengeConfig) -> list[str]:
    values = (
        ("禁用双倍现金", challenge.disable_double_cash),
        ("禁用即时猴", challenge.disable_instas),
        ("禁用猴子知识", challenge.disable_monkey_knowledge),
        ("禁用力量", challenge.disable_powers),
        ("禁用出售", challenge.disable_selling),
        ("禁止继续", challenge.no_continues),
    )
    return [label for label, enabled in values if enabled]


def challenge_limit_label(challenge: ChallengeConfig, field_name: str) -> str:
    value = getattr(challenge, field_name)
    if value is not None:
        return str(value)
    sentinels = challenge.unknown_fields.get("normalizedSentinels", {})
    if not isinstance(sentinels, dict):
        return "未知"
    api_field = {
        "max_towers": "maxTowers",
        "max_paragons": "maxParagons",
    }[field_name]
    raw_value = sentinels.get(api_field)
    if raw_value in {-1, 9999} or (field_name == "max_towers" and raw_value == 0):
        return "无限制"
    if field_name == "max_paragons" and raw_value == 0:
        return "未设置"
    return "未知"


def _display_value(value: int | None) -> str:
    return "未知" if value is None else str(value)


def _format_multiplier(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _challenge_label(value: str) -> str:
    return {"standard": "标准", "elite": "精英"}.get(value, value)


def _status_label(value: str) -> str:
    return {"current": "进行中", "upcoming": "即将开始", "ended": "已结束"}.get(value, "未知")


def _availability_label(value: str) -> str:
    return {
        "fresh": "最新数据",
        "stale": "陈旧缓存",
        "not_published": "官方暂未发布",
        "upstream_error": "上游错误",
    }.get(value, "未知")


def _scoring_label(value: object) -> str:
    return {
        "GameTime": "最短时间",
        "LeastCash": "最少现金",
        "LeastTiers": "最少阶数",
    }.get(str(value or ""), str(value or "未知"))


def format_activity_time(value: object) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        return "未知"
    display_timezone = timezone(timedelta(hours=_display_utc_offset_hours()))
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).astimezone(display_timezone).strftime("%Y-%m-%d %H:%M")


def _display_utc_offset_hours() -> int:
    raw = os.getenv("BTD6_DISPLAY_UTC_OFFSET_HOURS", "8").strip()
    try:
        return max(-12, min(14, int(raw)))
    except ValueError:
        return 8


def activity_timezone_label() -> str:
    offset = _display_utc_offset_hours()
    return f"+{offset}" if offset >= 0 else str(offset)
