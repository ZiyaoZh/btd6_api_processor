from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps

from btd6_core.activity_formatter import (
    CATEGORY_LABELS,
    activity_timezone_label,
    challenge_limit_label,
    challenge_modifier_labels,
    format_activity_time,
)
from btd6_core.activity_models import (
    ActivitySnapshot,
    ChallengeConfig,
    InventoryItem,
    PowerRule,
    TowerRule,
)
from btd6_core.cache_store import PROJECT_ROOT
from btd6_core.image_renderer import _load_font


WIDTH = 1080
MAX_HEIGHT = 16000
MARGIN = 46
CONTENT_WIDTH = WIDTH - MARGIN * 2

COLORS = {
    "background": "#11151a",
    "surface": "#1c2229",
    "surface_alt": "#252c34",
    "border": "#37414c",
    "text": "#f2f5f7",
    "muted": "#aeb8c2",
    "accent": "#18c7c9",
    "yellow": "#f4c542",
    "danger": "#ff6b6b",
    "hero": "#805dad",
    "primary": "#20aeda",
    "military": "#68c92e",
    "magic": "#d31bc5",
    "support": "#f3b517",
    "unknown": "#6f7b87",
    "modifier": "#e59a35",
    "positive": "#66bd4a",
}


class BriefCanvas:
    def __init__(self) -> None:
        self.image = Image.new("RGB", (WIDTH, MAX_HEIGHT), COLORS["background"])
        self.draw = ImageDraw.Draw(self.image)
        self.y = 42
        self.fonts: dict[int, ImageFont.ImageFont] = {}

    def font(self, size: int) -> ImageFont.ImageFont:
        if size not in self.fonts:
            self.fonts[size] = _load_font(size)
        return self.fonts[size]

    def text(
        self,
        text: str,
        *,
        size: int = 28,
        fill: str | None = None,
        max_width: int = CONTENT_WIDTH,
        x: int = MARGIN,
        spacing: int = 8,
        align: str = "left",
    ) -> int:
        font = self.font(size)
        lines = _wrap_text(self.draw, str(text), font, max_width)
        line_height = _line_height(self.draw, font)
        for line in lines:
            line_width = self.draw.textlength(line, font=font)
            line_x = x
            if align == "center":
                line_x = x + max(0, (max_width - line_width) / 2)
            self.draw.text((line_x, self.y), line, font=font, fill=fill or COLORS["text"])
            self.y += line_height + spacing
        return len(lines) * (line_height + spacing)

    def header(self, snapshot: ActivitySnapshot, label: str) -> None:
        self.text(label, size=30, fill=COLORS["accent"], spacing=4)
        self.text(snapshot.name, size=54, fill=COLORS["yellow"], spacing=8)
        if snapshot.description:
            self.text(snapshot.description, size=24, fill=COLORS["muted"], spacing=5)
        self.y += 6
        status = {"current": "进行中", "upcoming": "即将开始", "ended": "已结束"}.get(snapshot.status, "状态未知")
        self.tags(
            "",
            [status, f"ID  {snapshot.event_id}", f"范围  {snapshot.event_scope}"],
            category="accent",
            tag_fill=COLORS["surface_alt"],
        )
        if snapshot.start_at is not None or snapshot.end_at is not None:
            self.text(
                f"{format_activity_time(snapshot.start_at)}  至  "
                f"{format_activity_time(snapshot.end_at)}  UTC{activity_timezone_label()}",
                size=25,
                fill=COLORS["muted"],
                spacing=4,
            )
        self.y += 12

    def section(self, title: str) -> None:
        self.y += 18
        self.text(title, size=34, fill=COLORS["accent"], spacing=5)
        self.draw.line(
            (MARGIN, self.y + 2, WIDTH - MARGIN, self.y + 2),
            fill=COLORS["accent"],
            width=2,
        )
        self.y += 18

    def key_values(self, values: Iterable[tuple[str, str]], *, columns: int = 3) -> None:
        items = list(values)
        if not items:
            return
        gap = 12
        cell_width = (CONTENT_WIDTH - gap * (columns - 1)) // columns
        font = self.font(24)
        row_height = 62
        for start in range(0, len(items), columns):
            row = items[start : start + columns]
            for column, (label, value) in enumerate(row):
                x1 = MARGIN + column * (cell_width + gap)
                y1 = self.y
                x2 = x1 + cell_width
                y2 = y1 + row_height
                self.draw.rounded_rectangle(
                    (x1, y1, x2, y2),
                    radius=6,
                    fill=COLORS["surface_alt"],
                    outline=COLORS["border"],
                    width=1,
                )
                self.draw.rectangle((x1, y1, x1 + 6, y2), fill=COLORS["yellow"])
                rendered = _truncate_text(self.draw, f"{label}  {value}", font, cell_width - 30)
                self.draw.text((x1 + 18, y1 + 15), rendered, font=font, fill=COLORS["text"])
            self.y += row_height + gap
        self.y += 4

    def tags(
        self,
        label: str,
        values: Iterable[str],
        *,
        category: str = "unknown",
        tag_fill: str | None = None,
    ) -> None:
        items = [str(value) for value in values if str(value).strip()]
        if not items:
            return
        label_width = 112 if label else 0
        line_height = 48
        gap = 9
        start_y = self.y
        if label:
            self.draw.rounded_rectangle(
                (MARGIN, self.y, MARGIN + label_width - 8, self.y + 42),
                radius=5,
                fill=COLORS.get(category, COLORS["unknown"]),
            )
            label_font = self.font(22)
            display_label = _truncate_text(self.draw, label, label_font, label_width - 24)
            self.draw.text((MARGIN + 12, self.y + 8), display_label, font=label_font, fill="#ffffff")

        font = self.font(22)
        x = MARGIN + label_width
        max_x = WIDTH - MARGIN
        for value in items:
            available_width = CONTENT_WIDTH - label_width - 24
            display = _truncate_text(self.draw, value, font, available_width)
            tag_width = int(self.draw.textlength(display, font=font)) + 28
            if x + tag_width > max_x and x > MARGIN + label_width:
                x = MARGIN + label_width
                self.y += line_height
            self.draw.rounded_rectangle(
                (x, self.y, x + tag_width, self.y + 42),
                radius=5,
                fill=tag_fill or COLORS["surface_alt"],
                outline=COLORS["border"],
                width=1,
            )
            self.draw.text((x + 14, self.y + 8), display, font=font, fill=COLORS["text"])
            x += tag_width + gap
        self.y += line_height
        if self.y == start_y:
            self.y += line_height

    def map_feature(self, challenge: ChallengeConfig) -> None:
        top = self.y
        modifier_badges = [
            (value, COLORS["modifier"])
            for value in challenge_modifier_labels(challenge)
        ]
        badge_font = self.font(20)
        badge_height = _badge_flow_height(
            self.draw,
            modifier_badges,
            max_width=CONTENT_WIDTH - 40,
            font=badge_font,
        )
        height = 274 + max(0, badge_height - 29)
        self.draw.rounded_rectangle(
            (MARGIN, top, WIDTH - MARGIN, top + height),
            radius=7,
            fill=COLORS["surface"],
            outline=COLORS["border"],
            width=1,
        )
        image_box = (MARGIN + 12, top + 12, MARGIN + 384, top + 222)
        _paste_map(self.image, self.draw, challenge, image_box, self.font(24))
        content_x = MARGIN + 410
        content_width = WIDTH - MARGIN - content_x - 18
        title_font = self.font(31)
        title = _truncate_text(
            self.draw,
            f"{challenge.map_name}  /  {challenge.map_id}",
            title_font,
            content_width,
        )
        self.draw.text((content_x, top + 18), title, font=title_font, fill=COLORS["yellow"])
        facts = [
            ("难度", challenge.difficulty_name or challenge.difficulty_id or "未知"),
            ("模式", challenge.mode_name or challenge.mode_id or "未知"),
            ("回合", f"{_show(challenge.start_round)} - {_show(challenge.end_round)}"),
            ("资金", _show(challenge.starting_cash)),
            ("生命", f"{_show(challenge.lives)} / {_show(challenge.max_lives)}"),
            ("塔数", challenge_limit_label(challenge, "max_towers")),
            ("模范", challenge_limit_label(challenge, "max_paragons")),
        ]
        fact_font = self.font(23)
        col_width = content_width // 2
        for index, (label, value) in enumerate(facts):
            column = index % 2
            row = index // 2
            x = content_x + column * col_width
            y = top + 72 + row * 42
            rendered = _truncate_text(self.draw, f"{label}  {value}", fact_font, col_width - 12)
            self.draw.text((x, y), rendered, font=fact_font, fill=COLORS["text"])
        if modifier_badges:
            _draw_inline_badges(
                self.draw,
                modifier_badges,
                x=MARGIN + 20,
                y=top + 232,
                max_width=CONTENT_WIDTH - 40,
                font=badge_font,
            )
        self.y = top + height + 14

    def map_row(self, challenge: ChallengeConfig, index: int) -> None:
        top = self.y
        badges = [
            (value, COLORS["modifier"])
            for value in challenge_modifier_labels(challenge)
        ]
        badges.extend(
            (value, "#63343a")
            for value in _special_rule_tags(challenge)
        )
        badge_font = self.font(18)
        badge_height = _badge_flow_height(
            self.draw,
            badges,
            max_width=WIDTH - MARGIN - (MARGIN + 330) - 16,
            font=badge_font,
        )
        height = 226 + (badge_height + 10 if badges else 0)
        self.draw.rounded_rectangle(
            (MARGIN, top, WIDTH - MARGIN, top + height),
            radius=7,
            fill=COLORS["surface"],
            outline=COLORS["border"],
            width=1,
        )
        image_box = (MARGIN + 10, top + 10, MARGIN + 306, top + height - 10)
        _paste_map(self.image, self.draw, challenge, image_box, self.font(22))
        x = MARGIN + 330
        available_width = WIDTH - MARGIN - x - 16
        title = _truncate_text(
            self.draw,
            f"第 {index} 岛  {challenge.map_name}",
            self.font(28),
            available_width,
        )
        self.draw.text((x, top + 16), title, font=self.font(28), fill=COLORS["yellow"])
        self.draw.text(
            (x, top + 56),
            _truncate_text(self.draw, challenge.map_id, self.font(19), available_width),
            font=self.font(19),
            fill=COLORS["muted"],
        )
        facts = [
            f"难度  {challenge.difficulty_name or challenge.difficulty_id or '未知'}",
            f"模式  {challenge.mode_name or challenge.mode_id or '未知'}",
            f"回合  {_show(challenge.start_round)} - {_show(challenge.end_round)}",
            f"资金  {_show(challenge.starting_cash)}",
            f"生命  {_show(challenge.lives)} / {_show(challenge.max_lives)}",
            f"塔数  {challenge_limit_label(challenge, 'max_towers')}",
            f"模范  {challenge_limit_label(challenge, 'max_paragons')}",
        ]
        fact_font = self.font(21)
        col_width = available_width // 2
        for item_index, fact in enumerate(facts):
            column = item_index % 2
            row = item_index // 2
            rendered = _truncate_text(self.draw, fact, fact_font, col_width - 10)
            self.draw.text((x + column * col_width, top + 88 + row * 33), rendered, font=fact_font, fill=COLORS["text"])
        if badges:
            _draw_inline_badges(
                self.draw,
                badges,
                x=x,
                y=top + 222,
                max_width=available_width,
                font=badge_font,
            )
        self.y = top + height + 14

    def footer(self, fetched_at: str) -> None:
        self.y += 12
        self.draw.line((MARGIN, self.y, WIDTH - MARGIN, self.y), fill=COLORS["border"], width=1)
        self.y += 15
        font = self.font(19)
        self.draw.text((MARGIN, self.y), "数据来源  Ninja Kiwi Open Data API", font=font, fill=COLORS["muted"])
        fetched = f"快照  {fetched_at}"
        width = self.draw.textlength(fetched, font=font)
        self.draw.text((WIDTH - MARGIN - width, self.y), fetched, font=font, fill=COLORS["muted"])
        self.y += _line_height(self.draw, font) + 30

    def finish(self, output_path: Path) -> None:
        if self.y > MAX_HEIGHT:
            raise RuntimeError("活动图内容超过最大画布高度")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.image.crop((0, 0, WIDTH, max(320, self.y))).save(output_path, format="PNG", optimize=True)


