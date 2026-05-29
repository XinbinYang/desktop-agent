"""Deterministic PowerPoint auto-layout engine.

The LLM provides *semantic* slide content (titles, blocks, tables, bullets,
KPI cards, charts) WITHOUT pixel coordinates. This module measures real text
metrics and computes all geometry: positions, sizes, font sizes, wrapping, and
pagination.  It exists because python-pptx does no text measurement at all, and
LLMs are unreliable at hand-computing layout coordinates.

Geometry is expressed in inches (python-pptx native). Font sizes are points.

Public entry point: ``plan_slides(slide_spec, theme=None) -> list[PlannedSlide]``.
Each planned slide is a plain dict of fully-positioned ``elements`` that the
renderer in ``office_tool.py`` draws verbatim — no further geometry decisions.
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable, Optional

try:  # PIL is already a project dependency (used by the preview renderers).
    from PIL import ImageFont
except Exception:  # pragma: no cover - exercised only in broken envs
    ImageFont = None  # type: ignore


# --------------------------------------------------------------------------
# Canvas constants (16:9 widescreen, inches)
# --------------------------------------------------------------------------
SLIDE_W = 13.333
SLIDE_H = 7.5
MARGIN_X = 0.72
KICKER_Y = 0.40
KICKER_H = 0.26
TITLE_Y = 0.70
CONTENT_GAP = 0.24
CONTENT_BOTTOM = 6.82
FOOTER_Y = 6.92
FOOTER_H = 0.30
BLOCK_GAP = 0.26
COLUMN_GAP = 0.42
CONTENT_W = SLIDE_W - 2 * MARGIN_X  # 11.893

# Font-size envelopes (points)
TITLE_MAX, TITLE_MIN = 30.0, 20.0
SUBTITLE_SIZE = 14.0
KICKER_SIZE = 10.5
FOOTER_SIZE = 9.0
HEADING_SIZE = 16.0
BODY_MAX, BODY_MIN = 15.0, 10.0
BULLET_MAX, BULLET_MIN = 15.0, 10.5
TABLE_MAX, TABLE_MIN = 12.0, 8.0
TABLE_HEADER_BONUS = 0.5
KPI_VALUE_MAX, KPI_VALUE_MIN = 26.0, 14.0
KPI_LABEL_SIZE = 10.5
CALLOUT_SIZE = 13.0

_LINE_FACTOR = 1.34          # line height as a multiple of font size
_PX_PER_INCH = 96.0
_PX_PER_PT = 96.0 / 72.0


DEFAULT_THEME: dict[str, str] = {
    "bg": "F6F1E7",
    "ink": "1A1A2E",
    "muted": "5B6472",
    "accent": "B7791F",
    "blue": "2D6A9F",
    "green": "0F7B5F",
    "header": "1F2A44",
    "header_text": "FFFFFF",
    "card": "FFFFFF",
    "card_alt": "ECEFF4",
    "grid": "D4D8E0",
    "row_alt": "F3F0E8",
}


# --------------------------------------------------------------------------
# Font loading + text measurement
# --------------------------------------------------------------------------
_FONT_FILE_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\msyhl.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

_font_path_cache: Optional[str] = None
_font_cache: dict[int, Any] = {}


def _font_path() -> Optional[str]:
    global _font_path_cache
    if _font_path_cache is not None:
        return _font_path_cache or None
    for path in _FONT_FILE_CANDIDATES:
        try:
            if os.path.exists(path):
                _font_path_cache = path
                return path
        except Exception:
            continue
    _font_path_cache = ""
    return None


def _font(px: int) -> Any:
    px = max(6, min(400, int(px)))
    cached = _font_cache.get(px)
    if cached is not None:
        return cached
    font = None
    if ImageFont is not None:
        path = _font_path()
        if path:
            try:
                font = ImageFont.truetype(path, px)
            except Exception:
                font = None
        if font is None:
            try:
                font = ImageFont.truetype("arial.ttf", px)
            except Exception:
                font = None
        if font is None:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None
    _font_cache[px] = font
    return font


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF      # CJK unified ideographs
        or 0x3400 <= o <= 0x4DBF   # extension A
        or 0x3000 <= o <= 0x303F   # CJK symbols/punctuation
        or 0xFF00 <= o <= 0xFFEF   # full-width forms
        or 0x3040 <= o <= 0x30FF   # hiragana/katakana
    )


def _text_width_px(text: str, font_pt: float) -> float:
    if not text:
        return 0.0
    font = _font(round(font_pt * _PX_PER_PT))
    if font is None:
        est = 0.0
        for ch in text:
            est += font_pt * _PX_PER_PT * (1.0 if _is_cjk(ch) else 0.55)
        return est
    try:
        return float(font.getlength(text))
    except Exception:
        try:
            bbox = font.getbbox(text)
            return float(bbox[2] - bbox[0])
        except Exception:
            return len(text) * font_pt * _PX_PER_PT * 0.6


def text_width_in(text: str, font_pt: float) -> float:
    """Width of a single (un-wrapped) text run, in inches."""
    return _text_width_px(text, font_pt) / _PX_PER_INCH


def line_height_in(font_pt: float) -> float:
    """Height of one text line, in inches."""
    return font_pt * _LINE_FACTOR / 72.0


_BREAKABLE_PUNCT = "，。！？；：、）】》」』%”’"


def _tokenize(line: str) -> list[str]:
    """Split a line into wrap tokens: CJK chars stand alone, Latin words stick."""
    tokens: list[str] = []
    buf = ""
    for ch in line:
        if _is_cjk(ch):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        elif ch == " ":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(" ")
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return tokens


def _hard_break(token: str, font_pt: float, max_px: float) -> list[str]:
    parts: list[str] = []
    cur = ""
    for ch in token:
        if cur and _text_width_px(cur + ch, font_pt) > max_px:
            parts.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return parts or [token]


def wrap_lines(text: str, font_pt: float, max_width_in: float) -> list[str]:
    """Wrap ``text`` to fit ``max_width_in`` at ``font_pt``; returns visual lines."""
    max_px = max(12.0, max_width_in * _PX_PER_INCH)
    out: list[str] = []
    for raw in str(text).replace("\r", "").split("\n"):
        if raw == "":
            out.append("")
            continue
        cur = ""
        for tok in _tokenize(raw):
            if tok == " " and not cur:
                continue
            if cur and _text_width_px(cur + tok, font_pt) > max_px:
                out.append(cur)
                cur = "" if tok == " " else tok
            else:
                cur = cur + tok
            if _text_width_px(cur, font_pt) > max_px:
                pieces = _hard_break(cur, font_pt, max_px)
                out.extend(pieces[:-1])
                cur = pieces[-1]
        out.append(cur)
    return out or [""]


def measure_text(text: str, font_pt: float, max_width_in: float) -> tuple[list[str], float]:
    """Return (wrapped lines, total height in inches)."""
    lines = wrap_lines(text, font_pt, max_width_in)
    return lines, len(lines) * line_height_in(font_pt)


def fit_font_size(
    text: str,
    max_width_in: float,
    max_height_in: float,
    size_max: float,
    size_min: float,
    max_lines: Optional[int] = None,
) -> float:
    """Largest font size in [size_min, size_max] that fits text in the box."""
    size = float(size_max)
    while size > size_min:
        lines = wrap_lines(text, size, max_width_in)
        height = len(lines) * line_height_in(size)
        if height <= max_height_in and (max_lines is None or len(lines) <= max_lines):
            return round(size, 1)
        size -= 0.5
    return round(size_min, 1)


# --------------------------------------------------------------------------
# Element constructors (pure data dicts consumed by the office_tool renderer)
# --------------------------------------------------------------------------
def _text_el(
    x: float, y: float, w: float, h: float, text: str, font_size: float,
    color: str, *, bold: bool = False, align: str = "left",
    anchor: str = "top", italic: bool = False,
) -> dict[str, Any]:
    return {
        "kind": "text", "x": x, "y": y, "w": w, "h": h, "text": text,
        "font_size": font_size, "color": color, "bold": bold, "italic": italic,
        "align": align, "anchor": anchor,
    }


def _rect_el(
    x: float, y: float, w: float, h: float, fill: str, *,
    line_color: Optional[str] = None, rounded: bool = True,
) -> dict[str, Any]:
    return {
        "kind": "rect", "x": x, "y": y, "w": w, "h": h, "fill": fill,
        "line_color": line_color, "rounded": rounded,
    }


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        if "text" in value:
            return str(value.get("text") or "")
        if "value" in value:
            return str(value.get("value") if value.get("value") is not None else "")
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


# --------------------------------------------------------------------------
# Per-block preparation: measure first, emit later (so pagination can decide)
# --------------------------------------------------------------------------
# A "prepared block" is a dict with at least:
#   kind:    str
#   height:  float (inches)
#   emit:    Callable[[x, y, w], list[element]]
# Tables additionally carry "_table" raw data so they can be split across pages.


def _prepare_text(block: dict[str, Any], width: float, theme: dict[str, str]) -> dict[str, Any]:
    heading = str(block.get("heading") or "").strip()
    body = str(block.get("text") or block.get("content") or block.get("body") or "").strip()
    parts: list[tuple[str, float, str, bool]] = []  # (text, size, color, bold)
    if heading:
        h_size = float(block.get("heading_size") or HEADING_SIZE)
        parts.append((heading, h_size, str(block.get("heading_color") or theme["ink"]), True))
    if body:
        b_size = float(block.get("font_size") or BODY_MAX)
        b_size = min(BODY_MAX, max(BODY_MIN, b_size))
        # Shrink long body text so it never needs more than ~10 lines.
        b_size = fit_font_size(body, width, line_height_in(b_size) * 10, b_size, BODY_MIN)
        parts.append((body, b_size, str(block.get("font_color") or theme["ink"]), False))
    if not parts:
        parts.append((" ", BODY_MIN, theme["muted"], False))

    measured: list[tuple[str, float, str, bool, float]] = []
    total = 0.0
    for text, size, color, bold in parts:
        _lines, height = measure_text(text, size, width)
        measured.append((text, size, color, bold, height))
        total += height + 0.04

    def emit(x: float, y: float, w: float) -> list[dict[str, Any]]:
        els: list[dict[str, Any]] = []
        cy = y
        for text, size, color, bold, height in measured:
            els.append(_text_el(x, cy, w, height, text, size, color, bold=bold))
            cy += height + 0.04
        return els

    return {"kind": "text", "height": max(0.3, total), "emit": emit}


def _prepare_bullets(block: dict[str, Any], width: float, theme: dict[str, str]) -> dict[str, Any]:
    raw_items = block.get("items") or block.get("bullets") or []
    items: list[tuple[str, int]] = []
    for item in raw_items:
        if isinstance(item, dict):
            items.append((str(item.get("text") or item.get("label") or ""), int(item.get("level") or 0)))
        else:
            items.append((str(item), 0))
    items = [it for it in items if it[0].strip()]
    if not items:
        return {"kind": "bullets", "height": 0.3, "emit": lambda x, y, w: []}

    heading = str(block.get("heading") or "").strip()
    size = float(block.get("font_size") or BULLET_MAX)
    size = min(BULLET_MAX, max(BULLET_MIN, size))
    indent = 0.30
    gap = 0.10

    def block_height(font: float) -> tuple[float, float]:
        head_h = (line_height_in(HEADING_SIZE) + 0.10) if heading else 0.0
        total = head_h
        for text, level in items:
            avail = width - indent * (level + 1) - 0.18
            _lines, h = measure_text(text, font, avail)
            total += h + gap
        return total, head_h

    total, head_h = block_height(size)
    full = CONTENT_BOTTOM - 2.4
    while size > BULLET_MIN and total > full:
        size -= 0.5
        total, head_h = block_height(size)

    def emit(x: float, y: float, w: float) -> list[dict[str, Any]]:
        els: list[dict[str, Any]] = []
        cy = y
        if heading:
            els.append(_text_el(x, cy, w, line_height_in(HEADING_SIZE), heading,
                                HEADING_SIZE, theme["ink"], bold=True))
            cy += line_height_in(HEADING_SIZE) + 0.10
        for text, level in items:
            off = indent * level
            _lines, h = measure_text(text, size, w - indent - off - 0.18)
            els.append(_text_el(x + off, cy, 0.26, line_height_in(size),
                                "•", size, theme["accent"], bold=True))
            els.append(_text_el(x + off + indent, cy, w - indent - off, h,
                                text, size, theme["ink"]))
            cy += h + gap
        return els

    return {"kind": "bullets", "height": max(0.3, total), "emit": emit}


def _prepare_kpi(block: dict[str, Any], width: float, theme: dict[str, str]) -> dict[str, Any]:
    raw = block.get("items") or block.get("cards") or block.get("metrics") or []
    cards: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            value = _cell_text(item.get("value") if item.get("value") is not None else item.get("v"))
            label = str(item.get("label") or item.get("name") or item.get("k") or "")
            cards.append((value, label))
        else:
            cards.append((str(item), ""))
    cards = [c for c in cards if c[0] or c[1]]
    if not cards:
        return {"kind": "kpi", "height": 0.3, "emit": lambda x, y, w: []}

    per_row = min(4, len(cards))
    rows = math.ceil(len(cards) / per_row)
    card_gap = 0.22
    card_h = 1.18
    card_w = (width - card_gap * (per_row - 1)) / per_row
    total = rows * card_h + (rows - 1) * card_gap

    def emit(x: float, y: float, w: float) -> list[dict[str, Any]]:
        els: list[dict[str, Any]] = []
        eff_w = (w - card_gap * (per_row - 1)) / per_row
        for idx, (value, label) in enumerate(cards):
            r, c = divmod(idx, per_row)
            cx = x + c * (eff_w + card_gap)
            cy = y + r * (card_h + card_gap)
            els.append(_rect_el(cx, cy, eff_w, card_h, theme["card"],
                                line_color=theme["grid"]))
            els.append(_rect_el(cx, cy, 0.07, card_h, theme["accent"], rounded=False))
            v_size = fit_font_size(value or " ", eff_w - 0.40, 0.54,
                                   KPI_VALUE_MAX, KPI_VALUE_MIN, max_lines=1)
            els.append(_text_el(cx + 0.20, cy + 0.14, eff_w - 0.38, 0.54,
                                value, v_size, theme["ink"], bold=True, anchor="middle"))
            els.append(_text_el(cx + 0.20, cy + 0.76, eff_w - 0.38, 0.30,
                                label, KPI_LABEL_SIZE, theme["muted"], anchor="top"))
        return els

    return {"kind": "kpi", "height": total, "emit": emit}


def _prepare_callout(block: dict[str, Any], width: float, theme: dict[str, str]) -> dict[str, Any]:
    text = str(block.get("text") or block.get("content") or block.get("body") or "").strip()
    heading = str(block.get("heading") or block.get("title") or "").strip()
    fill = str(block.get("fill") or "FCF4E2")
    pad = 0.22
    inner_w = width - pad * 2 - 0.12
    head_h = (line_height_in(HEADING_SIZE) + 0.08) if heading else 0.0
    _lines, body_h = measure_text(text or " ", CALLOUT_SIZE, inner_w)
    total = head_h + body_h + pad * 2

    def emit(x: float, y: float, w: float) -> list[dict[str, Any]]:
        iw = w - pad * 2 - 0.12
        els: list[dict[str, Any]] = [_rect_el(x, y, w, total, fill, line_color=theme["accent"])]
        els.append(_rect_el(x, y, 0.09, total, theme["accent"], rounded=False))
        cy = y + pad
        if heading:
            els.append(_text_el(x + pad + 0.06, cy, iw, line_height_in(HEADING_SIZE),
                                heading, HEADING_SIZE, theme["ink"], bold=True))
            cy += line_height_in(HEADING_SIZE) + 0.08
        els.append(_text_el(x + pad + 0.06, cy, iw, body_h, text, CALLOUT_SIZE, theme["ink"]))
        return els

    return {"kind": "callout", "height": total, "emit": emit}


def _prepare_chart(block: dict[str, Any], width: float, theme: dict[str, str]) -> dict[str, Any]:
    height = float(block.get("height") or 3.4)
    height = max(2.2, min(height, CONTENT_BOTTOM - 2.0))
    categories = [str(c) for c in (block.get("categories") or [])]
    series_in = block.get("series") or []
    series: list[dict[str, Any]] = []
    for s in series_in:
        if isinstance(s, dict):
            series.append({
                "name": str(s.get("name") or "Series"),
                "values": [float(v) if _is_number(v) else 0.0 for v in (s.get("values") or [])],
            })
    chart_type = str(block.get("chart_type") or block.get("type") or "bar").lower()
    if chart_type == "chart":
        chart_type = "bar"
    title = str(block.get("title") or block.get("heading") or "").strip()

    def emit(x: float, y: float, w: float) -> list[dict[str, Any]]:
        return [{
            "kind": "chart", "x": x, "y": y, "w": w, "h": height,
            "chart_type": chart_type, "categories": categories,
            "series": series, "title": title,
        }]

    return {"kind": "chart", "height": height, "emit": emit}


def _prepare_image(block: dict[str, Any], width: float, theme: dict[str, str]) -> dict[str, Any]:
    height = float(block.get("height") or block.get("h") or 3.2)
    height = max(1.0, min(height, CONTENT_BOTTOM - 2.0))
    img_w = float(block.get("width") or block.get("w") or width)
    img_w = min(img_w, width)
    path = str(block.get("path") or block.get("image_path") or "")

    def emit(x: float, y: float, w: float) -> list[dict[str, Any]]:
        return [{"kind": "image", "x": x, "y": y, "w": min(img_w, w), "h": height, "path": path}]

    return {"kind": "image", "height": height, "emit": emit}


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", "").replace("%", "").replace("$", "").strip())
            return True
        except Exception:
            return False
    return False


# --------------------------------------------------------------------------
# Tables: column-width + row-height computation, with row pagination support
# --------------------------------------------------------------------------
def _prepare_table(block: dict[str, Any], width: float, theme: dict[str, str]) -> dict[str, Any]:
    raw_rows = block.get("rows") or block.get("data") or []
    grid: list[list[str]] = []
    for row in raw_rows:
        if isinstance(row, list):
            grid.append([_cell_text(c) for c in row])
        elif row is not None:
            grid.append([_cell_text(row)])
    grid = [r for r in grid if r]
    if not grid:
        return {"kind": "table", "height": 0.3, "emit": lambda x, y, w: []}
    ncol = max(len(r) for r in grid)
    for r in grid:
        while len(r) < ncol:
            r.append("")

    has_header = bool(block.get("header", True))
    cell_pad = 0.22  # total horizontal padding inside a cell
    base_font = min(TABLE_MAX, max(TABLE_MIN, float(block.get("font_size") or TABLE_MAX)))

    # Natural column widths from longest single-line cell content.
    natural = [0.62] * ncol
    for ri, r in enumerate(grid):
        f = base_font + (TABLE_HEADER_BONUS if has_header and ri == 0 else 0.0)
        for ci, txt in enumerate(r):
            wid = text_width_in(txt, f) + cell_pad
            natural[ci] = max(natural[ci], min(wid, width * 0.5))
    total_nat = sum(natural)
    if total_nat <= width:
        extra = width - total_nat
        col_w = [natural[ci] + extra * (natural[ci] / total_nat) for ci in range(ncol)]
    else:
        col_w = [max(0.6, natural[ci] * width / total_nat) for ci in range(ncol)]
        s = sum(col_w)
        col_w = [w * width / s for w in col_w]

    def row_heights(font: float) -> list[float]:
        heights: list[float] = []
        for ri, r in enumerate(grid):
            f = font + (TABLE_HEADER_BONUS if has_header and ri == 0 else 0.0)
            max_lines = 1
            for ci, txt in enumerate(r):
                lines = wrap_lines(txt, f, col_w[ci] - cell_pad)
                max_lines = max(max_lines, len(lines))
            heights.append(max(0.34, max_lines * line_height_in(f) + 0.14))
        return heights

    font = base_font
    heights = row_heights(font)
    page_cap = CONTENT_BOTTOM - 1.9
    # Shrink the font if even a single page's worth of rows is impossibly tall.
    while font > TABLE_MIN and sum(heights) > page_cap and max(heights) > 0.9:
        font -= 0.5
        heights = row_heights(font)

    data = {
        "grid": grid, "col_w": col_w, "row_h": heights, "font": font,
        "has_header": has_header,
        "header_fill": str(block.get("header_fill") or theme["header"]),
        "header_text": str(block.get("header_text") or theme["header_text"]),
        "row_alt": str(block.get("row_alt") or theme["row_alt"]),
        "grid_color": str(block.get("grid_color") or theme["grid"]),
        "ink": theme["ink"],
        "cell_pad": cell_pad,
    }

    def emit(x: float, y: float, w: float) -> list[dict[str, Any]]:
        return [_table_element(x, y, data)]

    return {"kind": "table", "height": sum(heights), "emit": emit, "_table": data}


def _table_element(x: float, y: float, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "table", "x": x, "y": y,
        "w": sum(data["col_w"]), "h": sum(data["row_h"]),
        "grid": data["grid"], "col_w": data["col_w"], "row_h": data["row_h"],
        "font_size": data["font"], "has_header": data["has_header"],
        "header_fill": data["header_fill"], "header_text": data["header_text"],
        "row_alt": data["row_alt"], "grid_color": data["grid_color"],
        "ink": data["ink"],
    }


def _split_table(prepared: dict[str, Any], first_avail: float, full_avail: float) -> list[dict[str, Any]]:
    """Split a tall table into page-sized chunks, repeating the header row."""
    data = prepared["_table"]
    grid = data["grid"]
    row_h = data["row_h"]
    has_header = data["has_header"]
    header_row = grid[0] if has_header else None
    header_h = row_h[0] if has_header else 0.0
    body_start = 1 if has_header else 0

    parts: list[dict[str, Any]] = []
    i = body_start
    avail = first_avail
    while i < len(grid):
        chunk_rows: list[list[str]] = []
        chunk_h: list[float] = []
        used = 0.0
        if has_header:
            chunk_rows.append(header_row)  # type: ignore[arg-type]
            chunk_h.append(header_h)
            used += header_h
        while i < len(grid) and used + row_h[i] <= max(avail, header_h + row_h[i]):
            chunk_rows.append(grid[i])
            chunk_h.append(row_h[i])
            used += row_h[i]
            i += 1
            if used > full_avail:
                break
        if len(chunk_rows) <= (1 if has_header else 0) and i < len(grid):
            chunk_rows.append(grid[i])
            chunk_h.append(row_h[i])
            i += 1
        chunk_data = {**data, "grid": chunk_rows, "row_h": chunk_h}
        parts.append({
            "kind": "table",
            "height": sum(chunk_h),
            "emit": (lambda d: (lambda x, y, w: [_table_element(x, y, d)]))(chunk_data),
        })
        avail = full_avail
    return parts


_PREPARERS: dict[str, Callable[[dict[str, Any], float, dict[str, str]], dict[str, Any]]] = {
    "text": _prepare_text,
    "paragraph": _prepare_text,
    "heading": _prepare_text,
    "bullets": _prepare_bullets,
    "bullet_list": _prepare_bullets,
    "list": _prepare_bullets,
    "table": _prepare_table,
    "data_table": _prepare_table,
    "kpi": _prepare_kpi,
    "kpi_cards": _prepare_kpi,
    "metrics": _prepare_kpi,
    "callout": _prepare_callout,
    "note": _prepare_callout,
    "chart": _prepare_chart,
    "image": _prepare_image,
}


def _prepare_block(block: dict[str, Any], width: float, theme: dict[str, str]) -> dict[str, Any]:
    kind = str(block.get("type") or block.get("kind") or "text").lower()
    preparer = _PREPARERS.get(kind, _prepare_text)
    try:
        return preparer(block, width, theme)
    except Exception:
        return _prepare_text({"text": _cell_text(block.get("text") or block.get("content"))},
                             width, theme)


# --------------------------------------------------------------------------
# Slide planning + pagination
# --------------------------------------------------------------------------
def _resolve_theme(slide_spec: dict[str, Any], theme: Optional[dict[str, str]]) -> dict[str, str]:
    resolved = dict(DEFAULT_THEME)
    if theme:
        resolved.update({k: str(v) for k, v in theme.items() if v})
    spec_theme = slide_spec.get("theme")
    if isinstance(spec_theme, dict):
        resolved.update({k: str(v) for k, v in spec_theme.items() if v})
    return resolved


def _header_elements(
    slide_spec: dict[str, Any], theme: dict[str, str], continuation: bool,
) -> tuple[list[dict[str, Any]], float]:
    """Build kicker/title/subtitle elements; return (elements, content_top)."""
    els: list[dict[str, Any]] = []
    cursor = TITLE_Y
    kicker = str(slide_spec.get("kicker") or "").strip()
    if kicker:
        els.append(_text_el(MARGIN_X, KICKER_Y, CONTENT_W, KICKER_H,
                            kicker.upper(), KICKER_SIZE, theme["accent"], bold=True))

    title = str(slide_spec.get("title") or "").strip()
    if title:
        if continuation:
            title = f"{title} ·续"
        t_size = fit_font_size(title, CONTENT_W, line_height_in(TITLE_MAX) * 2 + 0.05,
                               TITLE_MAX, TITLE_MIN, max_lines=2)
        _lines, t_h = measure_text(title, t_size, CONTENT_W)
        els.append(_text_el(MARGIN_X, cursor, CONTENT_W, t_h, title, t_size,
                            str(slide_spec.get("title_color") or theme["ink"]), bold=True))
        # accent underline
        els.append(_rect_el(MARGIN_X, cursor + t_h + 0.05, 0.66, 0.055,
                            theme["accent"], rounded=False))
        cursor += t_h + 0.18

    subtitle = str(slide_spec.get("subtitle") or "").strip()
    if subtitle:
        _lines, s_h = measure_text(subtitle, SUBTITLE_SIZE, CONTENT_W)
        els.append(_text_el(MARGIN_X, cursor, CONTENT_W, s_h, subtitle,
                            SUBTITLE_SIZE, theme["muted"]))
        cursor += s_h + 0.06

    return els, cursor + CONTENT_GAP


def _footer_element(slide_spec: dict[str, Any], theme: dict[str, str]) -> Optional[dict[str, Any]]:
    footer = str(slide_spec.get("footer") or "").strip()
    if not footer:
        return None
    return _text_el(MARGIN_X, FOOTER_Y, CONTENT_W - 0.7, FOOTER_H,
                    footer, FOOTER_SIZE, theme["muted"], anchor="middle")


def _is_section(slide_spec: dict[str, Any]) -> bool:
    layout = str(slide_spec.get("layout") or slide_spec.get("pattern") or "").lower()
    return layout in {"cover", "section", "divider", "title"}


def _plan_section_slide(slide_spec: dict[str, Any], theme: dict[str, str]) -> dict[str, Any]:
    els: list[dict[str, Any]] = []
    kicker = str(slide_spec.get("kicker") or "").strip()
    title = str(slide_spec.get("title") or "").strip()
    subtitle = str(slide_spec.get("subtitle") or "").strip()

    t_size = fit_font_size(title or " ", SLIDE_W - 2.4, line_height_in(46) * 3,
                           46.0, 26.0, max_lines=3)
    _tl, t_h = measure_text(title or " ", t_size, SLIDE_W - 2.4)
    s_h = 0.0
    if subtitle:
        _sl, s_h = measure_text(subtitle, 17.0, SLIDE_W - 3.0)
    kick_h = line_height_in(13.0) if kicker else 0.0
    bar_h = 0.07
    total = kick_h + (0.22 if kicker else 0.0) + t_h + (s_h + 0.34 if subtitle else 0.0) + bar_h + 0.3
    cy = (SLIDE_H - total) / 2

    if kicker:
        els.append(_text_el(1.2, cy, SLIDE_W - 2.4, kick_h, kicker.upper(), 13.0,
                            theme["accent"], bold=True, align="center"))
        cy += kick_h + 0.22
    els.append(_text_el(1.2, cy, SLIDE_W - 2.4, t_h, title, t_size,
                        str(slide_spec.get("title_color") or theme["ink"]),
                        bold=True, align="center"))
    cy += t_h + 0.20
    els.append(_rect_el((SLIDE_W - 1.1) / 2, cy, 1.1, bar_h, theme["accent"], rounded=False))
    cy += bar_h + 0.26
    if subtitle:
        els.append(_text_el(1.5, cy, SLIDE_W - 3.0, s_h, subtitle, 17.0,
                            theme["muted"], align="center"))

    footer = _footer_element(slide_spec, theme)
    if footer:
        els.append(footer)
    return {
        "background": str(slide_spec.get("background") or theme["bg"]),
        "accent": str(slide_spec.get("accent") or theme["accent"]),
        "page_number": bool(slide_spec.get("page_number", True)),
        "speaker_notes": str(slide_spec.get("speaker_notes") or ""),
        "elements": els,
    }


def plan_slides(
    slide_spec: dict[str, Any], theme: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    """Plan one semantic slide spec into 1+ fully-positioned physical slides.

    The returned dicts contain only ``elements`` with absolute inch geometry —
    the renderer makes no further layout decisions.
    """
    resolved = _resolve_theme(slide_spec, theme)
    background = str(slide_spec.get("background") or resolved["bg"])
    accent = str(slide_spec.get("accent") or resolved["accent"])
    page_number = bool(slide_spec.get("page_number", True))
    notes = str(slide_spec.get("speaker_notes") or "")

    if _is_section(slide_spec):
        return [_plan_section_slide(slide_spec, resolved)]

    blocks = [b for b in (slide_spec.get("blocks") or []) if isinstance(b, dict)]
    columns = 2 if int(slide_spec.get("columns") or 1) >= 2 else 1
    if not blocks:
        # Title-only slide with no body content.
        header_els, _top = _header_elements(slide_spec, resolved, continuation=False)
        footer = _footer_element(slide_spec, resolved)
        if footer:
            header_els.append(footer)
        return [{
            "background": background, "accent": accent, "page_number": page_number,
            "speaker_notes": notes, "elements": header_els,
        }]

    if columns == 2:
        return _plan_two_column(slide_spec, blocks, resolved, background, accent,
                                page_number, notes)
    return _plan_single_column(slide_spec, blocks, resolved, background, accent,
                               page_number, notes)


def _plan_single_column(
    slide_spec: dict[str, Any], blocks: list[dict[str, Any]], theme: dict[str, str],
    background: str, accent: str, page_number: bool, notes: str,
) -> list[dict[str, Any]]:
    prepared = [_prepare_block(b, CONTENT_W, theme) for b in blocks]

    header_els, content_top = _header_elements(slide_spec, theme, continuation=False)
    footer = _footer_element(slide_spec, theme)

    pages: list[list[dict[str, Any]]] = [[]]
    cursor = content_top
    page_top = content_top

    def new_page() -> None:
        nonlocal cursor, page_top
        cont_header, cont_top = _header_elements(slide_spec, theme, continuation=True)
        pages.append([])
        pages[-1].extend(_header_with_footer(cont_header, footer))
        page_top = cont_top
        cursor = cont_top

    pages[-1].extend(_header_with_footer(header_els, footer))

    queue = list(prepared)
    idx = 0
    while idx < len(queue):
        block = queue[idx]
        idx += 1
        height = block["height"]
        full_h = CONTENT_BOTTOM - page_top

        if height > full_h and block.get("_table"):
            parts = _split_table(block, CONTENT_BOTTOM - cursor, full_h)
            queue[idx:idx] = parts
            continue

        if cursor + height > CONTENT_BOTTOM and cursor > page_top + 0.01:
            new_page()
            full_h = CONTENT_BOTTOM - page_top
            if height > full_h and block.get("_table"):
                parts = _split_table(block, CONTENT_BOTTOM - cursor, full_h)
                queue[idx:idx] = parts
                continue

        emitted = block["emit"](MARGIN_X, cursor, CONTENT_W)
        pages[-1].extend(emitted)
        cursor += height + BLOCK_GAP

    return _finalize_pages(pages, background, accent, page_number, notes)


def _plan_two_column(
    slide_spec: dict[str, Any], blocks: list[dict[str, Any]], theme: dict[str, str],
    background: str, accent: str, page_number: bool, notes: str,
) -> list[dict[str, Any]]:
    col_w = (CONTENT_W - COLUMN_GAP) / 2
    left_x = MARGIN_X
    right_x = MARGIN_X + col_w + COLUMN_GAP

    header_els, content_top = _header_elements(slide_spec, theme, continuation=False)
    footer = _footer_element(slide_spec, theme)
    elements: list[dict[str, Any]] = list(_header_with_footer(header_els, footer))

    left_blocks: list[dict[str, Any]] = []
    right_blocks: list[dict[str, Any]] = []
    for i, block in enumerate(blocks):
        col = block.get("column")
        target = left_blocks if (col in (0, "left", "l") or (col is None and i % 2 == 0)) else right_blocks
        target.append(block)

    for x, col_blocks in ((left_x, left_blocks), (right_x, right_blocks)):
        cursor = content_top
        for block in col_blocks:
            prepared = _prepare_block(block, col_w, theme)
            elements.extend(prepared["emit"](x, cursor, col_w))
            cursor += prepared["height"] + BLOCK_GAP

    return _finalize_pages([elements], background, accent, page_number, notes)


def _header_with_footer(
    header_els: list[dict[str, Any]], footer: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    els = list(header_els)
    if footer:
        els.append(dict(footer))
    return els


def _finalize_pages(
    pages: list[list[dict[str, Any]]], background: str, accent: str,
    page_number: bool, notes: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for i, elements in enumerate(pages):
        result.append({
            "background": background,
            "accent": accent,
            "page_number": page_number,
            "speaker_notes": notes if i == 0 else "",
            "elements": elements,
        })
    return result
