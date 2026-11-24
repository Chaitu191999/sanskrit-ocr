"""Write pages to an editable Word document that keeps the page layout.

What is preserved, per source page:
  * page size and margins
  * column structure (full-width bands and 2-3 column bands, via section columns)
  * reading order, paragraph breaks, alignment, indents and vertical gaps
  * font size (estimated for scans, exact for born-digital PDFs), bold/italic
    where the PDF says so
  * figures (photos, charts, logos) as pictures in their reading position
  * right-to-left paragraphs for Arabic-script and Thaana pages

Text stays flowing and editable -- no text boxes -- which is what makes the
document usable rather than just a picture of the page.
"""
from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Pt

from .layout import (Band, Block, Page, alignment, bands, content_box, font_size_pt,
                     paragraph_text, table_rows)

_ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "center": WD_ALIGN_PARAGRAPH.CENTER, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
EMU_PER_INCH = 914400


def write_docx(pages: list[Page], dest: Path) -> None:
    doc = Document()
    _strip_default_spacing(doc)
    first = True
    for page in pages:
        _write_page(doc, page, first)
        first = False
    if first:  # no pages at all
        doc.add_paragraph("")
    tmp = dest.with_name(dest.name + ".part")
    doc.save(str(tmp))
    tmp.replace(dest)


def _strip_default_spacing(doc: Document) -> None:
    style = doc.styles["Normal"]
    pf = style.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0


def _write_page(doc: Document, page: Page, first: bool) -> None:
    to_emu = EMU_PER_INCH / page.dpi
    cx0, cy0, cx1, cy1 = content_box(page)
    margin = lambda v: Emu(int(min(max(v, 0.25 * page.dpi), 1.25 * page.dpi) * to_emu))  # noqa: E731

    section = doc.sections[0] if first else doc.add_section(WD_SECTION.NEW_PAGE)
    section.page_width = Emu(int(page.width * to_emu))
    section.page_height = Emu(int(page.height * to_emu))
    section.left_margin = margin(cx0)
    section.right_margin = margin(page.width - cx1)
    section.top_margin = margin(cy0)
    # A little slack at the bottom absorbs small differences in Word's text
    # metrics instead of pushing the last lines onto a new page.
    section.bottom_margin = Emu(max(int(0.2 * EMU_PER_INCH), int(margin(page.height - cy1)) - int(0.3 * EMU_PER_INCH)))
    section.header_distance = section.footer_distance = Emu(0)
    # A strip or a screenshot of a few lines is smaller than the minimum
    # margins: grow the page around the content so Word can lay it out.
    need_w = section.left_margin + section.right_margin + int((cx1 - cx0) * to_emu)
    need_h = (section.top_margin + section.bottom_margin + int((cy1 - cy0) * to_emu)
              + int(0.4 * EMU_PER_INCH))
    if section.page_width < need_w:
        section.page_width = Emu(need_w)
    if section.page_height < need_h:
        section.page_height = Emu(need_h)
    _set_columns(section, 1, 0)
    if page.rtl:
        _set_section_rtl(section)

    if not page.has_text:
        if page.full_image_png:
            avail = section.page_width - section.left_margin - section.right_margin
            avail_h = section.page_height - section.top_margin - section.bottom_margin
            _add_picture(doc, page.full_image_png, avail, avail_h)
        else:
            doc.add_paragraph("")
        return

    left_edge = section.left_margin / to_emu      # px
    text_w = (section.page_width - section.left_margin - section.right_margin) / to_emu
    state = {"section": section, "cols": None, "used": False}

    def use_columns(widths: list[float], gaps: list[float]) -> None:
        """Make sure the content that follows sits in a section with these columns."""
        sig = (len(widths), tuple(round(w) for w in widths))
        if state["cols"] == sig:
            return
        if state["used"]:
            state["section"] = doc.add_section(WD_SECTION.CONTINUOUS)
            if page.rtl:
                _set_section_rtl(state["section"])
        _set_columns(state["section"], [int(w * to_emu) for w in widths],
                     [int(g * to_emu) for g in gaps])
        state["cols"], state["used"] = sig, False

    prev_bottom = None
    for band in bands(page):
        if band.table:
            use_columns([text_w], [])
            _write_table(doc, page, band, text_w, to_emu, prev_bottom)
            state["used"] = True
            prev_bottom = max(b.y1 for c in band.columns for b in c)
            continue
        cols = band.columns
        if len(cols) > 3:   # too fragmented for Word columns: one flow, column by column
            cols = [[b for c in cols for b in c]]
        if len(cols) == 1:
            ext = [(left_edge, left_edge + text_w)]
            use_columns([text_w], [])
        else:
            ext = [(min(b.x0 for b in c), max(b.x1 for b in c)) for c in cols]
            widths = [x1 - x0 for x0, x1 in ext]
            if page.rtl:
                gaps = [max(8.0, ext[i][0] - ext[i + 1][1]) for i in range(len(ext) - 1)]
            else:
                gaps = [max(8.0, ext[i + 1][0] - ext[i][1]) for i in range(len(ext) - 1)]
            scale = text_w / max(1.0, sum(widths) + sum(gaps))
            use_columns([w * scale for w in widths], [g * scale for g in gaps])
        # Every column starts at the same height in Word, so each column's
        # first block is offset from the same reference to keep its position.
        ref = prev_bottom if prev_bottom is not None else cy0
        for ci, col in enumerate(cols):
            x0, x1 = ext[ci]
            col_bottom = ref
            for block in col:
                col_bottom = _write_block(doc, page, block, x0, x1, x1 - x0, to_emu, col_bottom)
                state["used"] = True
            if ci < len(cols) - 1:
                p = doc.add_paragraph()
                p.add_run().add_break(WD_BREAK.COLUMN)
            prev_bottom = col_bottom if len(cols) == 1 else max(b.y1 for c in cols for b in c)