def render_activity_brief(snapshot: ActivitySnapshot, output_path: Path) -> None:
    if snapshot.activity_type == "race":
        RaceBriefRenderer().render(snapshot, output_path)
        return
    if snapshot.activity_type == "odyssey":
        OdysseyBriefRenderer().render(snapshot, output_path)
        return
    raise ValueError("活动情报图首版仅支持 race 和 odyssey")


class RaceBriefRenderer:
    def render(self, snapshot: ActivitySnapshot, output_path: Path) -> None:
        if not snapshot.challenges:
            raise RuntimeError("竞速快照缺少挑战配置")
        challenge = snapshot.challenges[0]
        canvas = BriefCanvas()
        canvas.header(snapshot, "竞速情报")
        total_scores = snapshot.score_counts.get("total")
        if total_scores is not None:
            canvas.key_values([("参与成绩", f"{total_scores:,}")], columns=1)
        canvas.section("地图与规则")
        canvas.map_feature(challenge)

        special_rules = _special_rule_tags(challenge)
        if special_rules:
            canvas.tags("规则", special_rules, category="accent")

        canvas.section("可用防御塔")
        available = [item for item in challenge.tower_rules if item.is_available]
        _draw_tower_groups(canvas, available)
        if not available:
            canvas.text("API 未提供防御塔限制。", size=23, fill=COLORS["muted"])

        banned = [
            item.name
            for item in challenge.tower_rules
            if not item.is_available
            and not item.is_hero
            and not item.unknown_fields.get("maxMissing")
        ]
        if banned:
            canvas.section("禁用防御塔")
            canvas.tags("禁用", banned, category="danger", tag_fill="#312a2d")
        canvas.footer(snapshot.fetched_at)
        canvas.finish(output_path)


