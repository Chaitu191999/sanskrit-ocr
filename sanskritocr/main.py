"""Entry point: start Qt, show the manuscript welcome screen over the main window.

Reads Sanskrit only, with Tesseract's Devanagari script model, which read Sanskrit better
than Tesseract's own Sanskrit model in our tests (median character error 8.7% vs 11.3% on
312 printed lines) and needs no English model. Settings live in
%APPDATA%\\Sanskrit OCR\\settings.json; start-up and errors are logged to
%LOCALAPPDATA%\\Sanskrit OCR\\sanskrit.log.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import traceback
from pathlib import Path

APP_NAME = "Sanskrit OCR"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME
LOG_FILE = DATA_DIR / "sanskrit.log"
SETTINGS_FILE = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME / "settings.json"
DEFAULTS = {"txt": True, "docx": True, "quality": "fast", "rotate": True, "textLayer": True,
            "clean": True, "theme": "light"}
#: Always used, whatever is saved: Sanskrit, read with the Devanagari script model.
FIXED = {"langs": ["san"], "model": "script/Devanagari"}

log = logging.getLogger("sanskrit")


def _setup_logging() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_000_000:
            LOG_FILE.replace(LOG_FILE.with_suffix(".old.log"))
        h = logging.FileHandler(LOG_FILE, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    except OSError:
        pass


def _message(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10)


def _excepthook(t, v, tb) -> None:
    log.critical("unhandled error\n%s", "".join(traceback.format_exception(t, v, tb)))
    _message(f"{APP_NAME} hit an error:\n\n{v}\n\nDetails were saved to:\n{LOG_FILE}")


def _write_icon(path: Path) -> None:
    """The window icon, drawn by Qt the first time (so no picture has to be bundled)."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter

    from .ui.art import paint_mark

    img = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint_mark(p, QRectF(4, 4, 248, 248))
    p.end()
    img.save(str(path))


def main() -> None:
    _setup_logging()
    sys.excepthook = _excepthook
    try:   # taskbar groups the window under our own icon
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sanskrit.OCR")
    except Exception:
        pass

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication

    from ocrapp.api import Api

    from .ui import theme
    from .ui.window import MainWindow

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    theme.load_fonts()
    app.setFont(theme.font(15))

    api = Api(settings_file=SETTINGS_FILE, defaults=DEFAULTS, fixed=FIXED, old_settings_file=None)
    theme.use(api.init()["settings"].get("theme", "light"))
    app.setStyleSheet(theme.style_sheet())
    ico = theme.assets_dir() / "sanskrit.ico"
    if not ico.exists():
        ico = DATA_DIR / "icon.png"
        if not ico.exists():
            try:
                _write_icon(ico)
            except Exception:  # noqa: BLE001 - an icon is not worth failing over
                pass
    if ico.exists():
        app.setWindowIcon(QIcon(str(ico)))
    log.info("start: windows=%s qt=%s", sys.getwindowsversion(), app.platformName())

    preload = [a for a in sys.argv[1:] if not a.startswith("--")]   # files dropped on the exe icon
    if preload:
        api.add_paths(preload)
    win = MainWindow(api, autostart="--autostart" in sys.argv)
    win.show()
    code = app.exec()
    log.info("closed")
    sys.exit(code)


if __name__ == "__main__":
    main()
