from __future__ import annotations

from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any
from urllib import request

from PIL import Image, ImageDraw, ImageFont


LOCAL_FONT_DIR = Path("assets/fonts")
LOCAL_CJK_FONT = LOCAL_FONT_DIR / "NotoSansSC-Regular.otf"
LOCAL_CJK_FONT_URL = "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf"


def _ensure_local_cjk_font() -> Path | None:
    if LOCAL_CJK_FONT.exists():
        return LOCAL_CJK_FONT
    try:
        LOCAL_FONT_DIR.mkdir(parents=True, exist_ok=True)
        with request.urlopen(LOCAL_CJK_FONT_URL, timeout=20) as resp:
            LOCAL_CJK_FONT.write_bytes(resp.read())
        return LOCAL_CJK_FONT
    except Exception:
        return None


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    local_font = _ensure_local_cjk_font()
    candidates = [
        str(local_font) if local_font else "",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if not path:
            continue
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _truncate_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, font: ImageFont.ImageFont) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    current = text
    while current and draw.textlength(current + ellipsis, font=font) > max_width:
        current = current[:-1]
    return current + ellipsis if current else ellipsis


def _draw_center_text(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
) -> None:
    x1, y1, x2, y2 = rect
    text_w = draw.textlength(text, font=font)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_h = bbox[3] - bbox[1]
    x = x1 + max(0, ((x2 - x1) - text_w) / 2)
    y = y1 + max(0, ((y2 - y1) - text_h) / 2)
    draw.text((x, y), text, font=font, fill=fill)


def render_leaderboard_image(table_data: dict[str, Any], entries: list[dict[str, Any]], max_pages: Any, output_path: Path) -> None:
    is_boss = bool(table_data.get("is_boss"))

    width = 2400
    if is_boss:
        blocks = 3
        rows_per_block = 50
        height = 3200
    else:
        blocks = 4
        rows_per_block = 25
        height = 1800

    bg = "#f7f7fb"
    panel = "#ffffff"
    grid = "#d8dbe6"
    text = "#1f2430"
    accent = "#2f80ed"
    row_even = "#f5f9ff"
    row_odd = "#eef3fb"

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(60)
    sub_font = _load_font(30)
    head_font = _load_font(30)
    row_font = _load_font(24)

    margin = 64
    panel_x1, panel_y1 = margin, margin
    panel_x2, panel_y2 = width - margin, height - margin
    draw.rounded_rectangle((panel_x1, panel_y1, panel_x2, panel_y2), radius=22, fill=panel, outline=grid, width=2)

    draw.text((panel_x1 + 32, panel_y1 + 24), table_data["title"], font=title_font, fill=text)
    draw.text((panel_x1 + 32, panel_y1 + 98), f"活动: {table_data['event_name']}", font=sub_font, fill=text)
    draw.text((panel_x1 + 32, panel_y1 + 138), f"提交总人数: {table_data.get('total_submissions', '未知')}", font=sub_font, fill=text)

    table_top = panel_y1 + 200
    table_left = panel_x1 + 24
    table_right = panel_x2 - 24
    table_bottom = panel_y2 - 24

    draw.rectangle((table_left, table_top, table_right, table_bottom), outline=grid, width=2, fill="#fcfcff")

    block_gap = 18
    block_w = (table_right - table_left - block_gap * (blocks - 1)) // blocks
    header_h = 50
    score_title = str(table_data.get("score_label", "得分"))

    for block_idx in range(blocks):
        bx1 = table_left + block_idx * (block_w + block_gap)
        bx2 = bx1 + block_w
        by1 = table_top
        by2 = table_bottom

        draw.rectangle((bx1, by1, bx2, by2), outline=grid, width=1, fill="#fcfcff")
        draw.rectangle((bx1, by1, bx2, by1 + header_h), fill="#eef3ff", outline=grid, width=1)

        rank_split = bx1 + int(block_w * 0.14)
        if is_boss:
            name_split = bx1 + int(block_w * 0.50)
        else:
            name_split = bx1 + int(block_w * 0.66)

        draw.line((rank_split, by1, rank_split, by2), fill=grid, width=1)
        draw.line((name_split, by1, name_split, by2), fill=grid, width=1)

        _draw_center_text(draw, (bx1, by1, rank_split, by1 + header_h), "排行", head_font, accent)
        _draw_center_text(draw, (rank_split, by1, name_split, by1 + header_h), "玩家", head_font, accent)
        _draw_center_text(draw, (name_split, by1, bx2, by1 + header_h), score_title, head_font, accent)

        usable_h = by2 - (by1 + header_h)
        row_h = max(24, usable_h // rows_per_block)

        start = block_idx * rows_per_block
        end = start + rows_per_block
        y = by1 + header_h

        for row_idx in range(start, end):
            y2 = y + row_h
            if y2 > by2:
                break
            fill_color = row_even if (row_idx - start) % 2 == 0 else row_odd
            draw.rectangle((bx1 + 1, y, bx2 - 1, y2), fill=fill_color)
            draw.line((bx1, y2, bx2, y2), fill=grid, width=1)

            if row_idx < len(entries):
                item = entries[row_idx]
                name = _truncate_text(draw, str(item.get("displayName", "Unknown")), name_split - rank_split - 20, row_font)
                score = str(item.get("displayScore", item.get("score", "?")))
            else:
                name = ""
                score = ""

            rank_text = str(row_idx + 1)
            _draw_center_text(draw, (bx1, y, rank_split, y2), rank_text, row_font, text)
            _draw_center_text(draw, (rank_split, y, name_split, y2), name, row_font, text)
            _draw_center_text(draw, (name_split, y, bx2, y2), score, row_font, text)
            y = y2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    footer_font = _load_font(22)
    footer_y = panel_y2 + 4
    draw.text((panel_x1 + 32, footer_y), "数据来源: btd6 open data", font=footer_font, fill="#6b7280")

    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fetched_text = f"数据获取时间: {fetched_at}"
    fetched_w = draw.textlength(fetched_text, font=footer_font)
    fetched_x = panel_x2 - 32 - fetched_w
    draw.text((fetched_x, footer_y), fetched_text, font=footer_font, fill="#6b7280")
    img.save(output_path)
