"""Batch runner: find files, OCR every page in parallel, write outputs beside each file."""
from __future__ import annotations

import os
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from .docx_writer import write_docx
from .engine import (OCR_DPI, Cancelled, Tesseract, has_usable_text_layer, ocr_image,
                     page_from_pdf_text)
from .langs import BY_CODE
from .layout import Page, page_text

Image.MAX_IMAGE_PIXELS = 400_000_000
PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif", ".jp2"}
INPUT_EXT = PDF_EXT | IMAGE_EXT
OUT_SUFFIX = "_OCR"


@dataclass
class FileItem:
    path: str
    root: str                 # folder the user added (for display)
    pages: int = 0
    done: int = 0
    status: str = "queued"    # queued | running | done | failed | cancelled
    error: str = ""
    outputs: list[str] = field(default_factory=list)

    def view(self) -> dict:
        p = Path(self.path)
        try:
            rel = str(p.parent.relative_to(self.root)) if self.root else ""
        except ValueError:
            rel = str(p.parent)
        return {"path": self.path, "name": p.name, "folder": "" if rel == "." else rel,
                "ext": p.suffix.lower().lstrip("."), "pages": self.pages, "done": self.done,
                "status": self.status, "error": self.error, "outputs": self.outputs}


def discover(paths: list[str]) -> list[FileItem]:
    """Expand files and folders (recursively) into input files, keeping order."""
    out: list[FileItem] = []
    seen: set[str] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith((".", "$")))
                for name in sorted(filenames, key=str.lower):
                    f = Path(dirpath) / name
                    if _is_input(f) and str(f) not in seen:
                        seen.add(str(f))
                        out.append(FileItem(str(f), str(p)))
        elif p.is_file() and _is_input(p) and str(p) not in seen:
            seen.add(str(p))
            out.append(FileItem(str(p), str(p.parent)))
    return out


def _is_input(p: Path) -> bool:
    return (p.suffix.lower() in INPUT_EXT and not p.name.startswith("~$")
            and not p.stem.endswith(OUT_SUFFIX))


def count_pages(path: str) -> int:
    ext = Path(path).suffix.lower()
    try:
        if ext in PDF_EXT:
            import pymupdf
            with pymupdf.open(path) as doc:
                return doc.page_count
        with Image.open(path) as im:
            return getattr(im, "n_frames", 1) or 1
    except Exception:  # noqa: BLE001 - reported when the file is processed
        return 1


@dataclass
class Settings:
    langs: list[str]            # empty = automatic script detection
    want_txt: bool = True
    want_docx: bool = True
    quality: str = "fast"       # "fast" | "best"
    auto_rotate: bool = True
    use_text_layer: bool = True
    workers: int = 0            # 0 = automatic
    model: str = ""             # fixed Tesseract model (single-script editions); "" = from langs
    clean_paper: bool = False   # even out yellowed or stained paper before reading


