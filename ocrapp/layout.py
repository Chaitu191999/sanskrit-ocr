"""Page layout model shared by OCR output and born-digital PDF extraction.

Everything is in pixel coordinates of the page image at `dpi`, so the Word
writer can convert to physical units without caring where the page came from.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class Span:
    text: str
    size_pt: float | None = None   # known for born-digital PDFs
    bold: bool = False
    italic: bool = False


@dataclass
class Line:
    x0: float
    y0: float
    x1: float
    y1: float
    spans: list[Span]

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans).strip()

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class Block:
    x0: float
    y0: float
    x1: float
    y1: float
    kind: str = "text"                     # "text" | "figure"
    paras: list[list[Line]] = field(default_factory=list)
    image_png: bytes | None = None          # figure crop

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class Page:
    width: float
    height: float
    dpi: float
    blocks: list[Block]
    rtl: bool = False
    font: str = "Calibri"
    source: str = "ocr"                     # "ocr" | "text-layer"
    full_image_png: bytes | None = None     # used when no text was found
    error: str | None = None

    @property
    def has_text(self) -> bool:
        return any(b.kind == "text" and b.paras for b in self.blocks)


# --- reading order and column bands ---------------------------------------------

@dataclass
class Band:
    columns: list[list[Block]]
    table: bool = False

    def extents(self) -> list[tuple[float, float]]:
        return [(min(b.x0 for b in c), max(b.x1 for b in c)) for c in self.columns]


def content_box(page: Page) -> tuple[float, float, float, float]:
    bs = page.blocks
    if not bs:
        return (0.0, 0.0, page.width, page.height)
    return (min(b.x0 for b in bs), min(b.y0 for b in bs),
            max(b.x1 for b in bs), max(b.y1 for b in bs))


def bands(page: Page) -> list[Band]:
    """Page -> top-to-bottom bands, each with its columns in reading order.

    Recursive XY-cut over block boxes: a group of blocks is split into columns
    wherever a vertical gutter runs its full height, otherwise into strips at
    horizontal gaps, and each part is cut again. Adjacent strips with the same
    column structure are then merged back, so a three-column article that
    happens to have paragraph gaps at the same height in every column still
    reads column by column rather than row by row.
    """
    if not page.blocks:
        return []
    gutter = max(6.0, 0.010 * page.width)
    out = _merge(_cut(page.blocks, gutter, page.rtl))
    for band in out:
        band.table = _is_table(band)
    return out


def _groups(blocks: list[Block], lo, hi, min_gap: float) -> list[list[Block]]:
    items = sorted(blocks, key=lo)
    groups: list[list[Block]] = [[items[0]]]
    edge = hi(items[0])
    for b in items[1:]:
        if lo(b) - edge >= min_gap:
            groups.append([b])
        else:
            groups[-1].append(b)
        edge = max(edge, hi(b))
    return groups


def _cut(blocks: list[Block], gutter: float, rtl: bool) -> list[Band]:
    if len(blocks) == 1:
        return [Band([list(blocks)])]
    cols = _groups(blocks, lambda b: b.x0, lambda b: b.x1, gutter)
    if len(cols) > 1:
        if rtl:
            cols.reverse()
        return [Band([_flatten(c, gutter, rtl) for c in cols])]
    strips = _groups(blocks, lambda b: b.y0, lambda b: b.y1, 1.0)
    if len(strips) > 1:
        out: list[Band] = []
        for st in strips:
            out += _cut(st, gutter, rtl)
        return out
    # Neither cut works: usually a full-width block (table header, rule-bound
    # heading) whose box grazes the bottom of the columns above it. Split the
    # group above and below the topmost such block and try again.
    gx0, gx1 = min(b.x0 for b in blocks), max(b.x1 for b in blocks)
    wide = [b for b in blocks if b.width > 0.6 * (gx1 - gx0)]
    if wide and len(wide) < len(blocks):
        w = min(wide, key=lambda b: b.y0)
        wc = (w.y0 + w.y1) / 2
        above = [b for b in blocks if b is not w and (b.y0 + b.y1) / 2 < wc]
        below = [b for b in blocks if b is not w and (b.y0 + b.y1) / 2 >= wc]
        return ((_cut(above, gutter, rtl) if above else []) + [Band([[w]])]
                + (_cut(below, gutter, rtl) if below else []))
    return [Band([sorted(blocks, key=lambda b: (b.y0, b.x0))])]


def _flatten(blocks: list[Block], gutter: float, rtl: bool) -> list[Block]:
    out: list[Block] = []
    for band in _merge(_cut(blocks, gutter, rtl)):
        for col in band.columns:
            out += col
    return out


def _merge(bs: list[Band]) -> list[Band]:
    merged: list[Band] = []
    for band in bs:
        if merged and _compatible(merged[-1], band):
            for col, more in zip(merged[-1].columns, band.columns):
                col.extend(more)
        else:
            merged.append(band)
    return merged


def _compatible(a: Band, b: Band) -> bool:
    if len(a.columns) != len(b.columns):
        return False
    if len(a.columns) == 1:
        return True
    for (a0, a1), (b0, b1) in zip(a.extents(), b.extents()):
        if min(a1, b1) - max(a0, b0) <= 0.5 * min(a1 - a0, b1 - b0):
            return False
    return True


def _is_table(band: Band) -> bool:
    """Columns whose lines line up row by row and are not running text.

    Newspaper columns also share a baseline grid, so row alignment alone is
    not enough: running text has equal-width columns filled edge to edge.
    """
    if len(band.columns) < 2:
        return False
    cols = [[l for b in c if b.kind == "text" for p in b.paras for l in p] for c in band.columns]
    if any(len(c) < 2 for c in cols):
        return False
    all_lines = [l for c in cols for l in c]
    matched = 0
    for i, c in enumerate(cols):
        others = [l for j, o in enumerate(cols) if j != i for l in o]
        for l in c:
            yc = (l.y0 + l.y1) / 2
            if any(abs(yc - (o.y0 + o.y1) / 2) < 0.5 * max(l.height, o.height) for o in others):
                matched += 1
    if matched / len(all_lines) < 0.6:
        return False
    widths = [x1 - x0 for x0, x1 in band.extents()]
    full = sum(1 for c, (x0, x1) in zip(cols, band.extents()) for l in c
               if l.x1 - l.x0 >= 0.85 * (x1 - x0))
    return max(widths) / max(1.0, min(widths)) > 1.5 or full / len(all_lines) < 0.4


def table_rows(band: Band) -> list[list[str]]:
    """Group a table band's lines into rows by vertical position."""
    cells: list[tuple[float, float, int, Line]] = []
    for ci, col in enumerate(band.columns):
        for b in col:
            for p in b.paras:
                for l in p:
                    cells.append(((l.y0 + l.y1) / 2, l.height, ci, l))
    cells.sort(key=lambda t: t[0])
    rows: list[list[tuple]] = []
    for c in cells:
        if rows and abs(c[0] - rows[-1][0][0]) < 0.6 * max(c[1], rows[-1][0][1]):
            rows[-1].append(c)
        else:
            rows.append([c])
    out = []
    for r in rows:
        texts = [""] * len(band.columns)
        for _, _, ci, l in sorted(r, key=lambda t: t[3].x0):
            texts[ci] = (texts[ci] + " " + l.text).strip()
        out.append(texts)
    return out