def _write_table(doc, page: Page, band: Band, text_w: float, to_emu: float,
                 prev_bottom: float | None) -> None:
    rows = table_rows(band)
    ext = band.extents()
    widths = [x1 - x0 for x0, x1 in ext]
    if page.rtl:   # columns are in reading order; Word lays tables out visually
        rows = [list(reversed(r)) for r in rows]
        widths.reverse()
    lines = [l for c in band.columns for b in c for p in b.paras for l in p]
    size = font_size_pt(lines, page.dpi)
    if prev_bottom is not None:
        top = min(b.y0 for c in band.columns for b in c)
        if top > prev_bottom:
            spacer = doc.add_paragraph()
            spacer.paragraph_format.space_before = Pt(_gap_pt(top - prev_bottom, page.dpi))
    table = doc.add_table(rows=len(rows), cols=len(widths))
    table.autofit = False
    total = max(1.0, sum(widths))
    for ci, w in enumerate(widths):
        cw = Emu(int(text_w * w / total * to_emu))
        for cell in table.columns[ci].cells:
            cell.width = cw
    centers = sorted((l.y0 + l.y1) / 2 for l in lines)
    steps = sorted(b - a for a, b in zip(centers, centers[1:]) if b - a > 0.5 * size / 72 * page.dpi)
    pitch = steps[len(steps) // 2] / page.dpi * 72 if steps else None
    for ri, row in enumerate(rows):
        for ci, text in enumerate(row):
            para = table.cell(ri, ci).paragraphs[0]
            if pitch and size * 0.95 <= pitch <= size * 2.2:
                para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
                para.paragraph_format.line_spacing = Pt(round(pitch * 2) / 2)
            if page.rtl:
                _set_para_rtl(para)
                para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            if text:
                _add_run(para, text, page.font, size, page.rtl)


def _write_block(doc, page: Page, block: Block, col_x0: float, col_x1: float, col_w: float,
                 to_emu: float, prev_bottom: float | None) -> float:
    if block.kind == "figure":
        if block.image_png:
            p = _add_picture(doc, block.image_png, Emu(int(min(block.width, col_w) * to_emu)), None)
            if prev_bottom is not None:
                p.paragraph_format.space_before = Pt(_gap_pt(block.y0 - prev_bottom, page.dpi))
        return block.y1

    for lines in block.paras:
        text = paragraph_text(lines, reflow=True)
        if not text.strip():
            continue
        p = doc.add_paragraph()
        pf = p.paragraph_format
        align = alignment(lines, col_x0, col_x1)
        if page.rtl and align == "left":
            align = "right"
        p.alignment = _ALIGN[align]
        if page.rtl:
            _set_para_rtl(p)

        indent_px = min(l.x0 for l in lines) - col_x0
        right_px = col_x1 - max(l.x1 for l in lines)
        if align in ("left", "justify") and not page.rtl and indent_px > 0.02 * col_w:
            pf.left_indent = Emu(int(indent_px * to_emu))
        if page.rtl and align in ("right", "justify") and right_px > 0.02 * col_w:
            pf.right_indent = Emu(int(right_px * to_emu))
        if len(lines) >= 2 and align in ("left", "justify") and not page.rtl:
            first_extra = lines[0].x0 - min(l.x0 for l in lines[1:])
            if first_extra > 0.015 * col_w:
                pf.first_line_indent = Emu(int(first_extra * to_emu))

        top = lines[0].y0
        if prev_bottom is not None and top > prev_bottom:
            pf.space_before = Pt(_gap_pt(top - prev_bottom, page.dpi))
        prev_bottom = lines[-1].y1

        size = font_size_pt(lines, page.dpi)
        if len(lines) >= 2:
            # Exact line pitch from the page: keeps each column the same
            # height as the original even when Word's font is a little taller.
            steps = sorted(b.y0 - a.y0 for a, b in zip(lines, lines[1:]))
            pitch = steps[len(steps) // 2] / page.dpi * 72
            if size * 0.95 <= pitch <= size * 2.2:
                pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
                pf.line_spacing = Pt(round(pitch * 2) / 2)
        else:
            # Single line: Word's "single" spacing is ~1.22x the font size,
            # taller than print, and it adds up down a dense column.
            pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
            pf.line_spacing = Pt(round(size * 1.15 * 2) / 2)
        if page.source == "text-layer":
            _add_styled_runs(p, lines, page.font, size, page.rtl)
        else:
            r = _add_run(p, text, page.font, size, page.rtl)
            if all(sp.bold for l in lines for sp in l.spans):
                r.bold = True
    return prev_bottom if prev_bottom is not None else block.y1


def _gap_pt(px: float, dpi: float, cap: float = 120.0) -> float:
    pt = px / dpi * 72
    # Ordinary line spacing is already part of the paragraph; only keep the excess.
    return max(0.0, min(cap, round(pt - 2)))


def _add_styled_runs(p, lines, font: str, default_size: float, rtl: bool) -> None:
    first = True
    for ln in lines:
        for i, span in enumerate(ln.spans):
            t = span.text
            if first:
                t = t.lstrip()
            r = _add_run(p, t, font, span.size_pt or default_size, rtl)
            r.bold = span.bold or None
            r.italic = span.italic or None
            first = False
        p.add_run(" ")


def _add_run(p, text: str, font: str, size: float, rtl: bool):
    r = p.add_run(text)
    r.font.size = Pt(size)
    rpr = r._element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), font)
    szcs = OxmlElement("w:szCs")
    szcs.set(qn("w:val"), str(int(size * 2)))
    rpr.append(szcs)
    if rtl:
        rpr.append(OxmlElement("w:rtl"))
    return r


