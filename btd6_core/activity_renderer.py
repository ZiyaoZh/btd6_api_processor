from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

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
from btd6_core.activity_repository import classify_event
from btd6_core.cache_store import PROJECT_ROOT
from btd6_core.image_renderer import _load_font

WIDTH = 1080
MAX_HEIGHT = 16000
MARGIN = 46
CONTENT_WIDTH = WIDTH - MARGIN * 2
ACTIVITY_BRIEF_RENDER_VERSION = "v3"
ACTIVITY_OVERVIEW_RENDER_VERSION = "v3"
ACTIVITY_ASSET_DIR = PROJECT_ROOT / "assets" / "activity_brief"
HEADER_BANNER_PATHS = {
    "race": ACTIVITY_ASSET_DIR / "race_banner.png",
    "odyssey": ACTIVITY_ASSET_DIR / "odyssey_banner.png",
}
BACKGROUND_PATTERN_PATH = ACTIVITY_ASSET_DIR / "hex_pattern.png"
HEADER_ART_HEIGHT = 300
FEATURE_MAP_SIZE = (372, 248)
ROW_MAP_SIZE = (304, 203)
OVERVIEW_MAP_SIZE = (300, 200)
OVERVIEW_ACTIVITY_TYPES = ("race", "boss", "odyssey", "daily")
OVERVIEW_LABELS = {
    "race": "竞速",
    "boss": "Boss",
    "odyssey": "征程",
    "daily": "每日挑战",
}
OVERVIEW_ACCENTS = {
    "race": "#35d1c2",
    "boss": "#ff6b6b",
    "odyssey": "#9b7bd1",
    "daily": "#ffcf45",
}