class OdysseyBriefRenderer:
    def render(self, snapshot: ActivitySnapshot, output_path: Path) -> None:
        odyssey = snapshot.odyssey
        if odyssey is None:
            raise RuntimeError("征程快照缺少难度配置")
        canvas = BriefCanvas()
        canvas.header(snapshot, "征程情报")
        canvas.tags(
            "难度",
            [odyssey.difficulty_name, "极限模式" if odyssey.is_extreme else "普通模式"],
            category="danger" if odyssey.difficulty == "hard" else "accent",
        )
        canvas.section("总体配置")
        canvas.key_values(
            [
                ("英雄位", _show(odyssey.max_hero_seats)),
                ("船员上限", _show(odyssey.max_monkeys_on_boat)),
                ("力量槽", _show(odyssey.max_power_slots)),
                ("初始生命", _show(odyssey.starting_health)),
                ("地图数量", str(len(odyssey.maps))),
            ],
            columns=3,
        )
        if odyssey.rewards:
            canvas.tags("奖励", [_inventory_text(item) for item in odyssey.rewards], category="yellow")

        canvas.section("默认船员与力量")
        canvas.tags("船员", [_inventory_text(item) for item in odyssey.default_towers], category="accent")
        canvas.tags("力量", [_inventory_text(item) for item in odyssey.default_powers], category="modifier")

        canvas.section("可选船员")
        _draw_tower_groups(canvas, [item for item in odyssey.available_towers if item.is_available])

        canvas.section("可选力量")
        power_values = [_power_text(item) for item in odyssey.available_powers if item.is_available]
        canvas.tags("力量", power_values, category="modifier")

        canvas.section("地图列表")
        for index, challenge in enumerate(odyssey.maps, start=1):
            canvas.map_row(challenge, index)
        if not odyssey.maps:
            canvas.text("API 未返回征程地图。", size=23, fill=COLORS["muted"])
        canvas.footer(snapshot.fetched_at)
        canvas.finish(output_path)


