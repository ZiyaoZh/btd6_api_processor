from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def to_dt(ms: int | None) -> str:
    if not isinstance(ms, int):
        return "未知"
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def pick_current_or_latest(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None

    now_ms = int(time.time() * 1000)
    current = [
        e
        for e in events
        if isinstance(e.get("start"), int) and isinstance(e.get("end"), int) and e["start"] <= now_ms <= e["end"]
    ]
    if current:
        current.sort(key=lambda x: x.get("start", 0), reverse=True)
        return current[0]

    def start_distance(e: dict[str, Any]) -> int:
        start = e.get("start")
        if not isinstance(start, int):
            return 10**18
        return abs(start - now_ms)

    return sorted(events, key=start_distance)[0]


def normalize_translation_key(value: str) -> str:
    """将翻译键归一化：移除所有空白并转为小写。"""
    return re.sub(r"\s+", "", value).lower()


def parse_translation_tables(md_path: Path) -> dict[str, dict[str, str]]:
    if not md_path.exists():
        return {}

    categories = {
        "难度等级": "difficulty",
        "英雄": "hero",
        "猴塔": "tower",
        "地图": "map",
        "地图类型": "map_type",
        "游戏模式": "mode",
        "BOSS气球": "boss_bloon",
    }

    result: dict[str, dict[str, str]] = {v: {} for v in categories.values()}
    current_category: str | None = None

    for raw_line in md_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if line.startswith("## "):
            title = line[3:].strip()
            title = title.split(".", 1)[-1].strip() if "." in title else title
            current_category = categories.get(title)
            continue

        if not current_category:
            continue

        if not (line.startswith("|") and line.endswith("|")):
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if set(cells[0]) <= {"-", ":"}:
            continue
        if cells[0] in {"英文", "English"}:
            continue

        eng, zh = cells[0], cells[1]
        if eng and zh:
            zh = re.sub(r"\s+", "", zh)
            result[current_category][eng] = zh
            result[current_category][normalize_translation_key(eng)] = zh

    return result


def tr(value: str | None, table: dict[str, str]) -> str:
    if not value:
        return "未知"
    if value in table:
        return table[value]

    normalized = value.lstrip("#")
    if normalized in table:
        return table[normalized]

    normalized_key = normalize_translation_key(normalized)
    if normalized_key in table:
        return table[normalized_key]

    titled = normalized[:1].upper() + normalized[1:] if normalized else normalized
    if titled in table:
        return table[titled]

    titled_key = normalize_translation_key(titled)
    return table.get(titled_key, value)


def tr_level_label(level: str) -> str:
    mapping = {
        "easy": "简单",
        "medium": "中级",
        "hard": "困难",
        "standard": "标准",
        "elite": "精英",
    }
    return mapping.get(level.lower(), level)


def fmt_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "无" if value is False else "有"
    return str(value)


def _format_multiplier_percent(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    percent = value * 100
    if abs(percent - round(percent)) < 1e-9:
        return f"{int(round(percent))}%"
    return f"{percent:.2f}".rstrip("0").rstrip(".") + "%"


def format_bloon_modifiers(doc: dict[str, Any]) -> str | None:
    modifiers = doc.get("_bloonModifiers")
    if not isinstance(modifiers, dict):
        return None

    items: list[str] = []
    field_map = {
        "speedMultiplier": "气球速度",
        "moabSpeedMultiplier": "MOAB速度",
        "bossSpeedMultiplier": "BOSS速度",
        "regrowRateMultiplier": "重生率",
    }
    for key, label in field_map.items():
        value = modifiers.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value - 1.0) > 1e-9:
            percent = _format_multiplier_percent(value)
            if percent:
                items.append(f"{label}{percent}")

    health_map = {
        "bloons": "气球血量",
        "moabs": "MOAB血量",
        "boss": "BOSS血量",
    }
    health = modifiers.get("healthMultipliers")
    if isinstance(health, dict):
        for key, label in health_map.items():
            value = health.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value - 1.0) > 1e-9:
                percent = _format_multiplier_percent(value)
                if percent:
                    items.append(f"{label}{percent}")

    if modifiers.get("allCamo") is True:
        items.append("全迷彩")
    if modifiers.get("allRegen") is True:
        items.append("全重生")

    return "、".join(items) if items else None


