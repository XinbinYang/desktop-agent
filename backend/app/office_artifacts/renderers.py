from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.runtime_paths import runtime_dir


def _safe_segment(value: str, fallback: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip()).strip("._")
    return cleaned[:100] or fallback


def preview_url(path: Path) -> str:
    preview_root = runtime_dir("preview").resolve()
    rel = path.resolve().relative_to(preview_root)
    return "/preview/" + "/".join(quote(part) for part in rel.parts)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return None, None


def _image_artifact(path: Path, *, kind: str, title: str, index: int) -> dict[str, Any]:
    width, height = _image_dimensions(path)
    payload: dict[str, Any] = {
        "id": f"preview_{_safe_segment(path.stem, 'preview')}_{index}",
        "type": "image",
        "kind": kind,
        "title": title,
        "url": preview_url(path),
        "path": str(path),
        "mime_type": "image/png",
    }
    if width:
        payload["width"] = width
    if height:
        payload["height"] = height
    return payload


def _pdf_pages_to_pngs(pdf_path: Path, output_dir: Path, prefix: str) -> tuple[list[Path], list[str]]:
    try:
        import fitz  # PyMuPDF
    except Exception as exc:
        return [], [f"PyMuPDF unavailable for PDF preview rendering: {exc}"]
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    issues: list[str] = []
    try:
        doc = fitz.open(str(pdf_path))
        for index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7), alpha=False)
            out = output_dir / f"{prefix}_{index:02d}.png"
            pix.save(str(out))
            paths.append(out)
    except Exception as exc:
        issues.append(f"PDF preview rendering failed: {exc}")
    return paths, issues


def _libreoffice_pdf_render(path: Path, output_dir: Path, prefix: str) -> tuple[list[Path], list[str]]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return [], ["LibreOffice rendering unavailable: soffice was not found."]
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
        )
    except Exception as exc:
        return [], [f"LibreOffice conversion failed: {exc}"]
    pdfs = sorted(output_dir.glob(f"{path.stem}*.pdf")) or sorted(output_dir.glob("*.pdf"))
    if not pdfs:
        return [], ["LibreOffice did not produce a PDF preview."]
    return _pdf_pages_to_pngs(pdfs[0], output_dir, prefix)


