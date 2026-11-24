"""Tesseract wrapper, page preparation, figure detection, PDF text extraction."""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
import threading
from collections import defaultdict, deque
from pathlib import Path

from PIL import Image

from .langs import BY_CODE, OSD_SCRIPT_MODEL, RTL_SCRIPTS, SCRIPT_FONT, model_for
from .layout import Block, Line, Page, Span, join_words

OCR_DPI = 300
OSD_MIN_CONFIDENCE = 5.0
CJK_MODELS = {"chi_sim", "chi_tra", "jpn", "kor"}


def cjk_options(model: str) -> list[str]:
    """Fixed-pitch CJK layout model. Without it Tesseract often takes widely
    spaced Hangul or Han for vertical text and splits lines into single
    characters (measured chrF +3 to +8 on Chinese, Japanese, Korean pages)."""
    if CJK_MODELS & set(model.split("+")):
        return ["-c", "textord_use_cjk_fp_model=1"]
    return []
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
csv.field_size_limit(10_000_000)


def resource_root() -> Path:
    """Folder holding tesseract/ and tessdata/ -- next to the exe when frozen."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1] / "build_assets"


class Cancelled(Exception):
    pass


class Tesseract:
    def __init__(self, root: Path | None = None):
        root = root or resource_root()
        self.exe = root / "tesseract" / "tesseract.exe"
        self.tessdata = root / "tessdata"
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()
        self.cancelled = False
        self._env = dict(os.environ, OMP_THREAD_LIMIT="1")

    def available_models(self, quality: str) -> set[str]:
        base = self.tessdata / quality
        found = {p.stem for p in base.glob("*.traineddata")}
        found |= {f"script/{p.stem}" for p in (base / "script").glob("*.traineddata")}
        return found

    def _run(self, args: list[str]) -> str:
        if self.cancelled:
            raise Cancelled()
        proc = subprocess.Popen([str(self.exe), *args], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=self._env,
                                creationflags=NO_WINDOW)
        with self._lock:
            self._procs.add(proc)
        try:
            out, err = proc.communicate(timeout=600)
        finally:
            with self._lock:
                self._procs.discard(proc)
        if self.cancelled:
            raise Cancelled()
        if proc.returncode != 0:
            raise RuntimeError(err.decode("utf-8", "replace").strip()[-400:] or "tesseract failed")
        return out.decode("utf-8", "replace")

    def cancel(self) -> None:
        self.cancelled = True
        with self._lock:
            for p in list(self._procs):
                try:
                    p.kill()
                except OSError:
                    pass

    def osd(self, image: Path, quality: str) -> tuple[int, str | None]:
        """(rotation needed in degrees, detected script). Fails soft."""
        try:
            out = self._run([str(image), "stdout", "--tessdata-dir", str(self.tessdata / quality),
                             "--psm", "0", "-l", "osd", "--dpi", str(OCR_DPI)])
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 - too little text to tell
            return 0, None
        rotate, script, conf = 0, None, 0.0
        for line in out.splitlines():
            k, _, v = line.partition(":")
            if k.strip() == "Rotate":
                rotate = int(v.strip() or 0)
            elif k.strip() == "Orientation confidence":
                conf = float(v.strip() or 0)
            elif k.strip() == "Script":
                script = v.strip()
        # Genuinely rotated pages score 13-18; sparse or decorative text can
        # produce a confident-looking but wrong rotation around 3-4.
        if conf < OSD_MIN_CONFIDENCE:
            rotate = 0
        return rotate, script

    def tsv(self, image: Path, model: str, quality: str, dpi: int, psm: str = "3") -> list[dict]:
        out = self._run([str(image), "stdout", "--tessdata-dir", str(self.tessdata / quality),
                         "-l", model, "--psm", psm, "--oem", "1", "--dpi", str(dpi),
                         # Config variables, not the "tsv" config file: the
                         # bundle ships no tessdata/configs directory.
                         "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0",
                         *cjk_options(model)])
        return list(csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE))


# --- OCR one page image ----------------------------------------------------------

def ocr_image(tess: Tesseract, gray: Image.Image, color: Image.Image | None, *, tmp: Path,
              langs: list[str], quality: str, auto_rotate: bool, dpi: int,
              model: str | None = None, clean: bool = False) -> Page:
    """OCR one page image.

    model: a fixed Tesseract -l value (an edition that reads one script); skips the
    language and script logic. clean: even out aged paper first (see paper.py).
    """
    from .paper import flatten
    from .textscale import upscale, upscale_factor

    # A crop or a single line (min side < 200 px) is one block, not a page.
    psm = "6" if min(gray.size) < 200 else "3"
    factor = upscale_factor(gray)
    if factor > 1.0:
        # Small text: enlarge so Tesseract can read it. DPI scales with it, so
        # the page keeps its physical size in Word.
        gray, color = upscale(gray, factor), (upscale(color, factor) if color else None)
        dpi = int(dpi * factor)
    path = tmp / f"p{threading.get_ident()}_{id(gray)}.png"
    # Cleaned after enlarging: the paper estimate needs text at a readable size.
    seen = flatten(gray) if clean else gray     # what Tesseract reads
    seen.save(path, "PNG", compress_level=1)
    try:
        auto = not langs and not model
        script = None
        mixed = not model and len({BY_CODE[c].script for c in langs if c in BY_CODE}) > 1
        if auto or auto_rotate or mixed:
            rotate, script = tess.osd(path, quality)
            if auto_rotate and rotate in (90, 180, 270):
                gray = gray.rotate(-rotate, expand=True)
                seen = seen.rotate(-rotate, expand=True) if clean else gray
                if color is not None:
                    color = color.rotate(-rotate, expand=True)
                seen.save(path, "PNG", compress_level=1)

        available = tess.available_models(quality)
        if model:
            first = BY_CODE.get(langs[0]) if langs else None
            rtl, font = (first.rtl, first.font) if first else (False, "Calibri")
        elif auto:
            model = OSD_SCRIPT_MODEL.get(script or "", "eng")
            if "eng" not in model.split("+"):
                model += "+eng"
            rtl = script in RTL_SCRIPTS
            font = SCRIPT_FONT.get(script or "", "Nirmala UI" if script else "Calibri")
        else:
            # Several scripts chosen: load only the models for the script this
            # page is actually in. One combined model across unrelated scripts
            # is far less accurate than the right one alone.
            chosen = [c for c in langs if c in BY_CODE]
            if mixed and script:
                same = [c for c in chosen if BY_CODE[c].script == script]
                chosen = same or chosen
            model = model_for(chosen) or "eng"
            first = BY_CODE[chosen[0]]
            rtl, font = first.rtl, first.font
        model = "+".join(m for m in model.split("+") if m in available) or "eng"

        rows = tess.tsv(path, model, quality, dpi, psm)
        page = page_from_tsv(rows, gray.width, gray.height, dpi)
        page.rtl, page.font = rtl, font
        mark_bold(page, seen)
        page.blocks += detect_figures(gray, color, page.blocks)
        if not page.has_text:
            page.full_image_png = _png(color or gray, max_side=2200)
        return page
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def page_from_tsv(rows: list[dict], width: int, height: int, dpi: int) -> Page:
    words: dict[tuple, list[dict]] = defaultdict(list)
    line_box: dict[tuple, tuple] = {}
    block_box: dict[str, tuple] = {}
    para_order: dict[str, list[str]] = defaultdict(list)
    line_order: dict[tuple, list[tuple]] = defaultdict(list)
    for r in rows:
        try:
            level = int(r["level"])
            box = (int(r["left"]), int(r["top"]),
                   int(r["left"]) + int(r["width"]), int(r["top"]) + int(r["height"]))
        except (KeyError, ValueError, TypeError):
            continue
        b, p, l = r["block_num"], r["par_num"], r["line_num"]
        if level == 2:
            block_box[b] = box
        elif level == 3:
            para_order[b].append(p)
        elif level == 4:
            line_box[(b, p, l)] = box
            line_order[(b, p)].append((b, p, l))
        elif level == 5:
            text = (r.get("text") or "").translate(_BIDI_MARKS).strip()
            conf = float(r.get("conf") or -1)
            if text and conf >= 0 and not _junk(text, conf):
                words[(b, p, l)].append({"text": text, "box": box})

    blocks: list[Block] = []
    for b, bbox in block_box.items():
        paras: list[list[Line]] = []
        for p in para_order.get(b, []):
            lines: list[Line] = []
            for key in line_order.get((b, p), []):
                ws = words.get(key)
                if not ws:
                    continue
                x0, y0, x1, y1 = line_box[key]
                text = ""
                for w in ws:
                    text = join_words(text, w["text"])
                lines.append(Line(x0, y0, x1, y1, [Span(text)]))
            if lines:
                paras.append(lines)
        if paras:
            xs0 = min(l.x0 for p in paras for l in p)
            ys0 = min(l.y0 for p in paras for l in p)
            xs1 = max(l.x1 for p in paras for l in p)
            ys1 = max(l.y1 for p in paras for l in p)
            blocks.append(Block(xs0, ys0, xs1, ys1, "text", paras))
    return Page(float(width), float(height), float(dpi), blocks)


_BIDI_MARKS = {0x200E: None, 0x200F: None, 0x061C: None}


def _junk(word: str, conf: float) -> bool:
    """Dot leaders and rules read as letters ("eeeeerrrr", "OOOCCCO")."""
    distinct = len(set(word.lower()))
    if len(word) >= 12 and distinct / len(word) < 0.3:
        return True    # real words this long use far more distinct letters
    return conf < 50 and len(word) >= 6 and distinct <= 4


def mark_bold(page: Page, gray: Image.Image) -> None:
    """Flag lines whose ink density is well above the page norm as bold.

    LSTM Tesseract reports no font attributes, but bold strokes are thicker,
    so a bold line darkens noticeably more of its box than body text does.
    """
    import numpy as np

    arr = np.asarray(gray)
    lines = [l for b in page.blocks for p in b.paras for l in p]
    dens = []
    for l in lines:
        box = arr[int(l.y0):int(l.y1), int(l.x0):int(l.x1)]
        dens.append(float((box < 128).mean()) if box.size else 0.0)
    if len(dens) < 3:
        return
    med = sorted(dens)[len(dens) // 2]
    for l, d in zip(lines, dens):
        if med > 0 and d > 1.4 * med:
            for sp in l.spans:
                sp.bold = True


# --- figures -----------------------------------------------------------------------

def detect_figures(gray: Image.Image, color: Image.Image | None, text_blocks: list[Block],
                   cell: int = 16) -> list[Block]:
    """Find large non-text ink regions (photos, charts, logos) to carry into Word.

    Works on a coarse occupancy grid: cells with enough non-white pixels and
    not covered by recognised text are flood-filled into regions; regions that
    are big and reasonably solid become figures.
    """
    import numpy as np

    W, H = gray.size
    gw, gh = max(1, W // cell), max(1, H // cell)
    small = np.asarray(gray.resize((gw * 4, gh * 4), Image.BILINEAR), dtype=np.uint8)
    ink = (small < 200).reshape(gh, 4, gw, 4).mean(axis=(1, 3)) > 0.12
    for b in text_blocks:
        for l in (l for p in b.paras for l in p):
            x0, y0 = int(l.x0 // cell) - 1, int(l.y0 // cell) - 1
            x1, y1 = int(l.x1 // cell) + 2, int(l.y1 // cell) + 2
            ink[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = False

    seen = np.zeros_like(ink)
    figures: list[Block] = []
    min_area = 0.012 * gw * gh
    for sy, sx in zip(*np.nonzero(ink)):
        if seen[sy, sx]:
            continue
        q = deque([(sy, sx)])
        seen[sy, sx] = True
        cells = 0
        y0 = y1 = sy
        x0 = x1 = sx
        while q:
            y, x = q.popleft()
            cells += 1
            y0, y1, x0, x1 = min(y0, y), max(y1, y), min(x0, x), max(x1, x)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < gh and 0 <= nx < gw and ink[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if cells < min_area or bw < 0.06 * gw or bh < 0.04 * gh:
            continue
        if cells / (bw * bh) < 0.3:      # frames, rules, scattered specks
            continue
        if bw > 0.95 * gw and bh > 0.95 * gh:  # scan border / dark background
            continue
        box = (x0 * cell, y0 * cell, min(W, (x1 + 1) * cell), min(H, (y1 + 1) * cell))
        crop = (color or gray).crop(box)
        figures.append(Block(*map(float, box), kind="figure", image_png=_png(crop, max_side=1600)))
    return figures


def _png(img: Image.Image, max_side: int) -> bytes:
    im = img
    if max(im.size) > max_side:
        scale = max_side / max(im.size)
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    if im.mode not in ("L", "RGB"):
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=False, compress_level=6)
    return buf.getvalue()


# --- born-digital PDF pages --------------------------------------------------------

def has_usable_text_layer(page) -> bool:
    """A real text layer, not an invisible OCR layer laid over a scan."""
    if len(page.get_text("text").strip()) < 25:
        return False
    try:
        trace = page.get_texttrace()
        visible = sum(len(t.get("chars", ())) for t in trace if t.get("type") != 3)
        hidden = sum(len(t.get("chars", ())) for t in trace if t.get("type") == 3)
        return visible >= hidden
    except Exception:  # noqa: BLE001
        return True


def page_from_pdf_text(page, rtl_hint: bool, font: str) -> Page:
    import pymupdf

    d = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_IMAGES | pymupdf.TEXT_PRESERVE_WHITESPACE)
    blocks: list[Block] = []
    for b in d.get("blocks", []):
        x0, y0, x1, y1 = b["bbox"]
        if b.get("type") == 1:
            if (x1 - x0) * (y1 - y0) < 0.002 * page.rect.width * page.rect.height:
                continue
            try:
                pix = page.get_pixmap(clip=pymupdf.Rect(x0, y0, x1, y1), dpi=150)
                png = pix.tobytes("png")
            except Exception:  # noqa: BLE001
                continue
            blocks.append(Block(x0, y0, x1, y1, "figure", image_png=png))
            continue
        lines: list[Line] = []
        for ln in b.get("lines", []):
            spans = [Span(s["text"], round(s["size"] * 2) / 2,
                          bool(s["flags"] & 16), bool(s["flags"] & 2))
                     for s in ln.get("spans", []) if s.get("text")]
            if spans and "".join(s.text for s in spans).strip():
                lx0, ly0, lx1, ly1 = ln["bbox"]
                lines.append(Line(lx0, ly0, lx1, ly1, spans))
        if lines:
            blocks.append(Block(x0, y0, x1, y1, "text", _split_paras(lines)))
    return Page(page.rect.width, page.rect.height, 72.0, blocks, rtl=rtl_hint, font=font,
                source="text-layer")


def _split_paras(lines: list[Line]) -> list[list[Line]]:
    """PDF blocks often hold several paragraphs; split on large vertical gaps."""
    if len(lines) < 3:
        return [lines]
    gaps = [b.y0 - a.y1 for a, b in zip(lines, lines[1:])]
    typical = sorted(gaps)[len(gaps) // 2]
    paras, cur = [], [lines[0]]
    for gap, ln in zip(gaps, lines[1:]):
        if gap > max(typical * 2.2, ln.height * 0.6):
            paras.append(cur)
            cur = []
        cur.append(ln)
    paras.append(cur)
    return paras