def format_tower_rules(doc: dict[str, Any], trans: dict[str, dict[str, str]]) -> tuple[str | None, str | None]:
    towers = doc.get("_towers")
    if not isinstance(towers, list):
        return None, None

    heroes: list[str] = []
    monkeys: list[str] = []

    for tower_info in towers:
        if not isinstance(tower_info, dict):
            continue

        tower_name = str(tower_info.get("tower", "")).strip()
        if not tower_name:
            continue

        max_count = tower_info.get("max")
        is_hero = tower_info.get("isHero") is True
        if is_hero:
            if max_count == 0:
                continue
            hero_name = tr(tower_name, trans.get("hero", {}))
            if hero_name not in heroes:
                heroes.append(hero_name)
            continue

        if max_count == 0:
            continue

        monkey_name = tr(tower_name, trans.get("tower", {}))
        p1_block = tower_info.get("path1NumBlockedTiers", 0)
        p2_block = tower_info.get("path2NumBlockedTiers", 0)
        p3_block = tower_info.get("path3NumBlockedTiers", 0)
        if all(isinstance(x, int) for x in (p1_block, p2_block, p3_block)):
            tier1 = max(0, 5 - p1_block)
            tier2 = max(0, 5 - p2_block)
            tier3 = max(0, 5 - p3_block)
            tier_text = f"{tier1}-{tier2}-{tier3}"
        else:
            tier_text = "5-5-5"

        extra: list[str] = []
        if isinstance(max_count, int) and max_count > 0:
            extra.append(f"最多{max_count}")
        if tier_text != "5-5-5":
            extra.append(tier_text)

        display = monkey_name if not extra else f"{monkey_name}（{'，'.join(extra)}）"
        monkeys.append(display)

    hero_text = "、".join(heroes) if heroes else None
    monkey_text = "、".join(monkeys) if monkeys else None
    return hero_text, monkey_text


def tr_reward_item(item: str, trans: dict[str, dict[str, str]]) -> str:
    token_map = {
        "MonkeyMoney": "猴钞",
        "CollectionEvent": "收集物",
        "InstaMonkey": "Insta猴",
    }
    if ":" not in item:
        return token_map.get(item, item)

    key, value = item.split(":", 1)
    if key == "InstaMonkey":
        tower_name = value
        suffix = ""
        if "," in value:
            tower_name, suffix = value.split(",", 1)
            suffix = "," + suffix
        tower_zh = tr(tower_name, trans.get("tower", {}))
        return f"{token_map.get(key, key)}:{tower_zh}{suffix}"

    return f"{token_map.get(key, key)}:{value}"


def challenge_doc_brief(doc: dict[str, Any], trans: dict[str, dict[str, str]]) -> list[str]:
    return [
        f"地图: {tr(doc.get('map'), trans.get('map', {}))}",
        f"模式: {tr(doc.get('mode'), trans.get('mode', {}))}",
        f"难度: {tr(doc.get('difficulty'), trans.get('difficulty', {}))}",
        f"回合: {doc.get('startRound', '?')} - {doc.get('endRound', '?')}",
        f"初始资金: {doc.get('startingCash', '?')}",
    ]


def challenge_doc_detail(doc: dict[str, Any], trans: dict[str, dict[str, str]]) -> list[str]:
    lines = [
        f"地图: {tr(doc.get('map'), trans.get('map', {}))}",
        f"模式: {tr(doc.get('mode'), trans.get('mode', {}))}",
        f"难度: {tr(doc.get('difficulty'), trans.get('difficulty', {}))}",
        f"回合: {doc.get('startRound', '?')} - {doc.get('endRound', '?')}",
        f"初始资金: {doc.get('startingCash', '?')}",
        f"生命: {doc.get('lives', '?')} / 最大生命: {doc.get('maxLives', '?')}",
        f"禁止双金: {fmt_bool(doc.get('disableDoubleCash', False))}",
        f"禁止知识: {fmt_bool(doc.get('disableMK', False))}",
        f"禁止道具: {fmt_bool(doc.get('disablePowers', False))}",
        f"禁止出售: {fmt_bool(doc.get('disableSelling', False))}",
        f"最大塔数: {doc.get('maxTowers', '?')}",
    ]

    modifiers = format_bloon_modifiers(doc)
    if modifiers:
        lines.append(f"修改器: {modifiers}")

    heroes, monkeys = format_tower_rules(doc, trans)
    if heroes:
        lines.append(f"英雄: {heroes}")
    if monkeys:
        lines.append(f"猴子: {monkeys}")

    return lines


def sanitize_id(value: str | None) -> str:
    if not value:
        return "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def append_page(url: str, page: int) -> str:
    if "?" in url:
        return f"{url}&page={page}"
    return f"{url}?page={page}"


def format_score_parts(item: dict[str, Any]) -> str:
    parts = item.get("scoreParts", [])
    rendered: list[str] = []
    for part in parts:
        name = part.get("name", "未知")
        score = part.get("score", "?")
        rendered.append(f"{name}={score}")
    return "; ".join(rendered) if rendered else "无"


def format_time_score_ms(value: Any) -> str:
    """将毫秒数格式化为 分:秒:毫秒，若有小时则为 时:分:秒:毫秒。"""
    try:
        ms_total = int(float(value))
    except (TypeError, ValueError):
        return str(value)

    if ms_total < 0:
        ms_total = 0

    hours, rem = divmod(ms_total, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    seconds, milliseconds = divmod(rem, 1000)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"
    return f"{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


def scoring_type_to_label(scoring_type: str) -> str:
    mapping = {
        "GameTime": "少时",
        "LeastCash": "少金",
        "LeastTiers": "少阶",
    }
    return mapping.get(scoring_type, "得分")


def format_score_by_type(score: Any, scoring_type: str) -> str:
    if scoring_type == "GameTime":
        return format_time_score_ms(score)
    return str(score)
