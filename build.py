"""Build Sanskrit OCR for Windows: stage Tesseract and the two models it uses, then PyInstaller.

    python build.py --fetch-models    # download the models into build_assets/tessdata (once)
    python build.py                   # -> dist\\Sanskrit OCR\\Sanskrit OCR.exe

Needs, next to this file:
    build_assets/tesseract/           tesseract.exe and its DLLs (Tesseract 5.x for Windows)
    build_assets/tessdata/{fast,best}/osd.traineddata
    build_assets/tessdata/{fast,best}/script/Devanagari.traineddata

The result is a self-contained folder (no installer, no internet, no graphics card needed).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "build_assets"
STAGE = HERE / "build" / "stage"
NAME = "Sanskrit OCR"
MODELS = ["osd.traineddata", "script/Devanagari.traineddata"]
MODEL_URL = "https://github.com/tesseract-ocr/tessdata_{quality}/raw/main/{model}"

#: Qt pieces the interface does not use (it is plain Qt Widgets drawn in software).
QT_UNUSED = ["PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL",
             "PySide6.QtOpenGLWidgets", "PySide6.QtDBus", "PySide6.QtPdf", "PySide6.QtConcurrent",
             "PySide6.QtXml", "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtPrintSupport",
             "PySide6.QtUiTools", "PySide6.QtHelp", "PySide6.QtDesigner"]
#: Files PyInstaller's Qt hook collects that a software-drawn Widgets app never loads.
QT_PRUNE = ["opengl32sw.dll", "Qt6Pdf.dll", "Qt6Network.dll", "Qt6Qml*.dll", "Qt6Quick*.dll",
            "Qt6OpenGL*.dll", "Qt6VirtualKeyboard*.dll", "translations"]


def fetch_models() -> None:
    for quality in ("fast", "best"):
        for model in MODELS:
            dest = ASSETS / "tessdata" / quality / model
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            url = MODEL_URL.format(quality=quality, model=model)
            print(f"downloading {url}")
            urllib.request.urlretrieve(url, dest)


def make_icon(dest: Path) -> None:
    """The app's mark (maroon tile, gold सं), drawn by its own Qt code."""
    png = dest.with_suffix(".png")
    code = ("import sys; sys.path.insert(0, sys.argv[1]);"
            "from PySide6.QtCore import QRectF, Qt;"
            "from PySide6.QtGui import QGuiApplication, QImage, QPainter;"
            "app = QGuiApplication([]);"
            "from sanskritocr.ui import theme, art; theme.load_fonts();"
            "img = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied); img.fill(Qt.GlobalColor.transparent);"
            "p = QPainter(img); art.paint_mark(p, QRectF(4, 4, 248, 248)); p.end(); img.save(sys.argv[2])")
    subprocess.run([sys.executable, "-c", code, str(HERE), str(png)], check=True,
                   env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    from PIL import Image
    Image.open(png).save(dest, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def stage() -> None:
    missing = [p for p in [ASSETS / "tesseract" / "tesseract.exe"] +
               [ASSETS / "tessdata" / q / m for q in ("fast", "best") for m in MODELS] if not p.exists()]
    if missing:
        sys.exit("Missing:\n  " + "\n  ".join(str(p) for p in missing) +
                 "\nSee the README (Build from source). Models: python build.py --fetch-models")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    shutil.copytree(ASSETS / "tesseract", STAGE / "tesseract", ignore=shutil.ignore_patterns("tessdata"))
    for quality in ("fast", "best"):
        for m in MODELS:
            dst = STAGE / "tessdata" / quality / m
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ASSETS / "tessdata" / quality / m, dst)
    make_icon(STAGE / "sanskrit.ico")
    shutil.copy2(STAGE / "sanskrit.ico", HERE / "sanskritocr" / "assets" / "sanskrit.ico")


def build() -> Path:
    args = [
        sys.executable, "-m", "PyInstaller", str(HERE / "run_sanskrit.py"),
        "--name", NAME, "--noconfirm", "--clean", "--windowed",
        "--icon", str(STAGE / "sanskrit.ico"),
        "--add-data", f"{HERE / 'sanskritocr' / 'assets'};assets",
        *[a for m in ["tkinter", "pymupdf4llm", "pymupdf_layout", "onnxruntime", *QT_UNUSED]
          for a in ("--exclude-module", m)],
        "--distpath", str(HERE / "dist"), "--workpath", str(HERE / "build" / "pyi"),
        "--specpath", str(HERE / "build"),
    ]
    subprocess.run(args, check=True)
    # Tesseract and its models are copied in afterwards: given to PyInstaller as data, it would
    # scan tesseract.exe and put a second copy of every Tesseract DLL next to Python (~60 MB).
    internal = HERE / "dist" / NAME / "_internal"
    shutil.copytree(STAGE / "tesseract", internal / "tesseract")
    shutil.copytree(STAGE / "tessdata", internal / "tessdata")
    for pattern in QT_PRUNE:
        for f in (internal / "PySide6").rglob(pattern):
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    return HERE / "dist" / NAME / f"{NAME}.exe"


if __name__ == "__main__":
    if "--fetch-models" in sys.argv:
        fetch_models()
        sys.exit(0)
    stage()
    exe = build()
    total = sum(p.stat().st_size for p in exe.parent.rglob("*") if p.is_file())
    print(f"\nBuilt {exe}  ({total / 1e6:.0f} MB folder)")