class Job:
    def __init__(self, files: list[FileItem], settings: Settings):
        self.files = files
        self.s = settings
        self.tess = Tesseract()
        self.started = 0.0
        self.finished = 0.0
        self.state = "idle"     # idle | counting | running | done | cancelled
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.total_pages = 0
        self.done_pages = 0

    # -- control ---------------------------------------------------------------
    def start(self) -> None:
        self.state = "counting"
        self.started = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        if self.state in ("counting", "running"):
            self.state = "cancelled"
            self.tess.cancel()

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = (self.finished or time.time()) - self.started if self.started else 0
            rate = self.done_pages / elapsed if elapsed > 0 and self.done_pages else 0
            left = (self.total_pages - self.done_pages) / rate if rate else None
            return {
                "state": self.state, "total": self.total_pages, "done": self.done_pages,
                "elapsed": elapsed, "rate": rate, "eta": left,
                "files": [f.view() for f in self.files],
                "failed": sum(f.status == "failed" for f in self.files),
                "completed": sum(f.status == "done" for f in self.files),
            }

    # -- work ------------------------------------------------------------------
    def _run(self) -> None:
        workers = self.s.workers or max(1, min(8, (os.cpu_count() or 4) - 1))
        try:
            for f in self.files:
                if self.state == "cancelled":
                    return
                f.pages = count_pages(f.path)
            with self._lock:
                self.total_pages = sum(f.pages for f in self.files)
                if self.state != "cancelled":
                    self.state = "running"
            with tempfile.TemporaryDirectory(prefix="lipi_") as tmp, \
                    ThreadPoolExecutor(max_workers=workers) as pool:
                tmpdir = Path(tmp)
                # Files are processed in order, but pages of the current and the
                # next files overlap, so workers never idle at file boundaries.
                # Files finish (and are written) in order, while enough pages of
                # later files stay queued that workers never idle between files.
                from collections import deque
                pending: deque[tuple[FileItem, list]] = deque()
                inflight = 0
                for f in self.files:
                    if self.state == "cancelled":
                        break
                    futures = [pool.submit(self._page, f, i, tmpdir) for i in range(f.pages)]
                    pending.append((f, futures))
                    inflight += len(futures)
                    while pending and inflight - len(pending[0][1]) >= 2 * workers:
                        g, gf = pending.popleft()
                        inflight -= len(gf)
                        self._finish_file(g, gf)
                while pending:
                    self._finish_file(*pending.popleft())
        except Exception:  # noqa: BLE001 - never let the worker thread die silently
            traceback.print_exc()
        finally:
            for f in self.files:
                if f.status in ("queued", "running"):
                    f.status = "cancelled" if self.state == "cancelled" else f.status
            self.finished = time.time()
            if self.state != "cancelled":
                self.state = "done"

    def _finish_file(self, f: FileItem, futures: list) -> None:
        pages: list[Page | None] = [None] * len(futures)
        errors: list[str] = []
        for fut in as_completed(futures):
            try:
                idx, page = fut.result()
                pages[idx] = page
                if page.error:
                    errors.append(page.error)
            except Cancelled:
                pass
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        if self.state == "cancelled":
            f.status = "cancelled"
            return
        good = [p for p in pages if p is not None]
        if not good:
            f.status, f.error = "failed", (errors[0] if errors else "No pages could be read")
            return
        try:
            f.outputs = self._write_outputs(f, good)
            f.status = "done"
            if errors:
                f.error = f"{len(errors)} page(s) could not be read"
        except PermissionError:
            f.status, f.error = "failed", "Could not save next to the file (is it open in Word, or read-only?)"
        except Exception as exc:  # noqa: BLE001
            f.status, f.error = "failed", f"Could not save output: {exc}"

    def _page(self, f: FileItem, index: int, tmp: Path) -> tuple[int, Page]:
        if self.state == "cancelled":
            raise Cancelled()
        if f.status == "queued":
            f.status = "running"
        try:
            page = self._read_page(f.path, index, tmp)
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad page must not sink the file
            page = Page(612, 792, 72, [], error=f"page {index + 1}: {exc}")
        with self._lock:
            f.done += 1
            self.done_pages += 1
        return index, page

    def _read_page(self, path: str, index: int, tmp: Path) -> Page:
        s = self.s
        first = BY_CODE.get(s.langs[0]) if s.langs else None
        ext = Path(path).suffix.lower()
        if ext in PDF_EXT:
            import pymupdf
            with pymupdf.open(path) as doc:
                pg = doc[index]
                digital = None
                if s.use_text_layer and has_usable_text_layer(pg):
                    digital = page_from_pdf_text(pg, first.rtl if first else False,
                                                 first.font if first else "Calibri")
                    if not _complex_script(pg.get_text("text")):
                        return digital
                gray_pix = pg.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY)
                gray = Image.frombytes("L", (gray_pix.width, gray_pix.height), gray_pix.samples)
                rgb_pix = pg.get_pixmap(dpi=150)
                color = Image.frombytes("RGB", (rgb_pix.width, rgb_pix.height), rgb_pix.samples)
                color = color.resize(gray.size)
            dpi = OCR_DPI
            if digital is not None:
                # Indic and Arabic-script PDFs often carry a text layer built
                # from legacy font encodings: valid Unicode, wrong letters. Keep
                # it only if it agrees with what OCR reads off the page.
                ocr = ocr_image(self.tess, gray, color, tmp=tmp, langs=s.langs,
                                quality=s.quality, auto_rotate=False, dpi=dpi,
                                model=s.model or None, clean=s.clean_paper)
                if _similar(page_text(digital), page_text(ocr)) >= 0.75:
                    return digital
                return ocr
        else:
            with Image.open(path) as im:
                im.seek(index)
                im = ImageOps.exif_transpose(im)
                color = im.convert("RGB")
                dpi = int((im.info.get("dpi") or (0, 0))[0] or 0)
            gray = color.convert("L")
            if not dpi or dpi < 100:
                dpi = _guess_dpi(*gray.size)
        return ocr_image(self.tess, gray, color, tmp=tmp, langs=s.langs, quality=s.quality,
                         auto_rotate=s.auto_rotate, dpi=dpi, model=s.model or None,
                         clean=s.clean_paper)

    def _write_outputs(self, f: FileItem, pages: list[Page]) -> list[str]:
        src = Path(f.path)
        base = src.with_name(src.stem + OUT_SUFFIX)
        written: list[str] = []
        if self.s.want_txt:
            dest = base.with_suffix(".txt")
            parts = []
            for i, p in enumerate(pages, 1):
                if len(pages) > 1:
                    parts.append(f"----- Page {i} -----")
                parts.append(page_text(p))
            text = "\n\n".join(parts).strip() + "\n"
            tmpf = dest.with_name(dest.name + ".part")
            tmpf.write_text(text, encoding="utf-8-sig")
            tmpf.replace(dest)
            written.append(str(dest))
        if self.s.want_docx:
            dest = base.with_suffix(".docx")
            write_docx(pages, dest)
            written.append(str(dest))
        return written


def _guess_dpi(w: int, h: int) -> int:
    """Resolution for images that do not record one.

    A page-shaped image is assumed to be an A4 sheet, which gets the physical
    page size (and so font sizes in Word) right for the usual scan or phone
    photo. Anything else is assumed to be a 300 dpi scan.
    """
    ratio = h / w if w else 0
    if 1.2 <= ratio <= 1.6:
        return int(min(600, max(100, w / 8.27)))
    if ratio and 1.2 <= 1 / ratio <= 1.6:
        return int(min(600, max(100, w / 11.69)))
    return 300


def _complex_script(text: str) -> bool:
    """True when the text has letters outside Latin and Cyrillic."""
    n = sum(1 for ch in text if ch.isalpha() and ord(ch) > 0x052F)
    return n >= 20


def _similar(a: str, b: str) -> float:
    import difflib

    a, b = "".join(a.split())[:2000], "".join(b.split())[:2000]
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