# --- measurement helpers ---------------------------------------------------------

def font_size_pt(lines: list[Line], dpi: float) -> float:
    known = [s.size_pt for l in lines for s in l.spans if s.size_pt]
    if known:
        return round(statistics.median(known) * 2) / 2
    h = statistics.median([l.height for l in lines]) if lines else 12
    # A line box runs ascender to descender: about 0.9 of the em size
    # (calibrated on rendered 8-24 pt text at 300 dpi).
    pt = h / dpi * 72 / 0.9
    return max(6.0, min(48.0, round(pt * 2) / 2))


def alignment(lines: list[Line], col_x0: float, col_x1: float) -> str:
    if len(lines) == 0:
        return "left"
    width = max(1.0, col_x1 - col_x0)
    lefts = [l.x0 - col_x0 for l in lines]
    rights = [col_x1 - l.x1 for l in lines]
    tol = 0.03 * width
    if len(lines) >= 2:
        body = lines[:-1]
        if all(abs(l.x0 - col_x0) < tol for l in body) and all(abs(col_x1 - l.x1) < tol for l in body):
            return "justify"
    if all(abs(a - b) < max(tol, 0.08 * width) and a > 0.08 * width for a, b in zip(lefts, rights)):
        return "center"
    if all(r < tol for r in rights) and all(a > 0.15 * width for a in lefts):
        return "right"
    return "left"


def is_cjk(ch: str) -> bool:
    """Han, kana, and CJK/full-width punctuation: written without word spaces."""
    cp = ord(ch)
    return (0x3000 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF or 0x3400 <= cp <= 0x4DBF
            or 0x4E00 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or 0xFF00 <= cp <= 0xFFEF
            or 0x20000 <= cp <= 0x2A6DF)


def join_words(a: str, b: str) -> str:
    """Join two pieces of text with a space, unless either side is Chinese or Japanese."""
    if not a:
        return b
    if not b:
        return a
    if is_cjk(a[-1]) or is_cjk(b[0]):
        return a + b
    return a + " " + b


def paragraph_text(lines: list[Line], reflow: bool) -> str:
    """Join a paragraph's lines. Reflow joins with spaces and undoes hyphenation."""
    texts = [l.text for l in lines if l.text]
    if not reflow:
        return "\n".join(texts)
    out = ""
    for t in texts:
        if out.endswith("-") and t[:1].islower():
            out = out[:-1] + t
        else:
            out = join_words(out, t)
    return out


def page_text(page: Page) -> str:
    """Plain text in reading order: blank line between paragraphs."""
    paras: list[str] = []
    for band in bands(page):
        if band.table:
            paras.append("\n".join("\t".join(r) for r in table_rows(band)))
            continue
        for col in band.columns:
            for b in col:
                if b.kind != "text":
                    continue
                for p in b.paras:
                    t = paragraph_text(p, reflow=False)
                    if t.strip():
                        paras.append(t)
    return "\n\n".join(paras)