def _draw_tower_groups(canvas: BriefCanvas, rules: Iterable[TowerRule]) -> None:
    grouped: dict[str, list[TowerRule]] = defaultdict(list)
    for rule in rules:
        grouped[rule.category].append(rule)
    for category in ("hero", "primary", "military", "magic", "support", "unknown"):
        values = grouped.get(category, [])
        if not values:
            continue
        canvas.tags(
            CATEGORY_LABELS[category],
            [_tower_text(item) for item in values],
            category=category,
        )


def _tower_text(rule: TowerRule) -> str:
    suffixes: list[str] = []
    if rule.max_count is not None:
        suffixes.append(f"x{rule.max_count}")
    if not rule.is_hero and rule.max_tiers != (5, 5, 5):
        suffixes.append("-".join(str(item) for item in rule.max_tiers))
    return rule.name if not suffixes else f"{rule.name}  {' / '.join(suffixes)}"


def _inventory_text(item: InventoryItem) -> str:
    return item.name if item.quantity is None else f"{item.name}  x{item.quantity}"


def _power_text(item: PowerRule) -> str:
    return item.name if item.max_count is None else f"{item.name}  x{item.max_count}"


def _special_rule_tags(challenge: ChallengeConfig) -> list[str]:
    values = (
        ("禁用双倍现金", challenge.disable_double_cash),
        ("禁用即时猴", challenge.disable_instas),
        ("禁用猴子知识", challenge.disable_monkey_knowledge),
        ("禁用力量", challenge.disable_powers),
        ("禁用出售", challenge.disable_selling),
        ("禁止继续", challenge.no_continues),
    )
    return [label for label, enabled in values if enabled]


