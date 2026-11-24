"""Colours, fonts and the Qt style sheet for Sanskrit OCR.

Two palettes: "light" (palm-leaf and parchment, the default) and "dark" (lamp-lit). Widgets
read the current palette through `P` every time they paint, so switching is instant: call
`use(name)`, re-apply `style_sheet()` and repaint.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase


def assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


@dataclass(frozen=True)
class Palette:
    name: str
    dark: bool
    bg_top: str            # window background gradient
    bg_bottom: str
    surface: QColor        # cards
    solid: str             # popups, tooltips
    ink: str
    muted: str
    title: str             # headings
    line: QColor
    line_strong: QColor
    accent: str            # buttons, links, selection
    accent_hover: str
    accent_soft: QColor
    on_accent: str
    gold: str              # ornament only, never body text
    leaf: str              # tulsi green
    warn: str
    warn_soft: QColor
    stop: str
    stop_soft: QColor
    sunk: QColor           # hover wash
    well: QColor           # inset fields
    watermark: QColor      # the mandala behind the window
    shadow: QColor
    toast_bg: str
    toast_fg: str


LIGHT = Palette(
    name="light", dark=False,
    bg_top="#FAF4E8", bg_bottom="#F1E5CF",
    surface=QColor(255, 252, 245, 242), solid="#FFFBF3",
    ink="#2A1C12", muted="#76604B", title="#5B1D10",
    line=QColor(120, 78, 36, 40), line_strong=QColor(120, 78, 36, 82),
    accent="#A3401C", accent_hover="#86330F", accent_soft=QColor(163, 64, 28, 26), on_accent="#FFF8EC",
    gold="#B8862B", leaf="#4C6B2F",
    warn="#8A5A00", warn_soft=QColor(214, 150, 20, 40), stop="#A8261C", stop_soft=QColor(200, 50, 40, 30),
    sunk=QColor(120, 78, 36, 14), well=QColor(120, 78, 36, 12),
    watermark=QColor(160, 104, 36, 20), shadow=QColor(90, 50, 10, 26),
    toast_bg="#2E1F14", toast_fg="#FBF1DE",
)

DARK = Palette(
    name="dark", dark=True,
    bg_top="#1C140E", bg_bottom="#120C08",
    surface=QColor(39, 28, 20, 238), solid="#2A1E15",
    ink="#F3E6D0", muted="#BCA78B", title="#F4D49A",
    line=QColor(255, 214, 160, 30), line_strong=QColor(255, 214, 160, 64),
    accent="#E9A23B", accent_hover="#F4B861", accent_soft=QColor(233, 162, 59, 34), on_accent="#2A1606",
    gold="#D9A54A", leaf="#9DBB6C",
    warn="#F2C46B", warn_soft=QColor(242, 196, 107, 34), stop="#FF9C8C", stop_soft=QColor(255, 120, 100, 34),
    sunk=QColor(255, 214, 160, 14), well=QColor(0, 0, 0, 60),
    watermark=QColor(233, 170, 80, 16), shadow=QColor(0, 0, 0, 70),
    toast_bg="#F6E7CC", toast_fg="#22160C",
)

PALETTES = {"light": LIGHT, "dark": DARK}
P: Palette = LIGHT


def use(name: str) -> Palette:
    global P
    P = PALETTES.get(name, LIGHT)
    return P


SERIF = "Tiro Devanagari Sanskrit"   # Tiro Typeworks (SIL OFL): Devanagari made for Sanskrit, with Latin
SANS = "Hanken Grotesk"
DEVA = ["Tiro Devanagari Sanskrit", "Nirmala UI"]


def rgba(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha() / 255:.3f})"


def load_fonts() -> None:
    for f in sorted((assets_dir() / "fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(f))


def font(px: float, weight: int = 400, family: str = SANS, italic: bool = False) -> QFont:
    f = QFont(family)
    f.setPixelSize(round(px))
    f.setWeight(QFont.Weight(weight))
    f.setItalic(italic)
    if family == SANS:
        f.setFamilies([SANS, "Segoe UI", "Nirmala UI"])
    return f


def serif(px: float, italic: bool = False) -> QFont:
    f = QFont(SERIF)
    f.setFamilies([SERIF, "Nirmala UI"])
    f.setPixelSize(round(px))
    f.setItalic(italic)
    return f


def check_icon() -> Path:
    """The tick inside a checked box, in the colour that sits on the accent."""
    return assets_dir() / f"check-{P.name}.svg"


def style_sheet() -> str:
    p = P
    check = check_icon().as_posix()
    return f"""
* {{ outline: none; }}
QWidget {{ color: {p.ink}; }}   /* fonts come from QFont (app font + per-widget), not from here */
QToolTip {{ background: {p.solid}; color: {p.ink}; border: 1px solid {rgba(p.line_strong)}; padding: 4px 8px; }}

QPushButton {{ background: transparent; border: 1px solid {rgba(p.line_strong)}; border-radius: 8px;
              padding: 7px 13px; font-weight: 500; color: {p.ink}; }}
QPushButton:hover {{ border-color: {p.accent}; }}
QPushButton:focus {{ border-color: {p.accent}; }}
QPushButton:disabled {{ color: {p.muted}; }}
QPushButton[kind="quiet"] {{ border-color: transparent; color: {p.muted}; }}
QPushButton[kind="quiet"]:hover {{ color: {p.ink}; background: {rgba(p.sunk)}; }}
QPushButton[kind="quiet"]:disabled {{ color: {rgba(_fade(p.muted, .45))}; }}
QPushButton[kind="primary"] {{ background: {p.accent}; border-color: {p.accent}; color: {p.on_accent}; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[kind="primary"]:disabled {{ background: {rgba(_fade(p.accent, .38))};
              border-color: transparent; color: {rgba(_fade(p.on_accent, .75))}; }}

QCheckBox {{ spacing: 10px; font-size: 13px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1.5px solid {rgba(p.line_strong)}; border-radius: 4px;
                        background: {rgba(p.well)}; }}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; image: url("{check}"); }}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QListView {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {rgba(p.line_strong)}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.accent}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QLabel[role="title"] {{ color: {p.title}; }}
QLabel[role="label"] {{ color: {p.muted}; font-size: 13px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {p.muted}; }}
QLabel[role="small"] {{ color: {p.muted}; font-size: 13px; }}
QLabel[role="tiny"] {{ color: {p.muted}; font-size: 12px; }}
QLabel[role="accent"] {{ color: {p.accent}; }}

#toast {{ background: {p.toast_bg}; color: {p.toast_fg}; padding: 9px 16px; border-radius: 8px; font-size: 14px; }}
"""


def _fade(hex_colour: str, alpha: float) -> QColor:
    c = QColor(hex_colour)
    c.setAlphaF(alpha)
    return c