def _add_picture(doc, png: bytes, max_w, max_h):
    from PIL import Image

    with Image.open(io.BytesIO(png)) as im:
        w, h = im.size
    width = max_w
    if max_h is not None and w and h and int(max_w) * h / w > int(max_h):
        width = Emu(int(int(max_h) * w / h))
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(io.BytesIO(png), width=width)
    return p


def _set_columns(section, widths_emu, gaps_emu) -> None:
    """Section columns with explicit widths (Word columns default to equal)."""
    if isinstance(widths_emu, int):           # (count, space) form
        widths_emu, gaps_emu = [0] * widths_emu, [gaps_emu] * max(0, widths_emu - 1)
    sectPr = section._sectPr
    cols = sectPr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sectPr.append(cols)
    for child in list(cols):
        cols.remove(child)
    n = len(widths_emu)
    twips = lambda emu: str(max(0, int(emu / 635)))  # noqa: E731
    cols.set(qn("w:num"), str(n))
    cols.set(qn("w:space"), twips(gaps_emu[0]) if gaps_emu else "720")
    if n > 1 and all(widths_emu):
        cols.set(qn("w:equalWidth"), "0")
        for i, w in enumerate(widths_emu):
            col = OxmlElement("w:col")
            col.set(qn("w:w"), twips(w))
            if i < n - 1:
                col.set(qn("w:space"), twips(gaps_emu[i]))
            cols.append(col)
    else:
        cols.set(qn("w:equalWidth"), "1")


def _set_section_rtl(section) -> None:
    sectPr = section._sectPr
    if sectPr.find(qn("w:bidi")) is None:
        bidi = OxmlElement("w:bidi")
        grid = sectPr.find(qn("w:docGrid"))   # schema order: bidi precedes docGrid
        if grid is not None:
            grid.addprevious(bidi)
        else:
            sectPr.append(bidi)


def _set_para_rtl(p) -> None:
    ppr = p._element.get_or_add_pPr()
    if ppr.find(qn("w:bidi")) is None:
        ppr.insert(0, OxmlElement("w:bidi"))