def _paste_map(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    challenge: ChallengeConfig,
    box: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=5, fill="#0d1115", outline=COLORS["border"], width=1)
    asset_path = _resolve_asset_path(challenge.map_asset.local_path)
    if asset_path and asset_path.is_file():
        try:
            with Image.open(asset_path) as source:
                rendered = ImageOps.contain(
                    source.convert("RGB"),
                    (x2 - x1, y2 - y1),
                    method=Image.Resampling.LANCZOS,
                )
            paste_x = x1 + (x2 - x1 - rendered.width) // 2
            paste_y = y1 + (y2 - y1 - rendered.height) // 2
            image.paste(rendered, (paste_x, paste_y))
            return
        except (OSError, ValueError):
            pass
    label = challenge.map_name or challenge.map_id or "地图资源不可用"
    display = _truncate_text(draw, label, font, max(20, x2 - x1 - 30))
    width = draw.textlength(display, font=font)
    height = _line_height(draw, font)
    draw.text(
        (x1 + (x2 - x1 - width) / 2, y1 + (y2 - y1 - height) / 2),
        display,
        font=font,
        fill=COLORS["muted"],
    )


def _resolve_asset_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _draw_inline_badges(
    draw: ImageDraw.ImageDraw,
    values: Iterable[tuple[str, str]],
    *,
    x: int,
    y: int,
    max_width: int,
    font: ImageFont.ImageFont,
) -> None:
    cursor = x
    max_x = x + max_width
    cursor_y = y
    for value, fill in values:
        display = _truncate_text(draw, value, font, max_width - 22)
        width = int(draw.textlength(display, font=font)) + 22
        if cursor + width > max_x and cursor > x:
            cursor = x
            cursor_y += 35
        draw.rounded_rectangle(
            (cursor, cursor_y, cursor + width, cursor_y + 29),
            radius=4,
            fill=fill,
        )
        draw.text((cursor + 11, cursor_y + 4), display, font=font, fill="#ffffff")
        cursor += width + 8


def _badge_flow_height(
    draw: ImageDraw.ImageDraw,
    values: Iterable[tuple[str, str]],
    *,
    max_width: int,
    font: ImageFont.ImageFont,
) -> int:
    cursor = 0
    rows = 1
    has_values = False
    for value, _fill in values:
        has_values = True
        display = _truncate_text(draw, value, font, max_width - 22)
        width = int(draw.textlength(display, font=font)) + 22
        if cursor + width > max_width and cursor > 0:
            rows += 1
            cursor = 0
        cursor += width + 8
    return 0 if not has_values else 29 + (rows - 1) * 35


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for character in paragraph:
            candidate = current + character
            if current and draw.textlength(candidate, font=font) > max_width:
                lines.append(current.rstrip())
                current = character.lstrip()
            else:
                current = candidate
        lines.append(current.rstrip())
    return lines or [""]


def _truncate_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    value = str(text)
    if draw.textlength(value, font=font) <= max_width:
        return value
    ellipsis = "..."
    while value and draw.textlength(value + ellipsis, font=font) > max_width:
        value = value[:-1]
    return value + ellipsis if value else ellipsis


def _line_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), "国Ag", font=font)
    return box[3] - box[1]


def _show(value: int | None) -> str:
    return "未知" if value is None else str(value)