def _load_fonts(size: int, bold: bool = False):
    from PIL import ImageFont

    names = ["arialbd.ttf" if bold else "arial.ttf", "calibri.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _string_value(cell: dict[str, Any]) -> str:
    if cell.get("formula"):
        return str(cell["formula"])
    value = cell.get("value")
    if value is None:
        return ""
    return str(value)


def _render_sheet_grid(sheet: dict[str, Any], out_path: Path) -> None:
    from PIL import Image, ImageDraw

    rows = sheet.get("rows") or []
    visible_rows = rows[: min(45, len(rows))]
    visible_cols = max((len(row) for row in visible_rows), default=1)
    visible_cols = min(visible_cols, 18)
    row_h = 28
    col_w = 132
    header_h = 42
    row_header_w = 48
    width = row_header_w + visible_cols * col_w + 1
    height = header_h + max(1, len(visible_rows)) * row_h + 1
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    header_font = _load_fonts(15, bold=True)
    cell_font = _load_fonts(13)
    draw.rectangle((0, 0, width, header_h), fill="#EFF6FF")
    draw.text((12, 12), sheet.get("name") or "Sheet", fill="#0F172A", font=header_font)
    for col in range(visible_cols):
        x = row_header_w + col * col_w
        draw.rectangle((x, header_h - 22, x + col_w, header_h), fill="#DBEAFE", outline="#BFDBFE")
        label = chr(ord("A") + col) if col < 26 else str(col + 1)
        draw.text((x + 8, header_h - 19), label, fill="#334155", font=cell_font)
    for row_idx, row in enumerate(visible_rows):
        y = header_h + row_idx * row_h
        draw.rectangle((0, y, row_header_w, y + row_h), fill="#F8FAFC", outline="#E2E8F0")
        draw.text((8, y + 7), str(row_idx + 1), fill="#64748B", font=cell_font)
        for col_idx in range(visible_cols):
            x = row_header_w + col_idx * col_w
            cell = row[col_idx] if col_idx < len(row) else {}
            style = cell.get("style") or {}
            fill = style.get("fill") if isinstance(style.get("fill"), str) and style.get("fill", "").startswith("#") else "#FFFFFF"
            if fill.upper() in {"#000000", "#FFFFFF"}:
                fill = "#FFFFFF"
            draw.rectangle((x, y, x + col_w, y + row_h), fill=fill, outline="#E2E8F0")
            text = _string_value(cell)
            color = "#0F172A"
            if style.get("font_color") and str(style["font_color"]).startswith("#"):
                color = style["font_color"]
            draw.text((x + 7, y + 7), text[:18], fill=color, font=header_font if style.get("bold") else cell_font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def _render_workbook_structural(workbook_payload: dict[str, Any], output_dir: Path) -> tuple[list[Path], list[str]]:
    paths: list[Path] = []
    for index, sheet in enumerate(workbook_payload.get("sheets") or [], start=1):
        out = output_dir / f"excel_sheet_{index:02d}_{_safe_segment(sheet.get('name') or 'sheet', 'sheet')}.png"
        try:
            _render_sheet_grid(sheet, out)
            paths.append(out)
        except Exception:
            continue
    return paths, ["Native workbook rendering unavailable; generated structured sheet previews."]


def _render_excel_com(path: Path, output_dir: Path) -> tuple[list[Path], list[str]]:
    if not _is_windows():
        return [], ["Excel COM rendering is available only on Windows."]
    try:
        import pythoncom
        import win32com.client
        from PIL import ImageGrab
    except Exception as exc:
        return [], [f"Excel COM rendering unavailable: {exc}"]
    pythoncom.CoInitialize()
    excel = None
    workbook = None
    previews: list[Path] = []
    issues: list[str] = []
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        workbook = excel.Workbooks.Open(str(path), UpdateLinks=0, ReadOnly=True)
        for index, sheet in enumerate(workbook.Worksheets, start=1):
            try:
                used = sheet.UsedRange
                used.CopyPicture(Appearance=1, Format=2)
                image = ImageGrab.grabclipboard()
                if image is None:
                    issues.append(f"{sheet.Name}: clipboard did not contain an image.")
                    continue
                out = output_dir / f"excel_sheet_{index:02d}_{_safe_segment(sheet.Name, 'sheet')}.png"
                image.save(out)
                previews.append(out)
            except Exception as exc:
                issues.append(f"{sheet.Name}: render failed: {exc}")
    except Exception as exc:
        issues.append(f"Excel COM render failed: {exc}")
    finally:
        if workbook is not None:
            try:
                workbook.Close(False)
            except Exception:
                pass
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
    return previews, issues


def _render_slide_structural(slide: dict[str, Any], out_path: Path, slide_w: float, slide_h: float) -> None:
    from PIL import Image, ImageDraw

    width = 1600
    height = int(width * (slide_h / slide_w)) if slide_w else 900
    scale_x = width / slide_w if slide_w else 120
    scale_y = height / slide_h if slide_h else 120
    image = Image.new("RGB", (width, height), "#F8F4EA")
    draw = ImageDraw.Draw(image)
    title_font = _load_fonts(40, bold=True)
    body_font = _load_fonts(24)
    small_font = _load_fonts(18)
    draw.rectangle((0, 0, width, height), fill="#F8F4EA")
    for shape in slide.get("shapes") or []:
        bounds = shape.get("bounds") or {}
        x = int(float(bounds.get("x") or 0) * scale_x)
        y = int(float(bounds.get("y") or 0) * scale_y)
        w = max(8, int(float(bounds.get("w") or 1) * scale_x))
        h = max(8, int(float(bounds.get("h") or 1) * scale_y))
        has_table = bool(shape.get("has_table"))
        has_image = bool(shape.get("has_image"))
        fill = "#FFFFFF" if has_table else "#E2E8F0" if has_image else "#F8F4EA"
        outline = "#CBD5E1" if has_table or has_image else "#F8F4EA"
        draw.rectangle((x, y, x + w, y + h), fill=fill, outline=outline)
        if has_table:
            table = shape.get("table") or []
            row_h = max(22, h // max(1, len(table)))
            for r, row in enumerate(table[:8]):
                cy = y + r * row_h
                draw.line((x, cy, x + w, cy), fill="#CBD5E1")
                draw.text((x + 10, cy + 5), " | ".join(str(item) for item in row)[:80], fill="#0F172A", font=small_font)
        elif shape.get("text"):
            text = str(shape.get("text") or "").replace("\n", " ")
            font = title_font if shape.get("index") == 1 or len(text) < 60 and y < height * 0.25 else body_font
            draw.text((x + 8, y + 8), text[:120], fill="#111827", font=font)
    if not any(shape.get("text") for shape in slide.get("shapes") or []):
        draw.text((80, 80), slide.get("title") or f"Slide {slide.get('slide')}", fill="#111827", font=title_font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def _render_presentation_structural(presentation_payload: dict[str, Any], output_dir: Path) -> tuple[list[Path], list[str]]:
    paths: list[Path] = []
    slide_w = float(presentation_payload.get("slide_width") or 13.333)
    slide_h = float(presentation_payload.get("slide_height") or 7.5)
    for slide in presentation_payload.get("slides") or []:
        index = int(slide.get("slide") or len(paths) + 1)
        out = output_dir / f"ppt_slide_{index:02d}.png"
        try:
            _render_slide_structural(slide, out, slide_w, slide_h)
            paths.append(out)
        except Exception:
            continue
    return paths, ["Native presentation rendering unavailable; generated structured slide previews."]


def _render_ppt_com(path: Path, output_dir: Path) -> tuple[list[Path], list[str]]:
    if not _is_windows():
        return [], ["PowerPoint COM rendering is available only on Windows."]
    try:
        import pythoncom
        import win32com.client
    except Exception as exc:
        return [], [f"PowerPoint COM rendering unavailable: {exc}"]
    pythoncom.CoInitialize()
    app = None
    presentation = None
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
        presentation = app.Presentations.Open(str(path), ReadOnly=True, WithWindow=False)
        presentation.Export(str(output_dir), "PNG", 1600, 900)
        return sorted(output_dir.glob("*.PNG")) + sorted(output_dir.glob("*.png")), []
    except Exception as exc:
        return [], [f"PowerPoint COM render failed: {exc}"]
    finally:
        if presentation is not None:
            try:
                presentation.Close()
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def build_contact_sheet(image_paths: list[Path], output_path: Path, title: str) -> Path | None:
    if not image_paths:
        return None
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    thumbs: list[tuple[int, Any]] = []
    for index, path in enumerate(image_paths, start=1):
        try:
            image = Image.open(path).convert("RGB")
            image.thumbnail((360, 203))
            thumbs.append((index, image.copy()))
        except Exception:
            continue
    if not thumbs:
        return None
    cols = min(4, max(1, len(thumbs)))
    rows = math.ceil(len(thumbs) / cols)
    pad = 24
    label_h = 26
    header_h = 54
    cell_w = 360
    cell_h = 203 + label_h
    canvas_w = cols * cell_w + pad * (cols + 1)
    canvas_h = rows * cell_h + pad * (rows + 1) + header_h
    canvas = Image.new("RGB", (canvas_w, canvas_h), "#FFFFFF")
    draw = ImageDraw.Draw(canvas)
    title_font = _load_fonts(24, bold=True)
    label_font = _load_fonts(13)
    draw.text((pad, 18), title, fill="#111827", font=title_font)
    for idx, (slide_number, thumb) in enumerate(thumbs):
        row = idx // cols
        col = idx % cols
        x = pad + col * (cell_w + pad)
        y = header_h + pad + row * (cell_h + pad)
        draw.rectangle((x - 1, y - 1, x + cell_w + 1, y + 203 + 1), outline="#CBD5E1")
        canvas.paste(thumb, (x + (cell_w - thumb.width) // 2, y + (203 - thumb.height) // 2))
        draw.text((x, y + 211), f"Slide {slide_number:02d}", fill="#334155", font=label_font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path


def render_office_previews(
    path: str | Path,
    *,
    kind: str,
    output_dir: Path,
    workbook_payload: dict[str, Any] | None = None,
    presentation_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = Path(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    issues: list[str] = []
    preview_paths: list[Path] = []
    engine = "structural"

    if kind == "excel":
        preview_paths, issues = _render_excel_com(source, output_dir)
        if preview_paths:
            engine = "office_com"
        else:
            libre_paths, libre_issues = _libreoffice_pdf_render(source, output_dir, "excel_page")
            issues.extend(libre_issues)
            if libre_paths:
                preview_paths = libre_paths
                engine = "libreoffice_pdf"
            elif workbook_payload:
                preview_paths, structural_issues = _render_workbook_structural(workbook_payload, output_dir)
                issues.extend(structural_issues)
                engine = "structural"
    elif kind == "ppt":
        preview_paths, issues = _render_ppt_com(source, output_dir)
        if preview_paths:
            engine = "office_com"
        else:
            libre_paths, libre_issues = _libreoffice_pdf_render(source, output_dir, "ppt_slide")
            issues.extend(libre_issues)
            if libre_paths:
                preview_paths = libre_paths
                engine = "libreoffice_pdf"
            elif presentation_payload:
                preview_paths, structural_issues = _render_presentation_structural(presentation_payload, output_dir)
                issues.extend(structural_issues)
                engine = "structural"

    previews: list[dict[str, Any]] = []
    if kind == "ppt" and preview_paths:
        contact = build_contact_sheet(preview_paths, output_dir / "ppt_contact_sheet.png", f"{source.stem} contact sheet")
        if contact:
            previews.append(_image_artifact(contact, kind="ppt_contact_sheet", title=f"{source.stem} contact sheet", index=0))
    for index, preview in enumerate(preview_paths, start=1):
        previews.append(_image_artifact(
            preview,
            kind="excel_sheet" if kind == "excel" else "ppt_slide",
            title=f"{source.stem} {'sheet' if kind == 'excel' else 'slide'} preview {index}",
            index=index,
        ))

    return {
        "engine": engine,
        "issues": issues,
        "previews": previews,
        "preview_paths": [str(path) for path in preview_paths],
    }