COLORS = {
    "background": "#0d141a",
    "background_top": "#142735",
    "surface": "#18232c",
    "surface_alt": "#22313d",
    "border": "#355267",
    "text": "#f5f8fa",
    "muted": "#b2c0ca",
    "accent": "#35d1c2",
    "yellow": "#ffcf45",
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


def _create_background(
    activity_type: str,
    fallback_banner_path: Path | None = None,
) -> Image.Image:
    gradient = Image.linear_gradient("L").resize((WIDTH, MAX_HEIGHT))
    image = ImageOps.colorize(
        gradient,
        black=COLORS["background_top"],
        white=COLORS["background"],
    )

    if BACKGROUND_PATTERN_PATH.is_file():
        try:
            with Image.open(BACKGROUND_PATTERN_PATH) as source:
                pattern = source.convert("L")
            alpha = pattern.point(lambda value: min(32, max(0, 255 - value)))
            tint = Image.new("RGB", pattern.size, "#386279")
            for y in range(0, MAX_HEIGHT, pattern.height):
                for x in range(0, WIDTH, pattern.width):
                    image.paste(tint, (x, y), alpha)
        except (OSError, ValueError):
            pass

    banner_path = HEADER_BANNER_PATHS.get(activity_type)
    if banner_path is None or not banner_path.is_file():
        banner_path = fallback_banner_path
    if banner_path and banner_path.is_file():
        try:
            body_header = image.crop((0, 0, WIDTH, HEADER_ART_HEIGHT))
            with Image.open(banner_path) as source:
                rendered = ImageOps.fit(
                    source.convert("RGBA"),
                    (WIDTH, HEADER_ART_HEIGHT),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
            layer = body_header.convert("RGBA")
            layer.alpha_composite(rendered)
            banner = Image.blend(
                layer.convert("RGB"),
                Image.new("RGB", layer.size, "#071722"),
                0.58,
            )
            image.paste(banner, (0, 0))

            fade_height = 88
            fade_top = HEADER_ART_HEIGHT - fade_height
            banner_strip = image.crop((0, fade_top, WIDTH, HEADER_ART_HEIGHT))
            body_strip = body_header.crop((0, fade_top, WIDTH, HEADER_ART_HEIGHT))
            fade = Image.linear_gradient("L").resize((WIDTH, fade_height))
            image.paste(
                Image.composite(body_strip, banner_strip, fade),
                (0, fade_top),
            )
        except (OSError, ValueError):
            pass

    return image


def _paste_header_emblem(image: Image.Image, activity_type: str) -> None:
    path = ACTIVITY_ASSET_DIR / f"{activity_type}_emblem.png"
    if not path.is_file():
        return
    try:
        with Image.open(path) as source:
            rendered = ImageOps.contain(
                source.convert("RGBA"),
                (168, 168),
                method=Image.Resampling.LANCZOS,
            )
        alpha = rendered.getchannel("A").point(lambda value: value * 4 // 5)
        rendered.putalpha(alpha)
        image.paste(
            rendered,
            (WIDTH - MARGIN - rendered.width, 28),
            rendered,
        )
    except (OSError, ValueError):
        return


class BriefCanvas:
    def __init__(self, snapshot: ActivitySnapshot) -> None:
        self.activity_type = snapshot.activity_type
        fallback_banner = None
        if snapshot.challenges:
            fallback_banner = _resolve_asset_path(
                snapshot.challenges[0].map_asset.local_path
            )
        self.image = _create_background(snapshot.activity_type, fallback_banner)
        self.draw = ImageDraw.Draw(self.image)
        self.y = 38
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
            _draw_text_top(
                self.draw,
                (line_x, self.y),
                line,
                font=font,
                fill=fill or COLORS["text"],
            )
            self.y += line_height + spacing
        return len(lines) * (line_height + spacing)

    def header(self, snapshot: ActivitySnapshot, label: str) -> None:
        _paste_header_emblem(self.image, self.activity_type)
        has_emblem = (ACTIVITY_ASSET_DIR / f"{self.activity_type}_emblem.png").is_file()
        header_text_width = 720 if has_emblem else CONTENT_WIDTH
        self.text(
            label,
            size=28,
            fill=COLORS["accent"],
            max_width=header_text_width,
            spacing=8,
        )
        title_size = 52
        while (
            title_size > 38
            and self.draw.textlength(snapshot.name, font=self.font(title_size))
            > header_text_width
        ):
            title_size -= 2
        self.text(
            snapshot.name,
            size=title_size,
            fill=COLORS["yellow"],
            max_width=header_text_width,
            spacing=10,
        )
        if snapshot.description:
            self.text(
                snapshot.description,
                size=23,
                fill=COLORS["muted"],
                max_width=header_text_width,
                spacing=6,
            )
        self.y = max(self.y + 10, 174)
        status = {
            "current": "进行中",
            "upcoming": "即将开始",
            "ended": "已结束",
        }.get(snapshot.status, "状态未知")
        scope = {
            "current": "当前活动",
            "upcoming": "下一期",
            "latest": "最新发布",
        }.get(snapshot.event_scope, snapshot.event_scope or "范围未知")
        self.tags(
            "",
            [status, scope],
            category="accent",
            tag_fill=COLORS["surface_alt"],
        )
        self.text(
            f"活动 ID  {snapshot.event_id}",
            size=19,
            fill=COLORS["muted"],
            spacing=7,
        )
        if snapshot.start_at is not None or snapshot.end_at is not None:
            self.text(
                f"{format_activity_time(snapshot.start_at)}  至  "
                f"{format_activity_time(snapshot.end_at)}  UTC{activity_timezone_label()}",
                size=25,
                fill=COLORS["muted"],
                spacing=4,
            )
        self.y = max(self.y + 14, HEADER_ART_HEIGHT + 12)

    def section(self, title: str) -> None:
        self.y += 20
        self.text(title, size=32, fill=COLORS["accent"], spacing=7)
        self.draw.line(
            (MARGIN, self.y + 3, WIDTH - MARGIN, self.y + 3),
            fill=COLORS["border"],
            width=1,
        )
        self.draw.line(
            (MARGIN, self.y + 3, MARGIN + 78, self.y + 3),
            fill=COLORS["yellow"],
            width=4,
        )
        self.y += 19

    def key_values(self, values: Iterable[tuple[str, str]], *, columns: int = 3) -> None:
        items = list(values)
        if not items:
            return
        gap = 12
        cell_width = (CONTENT_WIDTH - gap * (columns - 1)) // columns
        label_font = self.font(18)
        value_font = self.font(25)
        row_height = 76
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
                self.draw.rectangle((x1, y1 + 7, x1 + 5, y2 - 7), fill=COLORS["yellow"])
                label_text = _truncate_text(self.draw, label, label_font, cell_width - 34)
                value_text = _truncate_text(self.draw, value, value_font, cell_width - 34)
                _draw_text_top(
                    self.draw,
                    (x1 + 18, y1 + 10),
                    label_text,
                    font=label_font,
                    fill=COLORS["muted"],
                )
                _draw_text_top(
                    self.draw,
                    (x1 + 18, y1 + 38),
                    value_text,
                    font=value_font,
                    fill=COLORS["text"],
                )
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
        font = self.font(22)
        tag_height = max(40, _line_height(self.draw, font) + 16)
        line_height = tag_height + 8
        gap = 9
        if label:
            self.draw.rounded_rectangle(
                (MARGIN, self.y, MARGIN + label_width - 8, self.y + tag_height),
                radius=5,
                fill=COLORS.get(category, COLORS["unknown"]),
            )
            label_font = self.font(22)
            display_label = _truncate_text(self.draw, label, label_font, label_width - 24)
            _draw_text_in_rect(
                self.draw,
                (MARGIN + 12, self.y, MARGIN + label_width - 18, self.y + tag_height),
                display_label,
                font=label_font,
                fill="#ffffff",
            )

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
                (x, self.y, x + tag_width, self.y + tag_height),
                radius=5,
                fill=tag_fill or COLORS["surface_alt"],
                outline=COLORS["border"],
                width=1,
            )
            _draw_text_in_rect(
                self.draw,
                (x + 14, self.y, x + tag_width - 10, self.y + tag_height),
                display,
                font=font,
                fill=COLORS["text"],
            )
            x += tag_width + gap
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
            max_width=WIDTH - MARGIN - (MARGIN + 410) - 18,
            font=badge_font,
        )
        height = max(272, 222 + badge_height + 16 if modifier_badges else 272)
        self.draw.rounded_rectangle(
            (MARGIN, top, WIDTH - MARGIN, top + height),
            radius=7,
            fill=COLORS["surface"],
            outline=COLORS["border"],
            width=1,
        )
        image_box = (
            MARGIN + 12,
            top + 12,
            MARGIN + 12 + FEATURE_MAP_SIZE[0],
            top + 12 + FEATURE_MAP_SIZE[1],
        )
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
        _draw_text_top(
            self.draw,
            (content_x, top + 18),
            title,
            font=title_font,
            fill=COLORS["yellow"],
        )
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
            y = top + 72 + row * 38
            rendered = _truncate_text(self.draw, f"{label}  {value}", fact_font, col_width - 12)
            _draw_text_top(
                self.draw,
                (x, y),
                rendered,
                font=fact_font,
                fill=COLORS["text"],
            )
        if modifier_badges:
            _draw_inline_badges(
                self.draw,
                modifier_badges,
                x=content_x,
                y=top + 222,
                max_width=content_width,
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
            max_width=WIDTH - MARGIN - (MARGIN + 340) - 16,
            font=badge_font,
        )
        height = max(227, 207 + badge_height + 14 if badges else 227)
        self.draw.rounded_rectangle(
            (MARGIN, top, WIDTH - MARGIN, top + height),
            radius=7,
            fill=COLORS["surface"],
            outline=COLORS["border"],
            width=1,
        )
        image_box = (
            MARGIN + 12,
            top + 12,
            MARGIN + 12 + ROW_MAP_SIZE[0],
            top + 12 + ROW_MAP_SIZE[1],
        )
        _paste_map(self.image, self.draw, challenge, image_box, self.font(22))
        x = MARGIN + 340
        available_width = WIDTH - MARGIN - x - 16
        title = _truncate_text(
            self.draw,
            f"第 {index} 岛  {challenge.map_name}",
            self.font(28),
            available_width,
        )
        _draw_text_top(
            self.draw,
            (x, top + 15),
            title,
            font=self.font(28),
            fill=COLORS["yellow"],
        )
        _draw_text_top(
            self.draw,
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
            _draw_text_top(
                self.draw,
                (x + column * col_width, top + 86 + row * 30),
                rendered,
                font=fact_font,
                fill=COLORS["text"],
            )
        if badges:
            _draw_inline_badges(
                self.draw,
                badges,
                x=x,
                y=top + 207,
                max_width=available_width,
                font=badge_font,
            )
        self.y = top + height + 14

    def footer(self) -> None:
        self.y += 12
        self.draw.line((MARGIN, self.y, WIDTH - MARGIN, self.y), fill=COLORS["border"], width=1)
        self.y += 15
        font = self.font(19)
        _draw_text_top(
            self.draw,
            (MARGIN, self.y),
            "数据来源  Ninja Kiwi Open Data API",
            font=font,
            fill=COLORS["muted"],
        )
        credit = "图片生成  小污猫"
        width = self.draw.textlength(credit, font=font)
        _draw_text_top(
            self.draw,
            (WIDTH - MARGIN - width, self.y),
            credit,
            font=font,
            fill=COLORS["muted"],
        )
        self.y += _line_height(self.draw, font) + 30

    def finish(self, output_path: Path) -> None:
        if self.y > MAX_HEIGHT:
            raise RuntimeError("活动图内容超过最大画布高度")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.image.crop((0, 0, WIDTH, max(320, self.y))).save(output_path, format="PNG", optimize=True)


def render_activity_brief(snapshot: ActivitySnapshot, output_path: Path) -> None:
    renderers = {
        "race": RaceBriefRenderer,
        "boss": BossBriefRenderer,
        "odyssey": OdysseyBriefRenderer,
        "daily": DailyBriefRenderer,
    }
    renderer_type = renderers.get(snapshot.activity_type)
    if renderer_type is None:
        raise ValueError("活动情报图仅支持 race、boss、odyssey、daily")
    renderer_type().render(snapshot, output_path)


def render_activity_overview(
    snapshots: Iterable[ActivitySnapshot],
    output_path: Path,
    *,
    errors: dict[str, str] | None = None,
    difficulty: str = "hard",
    event_scope: str = "current",
) -> None:
    snapshot_by_type = {item.activity_type: item for item in snapshots}
    error_by_type = errors or {}
    fallback_banner = next(
        (
            _resolve_asset_path(item.challenges[0].map_asset.local_path)
            for item in snapshot_by_type.values()
            if item.challenges
            and _resolve_asset_path(item.challenges[0].map_asset.local_path) is not None
        ),
        None,
    )
    image = _create_background("all", fallback_banner)
    draw = ImageDraw.Draw(image)
    fonts: dict[int, ImageFont.ImageFont] = {}

    def font(size: int) -> ImageFont.ImageFont:
        if size not in fonts:
            fonts[size] = _load_font(size)
        return fonts[size]

    y = 38
    _draw_text_top(
        draw,
        (MARGIN, y),
        "每日早报",
        font=font(28),
        fill=COLORS["accent"],
    )
    y += 43
    _draw_text_top(
        draw,
        (MARGIN, y),
        "BTD6 活动总览",
        font=font(54),
        fill=COLORS["yellow"],
    )
    y += 72
    scope_label = {
        "current": "当前活动",
        "upcoming": "下一期活动",
        "latest": "最新发布",
    }.get(event_scope, "活动总览")
    difficulty_label = {"easy": "简单", "medium": "中级", "hard": "困难"}.get(
        difficulty,
        difficulty,
    )
    subtitle = f"{scope_label}  ·  征程{difficulty_label}难度  ·  竞速 / Boss / 征程 / 每日挑战"
    _draw_text_top(
        draw,
        (MARGIN, y),
        _truncate_text(draw, subtitle, font(23), CONTENT_WIDTH),
        font=font(23),
        fill=COLORS["muted"],
    )
    fetched_dates = sorted(
        {
            item.fetched_at[:10]
            for item in snapshot_by_type.values()
            if len(item.fetched_at) >= 10
        }
    )
    if fetched_dates:
        y += 38
        _draw_text_top(
            draw,
            (MARGIN, y),
            f"数据日期  {fetched_dates[-1]}",
            font=font(21),
            fill=COLORS["muted"],
        )
    y = max(y + 54, HEADER_ART_HEIGHT + 12)

    for activity_type in OVERVIEW_ACTIVITY_TYPES:
        snapshot = snapshot_by_type.get(activity_type)
        y = _draw_overview_card(
            image,
            draw,
            y,
            activity_type,
            snapshot,
            error=error_by_type.get(activity_type, ""),
            font=font,
        )

    y += 8
    draw.line((MARGIN, y, WIDTH - MARGIN, y), fill=COLORS["border"], width=1)
    y += 15
    footer_font = font(19)
    _draw_text_top(
        draw,
        (MARGIN, y),
        "数据来源  Ninja Kiwi Open Data API",
        font=footer_font,
        fill=COLORS["muted"],
    )
    credit = "图片生成  小污猫"
    credit_width = draw.textlength(credit, font=footer_font)
    _draw_text_top(
        draw,
        (WIDTH - MARGIN - credit_width, y),
        credit,
        font=footer_font,
        fill=COLORS["muted"],
    )
    y += _line_height(draw, footer_font) + 30
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.crop((0, 0, WIDTH, max(320, y))).save(
        output_path,
        format="PNG",
        optimize=True,
    )


def _draw_overview_card(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    top: int,
    activity_type: str,
    snapshot: ActivitySnapshot | None,
    *,
    error: str,
    font: Callable[[int], ImageFont.ImageFont],
) -> int:
    height = 236
    bottom = top + height
    accent = OVERVIEW_ACCENTS.get(activity_type, COLORS["accent"])
    draw.rounded_rectangle(
        (MARGIN, top, WIDTH - MARGIN, bottom),
        radius=7,
        fill=COLORS["surface"],
        outline=COLORS["border"],
        width=1,
    )
    draw.rectangle((MARGIN, top + 8, MARGIN + 6, bottom - 8), fill=accent)
    map_box = (
        MARGIN + 18,
        top + 18,
        MARGIN + 18 + OVERVIEW_MAP_SIZE[0],
        top + 18 + OVERVIEW_MAP_SIZE[1],
    )
    challenge = snapshot.challenges[0] if snapshot and snapshot.challenges else None
    if challenge is not None:
        _paste_map(image, draw, challenge, map_box, font(22))
    else:
        draw.rounded_rectangle(
            map_box,
            radius=8,
            fill="#0a1116",
            outline=COLORS["border"],
            width=2,
        )
        _draw_text_in_rect(
            draw,
            (map_box[0] + 14, map_box[1], map_box[2] - 14, map_box[3]),
            "暂无地图数据",
            font=font(22),
            fill=COLORS["muted"],
            align="center",
        )

    content_x = MARGIN + 342
    content_width = WIDTH - MARGIN - content_x - 18
    label = OVERVIEW_LABELS.get(activity_type, activity_type)
    _draw_text_top(
        draw,
        (content_x, top + 16),
        label,
        font=font(25),
        fill=accent,
    )
    status = _overview_status_label(_overview_snapshot_status(snapshot))
    status_font = font(19)
    status_width = int(draw.textlength(status, font=status_font)) + 24
    status_x = WIDTH - MARGIN - 18 - status_width
    draw.rounded_rectangle(
        (status_x, top + 14, status_x + status_width, top + 48),
        radius=5,
        fill=COLORS["surface_alt"],
        outline=accent,
        width=1,
    )
    _draw_text_in_rect(
        draw,
        (status_x + 12, top + 14, status_x + status_width - 10, top + 48),
        status,
        font=status_font,
        fill=COLORS["text"],
    )

    if snapshot is None:
        _draw_text_top(
            draw,
            (content_x, top + 70),
            "暂未取得活动数据",
            font=font(31),
            fill=COLORS["text"],
        )
        if error == "not_published":
            message = "Ninja Kiwi Open Data 官方暂未发布该期活动。"
        elif error:
            message = "数据接口或缓存暂时不可用，请稍后再看。"
        else:
            message = "当前范围没有可用活动。"
        _draw_text_top(
            draw,
            (content_x, top + 125),
            _truncate_text(draw, message, font(22), content_width),
            font=font(22),
            fill=COLORS["muted"],
        )
        return bottom + 16

    title = _truncate_text(draw, snapshot.name or "未命名活动", font(31), content_width)
    _draw_text_top(
        draw,
        (content_x, top + 63),
        title,
        font=font(31),
        fill=COLORS["yellow"],
    )
    time_text = _overview_time_text(snapshot)
    _draw_text_top(
        draw,
        (content_x, top + 108),
        _truncate_text(draw, time_text, font(21), content_width),
        font=font(21),
        fill=COLORS["muted"],
    )
    primary, secondary = _overview_fact_lines(snapshot, challenge)
    _draw_text_top(
        draw,
        (content_x, top + 149),
        _truncate_text(draw, primary, font(23), content_width),
        font=font(23),
        fill=COLORS["text"],
    )
    _draw_text_top(
        draw,
        (content_x, top + 188),
        _truncate_text(draw, secondary, font(21), content_width),
        font=font(21),
        fill=COLORS["muted"],
    )
    return bottom + 16


def _overview_status_label(status: str) -> str:
    return {
        "current": "进行中",
        "upcoming": "即将开始",
        "ended": "已结束",
        "missing": "暂无数据",
    }.get(status, "状态未知")


def _overview_snapshot_status(snapshot: ActivitySnapshot | None) -> str:
    if snapshot is None:
        return "missing"
    status_start_at = snapshot.start_at
    if snapshot.activity_type == "daily":
        created_at = snapshot.attributes.get("created_at")
        status_start_at = (
            created_at
            if isinstance(created_at, int) and not isinstance(created_at, bool)
            else None
        )
    return classify_event(status_start_at, snapshot.end_at)


def _overview_time_text(snapshot: ActivitySnapshot) -> str:
    if snapshot.start_at is not None or snapshot.end_at is not None:
        return (
            f"{format_activity_time(snapshot.start_at)}  至  "
            f"{format_activity_time(snapshot.end_at)}  UTC{activity_timezone_label()}"
        )
    created_at = snapshot.attributes.get("created_at")
    if isinstance(created_at, int) and not isinstance(created_at, bool):
        return f"发布于 {format_activity_time(created_at)}  UTC{activity_timezone_label()}"
    return "活动时间暂未提供"


def _overview_fact_lines(
    snapshot: ActivitySnapshot,
    challenge: ChallengeConfig | None,
) -> tuple[str, str]:
    if snapshot.activity_type == "odyssey" and snapshot.odyssey is not None:
        odyssey = snapshot.odyssey
        map_count = len(odyssey.maps)
        mode = "极限模式" if odyssey.is_extreme else "普通模式"
        first_map = odyssey.maps[0].map_name if odyssey.maps else "地图待公布"
        return (
            f"{odyssey.difficulty_name} · {mode} · {map_count} 张地图",
            f"首站  {first_map}",
        )
    if snapshot.activity_type == "boss":
        boss_name = str(snapshot.attributes.get("boss_type_name", "") or "Boss 类型未知")
        map_name = challenge.map_name if challenge else "地图待公布"
        rounds = _overview_rounds(challenge)
        return f"{boss_name} · {map_name}", f"标准 / 精英  ·  {rounds}"
    if challenge is None:
        return "地图与模式待公布", "详细规则暂未提供"
    difficulty = challenge.difficulty_name or challenge.difficulty_id or "难度未知"
    mode = challenge.mode_name or challenge.mode_id or "模式未知"
    if snapshot.activity_type == "daily":
        return (
            f"{challenge.map_name or '地图待公布'} · {difficulty}",
            f"{mode}  ·  {_overview_rounds(challenge)}",
        )
    return (
        f"{challenge.map_name or '地图待公布'} · {mode}",
        f"{difficulty}  ·  {_overview_rounds(challenge)}",
    )


def _overview_rounds(challenge: ChallengeConfig | None) -> str:
    if challenge is None:
        return "回合待公布"
    if challenge.start_round is None and challenge.end_round is None:
        return "回合待公布"
    return f"第 {_show(challenge.start_round)} - {_show(challenge.end_round)} 回合"


class RaceBriefRenderer:
    def render(self, snapshot: ActivitySnapshot, output_path: Path) -> None:
        if not snapshot.challenges:
            raise RuntimeError("竞速快照缺少挑战配置")
        challenge = snapshot.challenges[0]
        canvas = BriefCanvas(snapshot)
        canvas.header(snapshot, "竞速情报")
        total_scores = snapshot.score_counts.get("total")
        if total_scores is not None:
            canvas.key_values([("参与成绩", f"{total_scores:,}")], columns=1)
        canvas.section("地图与规则")
        canvas.map_feature(challenge)

        _draw_challenge_rules(canvas, challenge)
        canvas.footer()
        canvas.finish(output_path)


class BossBriefRenderer:
    def render(self, snapshot: ActivitySnapshot, output_path: Path) -> None:
        if not snapshot.challenges:
            raise RuntimeError("Boss 快照缺少挑战配置")
        canvas = BriefCanvas(snapshot)
        canvas.header(snapshot, "Boss 情报")
        canvas.key_values(
            [
                (
                    "Boss 类型",
                    str(snapshot.attributes.get("boss_type_name", "") or "未知"),
                ),
                (
                    "标准提交",
                    _show_count(snapshot.score_counts.get("standard")),
                ),
                (
                    "精英提交",
                    _show_count(snapshot.score_counts.get("elite")),
                ),
            ],
            columns=3,
        )

        scoring_types = {
            "standard": snapshot.attributes.get("normal_scoring_type"),
            "elite": snapshot.attributes.get("elite_scoring_type"),
        }
        for challenge in snapshot.challenges:
            variant_label = _challenge_variant_label(challenge.label)
            canvas.section(f"{variant_label}模式")
            canvas.tags(
                "计分",
                [_scoring_type_label(scoring_types.get(challenge.label))],
                category="accent" if challenge.label == "standard" else "danger",
            )
            canvas.map_feature(challenge)
            _draw_challenge_rules(
                canvas,
                challenge,
                available_title=f"{variant_label}可用防御塔",
                banned_title=f"{variant_label}禁用防御塔",
            )

        canvas.footer()
        canvas.finish(output_path)


class DailyBriefRenderer:
    def render(self, snapshot: ActivitySnapshot, output_path: Path) -> None:
        if not snapshot.challenges:
            raise RuntimeError("每日挑战快照缺少挑战配置")
        challenge = snapshot.challenges[0]
        canvas = BriefCanvas(snapshot)
        canvas.header(snapshot, "每日挑战情报")
        created_at = snapshot.attributes.get("created_at")
        if isinstance(created_at, int) and not isinstance(created_at, bool):
            canvas.key_values(
                [
                    (
                        f"发布时间  UTC{activity_timezone_label()}",
                        format_activity_time(created_at),
                    )
                ],
                columns=1,
            )
        canvas.section("地图与规则")
        canvas.map_feature(challenge)
        _draw_challenge_rules(canvas, challenge)
        canvas.footer()
        canvas.finish(output_path)


class OdysseyBriefRenderer:
    def render(self, snapshot: ActivitySnapshot, output_path: Path) -> None:
        odyssey = snapshot.odyssey
        if odyssey is None:
            raise RuntimeError("征程快照缺少难度配置")
        canvas = BriefCanvas(snapshot)
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
        canvas.footer()
        canvas.finish(output_path)


def _draw_challenge_rules(
    canvas: BriefCanvas,
    challenge: ChallengeConfig,
    *,
    available_title: str = "可用防御塔",
    banned_title: str = "禁用防御塔",
) -> None:
    special_rules = _special_rule_tags(challenge)
    if special_rules:
        canvas.tags("规则", special_rules, category="accent")

    canvas.section(available_title)
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
        canvas.section(banned_title)
        canvas.tags("禁用", banned, category="danger", tag_fill="#312a2d")


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


def _show_count(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return "未知"


def _challenge_variant_label(value: str) -> str:
    return {"standard": "标准", "elite": "精英"}.get(value, value or "挑战")


def _scoring_type_label(value: object) -> str:
    return {
        "GameTime": "最短时间",
        "LeastCash": "最少现金",
        "LeastTiers": "最少阶数",
    }.get(str(value or ""), str(value or "未知"))


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
    width = x2 - x1
    height = y2 - y1
    draw.rounded_rectangle(
        (x1, y1, x2 - 1, y2 - 1),
        radius=8,
        fill="#0a1116",
    )
    asset_path = _resolve_asset_path(challenge.map_asset.local_path)
    if asset_path and asset_path.is_file():
        try:
            with Image.open(asset_path) as source:
                rendered = source.convert("RGB").resize(
                    (width, height),
                    resample=Image.Resampling.LANCZOS,
                )
            mask = Image.new("L", rendered.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, width - 1, height - 1),
                radius=8,
                fill=255,
            )
            image.paste(rendered, (x1, y1), mask)
            draw.rounded_rectangle(
                (x1, y1, x2 - 1, y2 - 1),
                radius=8,
                outline=COLORS["border"],
                width=2,
            )
            return
        except (OSError, ValueError):
            pass
    label = challenge.map_name or challenge.map_id or "地图资源不可用"
    display = _truncate_text(draw, label, font, max(20, width - 30))
    _draw_text_in_rect(
        draw,
        (x1 + 15, y1, x2 - 15, y2),
        display,
        font=font,
        fill=COLORS["muted"],
        align="center",
    )
    draw.rounded_rectangle(
        (x1, y1, x2 - 1, y2 - 1),
        radius=8,
        outline=COLORS["border"],
        width=2,
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
    badge_height = _badge_height(draw, font)
    row_step = badge_height + 6
    for value, fill in values:
        display = _truncate_text(draw, value, font, max_width - 22)
        width = int(draw.textlength(display, font=font)) + 22
        if cursor + width > max_x and cursor > x:
            cursor = x
            cursor_y += row_step
        draw.rounded_rectangle(
            (cursor, cursor_y, cursor + width, cursor_y + badge_height),
            radius=4,
            fill=fill,
        )
        _draw_text_in_rect(
            draw,
            (cursor + 11, cursor_y, cursor + width - 8, cursor_y + badge_height),
            display,
            font=font,
            fill="#ffffff",
        )
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
    badge_height = _badge_height(draw, font)
    row_step = badge_height + 6
    for value, _fill in values:
        has_values = True
        display = _truncate_text(draw, value, font, max_width - 22)
        width = int(draw.textlength(display, font=font)) + 22
        if cursor + width > max_width and cursor > 0:
            rows += 1
            cursor = 0
        cursor += width + 8
    return 0 if not has_values else badge_height + (rows - 1) * row_step


def _badge_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    return max(29, _line_height(draw, font) + 12)


def _draw_text_top(
    draw: ImageDraw.ImageDraw,
    position: tuple[float, float],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: str,
) -> tuple[float, float, float, float]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x, y = position
    draw.text((x - left, y - top), text, font=font, fill=fill)
    return (x, y, x + right - left, y + bottom - top)


def _draw_text_in_rect(
    draw: ImageDraw.ImageDraw,
    rect: tuple[float, float, float, float],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: str,
    align: str = "left",
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = rect
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_width = right - left
    text_height = bottom - top
    if align == "center":
        ink_x = x1 + max(0, (x2 - x1 - text_width) / 2)
    elif align == "right":
        ink_x = x2 - text_width
    else:
        ink_x = x1
    ink_y = y1 + max(0, (y2 - y1 - text_height) / 2)
    draw.text((ink_x - left, ink_y - top), text, font=font, fill=fill)
    return (ink_x, ink_y, ink_x + text_width, ink_y + text_height)


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
        if " " in paragraph:
            lines.extend(_wrap_spaced_text(draw, paragraph, font, max_width))
            continue
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


def _wrap_spaced_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = [item for item in re.split(r"\s+", text.strip()) if item]
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
        if draw.textlength(current, font=font) <= max_width:
            continue
        overflow = current
        current = ""
        for character in overflow:
            candidate = current + character
            if current and draw.textlength(candidate, font=font) > max_width:
                lines.append(current.rstrip())
                current = character.lstrip()
            else:
                current = candidate
    lines.append(current.rstrip())
    return lines


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
