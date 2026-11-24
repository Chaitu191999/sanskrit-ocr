"""Procedural art for Sanskrit OCR's welcome screen. Nothing here is a bundled picture.

The scene: a palm-leaf manuscript (pothi) between lacquered wooden covers, tied with a cord,
resting on a red silk cloth; beside it a clay lamp on a brass plate, a stone mortar and pestle
(khalva) with herb paste, sprigs of tulsi and amla fruit; a gold lotus mandala behind.

The manuscript is a small 3D model (boxes in world units) seen from above at an angle. Its
faces are flat textures painted once with QPainter and mapped onto the screen with
perspective (QTransform.quadToQuad), so the cover can swing open on its hinge.
"""
from __future__ import annotations

import functools
import math
import random
import unicodedata

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient, QTransform)

from . import theme

# -- words ---------------------------------------------------------------------------------------------
#: Written on the top leaf: the opening of the Charaka Saṃhitā (Sūtrasthāna 1.1-2), the opening
#: verse of the Aṣṭāṅga Hṛdaya, and Charaka's statement of what Ayurveda is for (Sū. 30.26).
LEAF_TEXT = ("॥ श्रीः ॥ अथातो दीर्घञ्जीवितीयमध्यायं व्याख्यास्यामः ॥ इति ह स्माह भगवानात्रेयः ॥ "
             "रागादिरोगान् सततानुषक्तानशेषकायप्रसृतानशेषान् । औत्सुक्यमोहारतिदाञ्जघान "
             "योऽपूर्ववैद्याय नमोऽस्तु तस्मै ॥ प्रयोजनं चास्य स्वस्थस्य स्वास्थ्यरक्षणमातुरस्य "
             "विकारप्रशमनं च ॥ ")
COVER_TITLE = "आयुर्वेदः"
VERSE = "स्वस्थस्य स्वास्थ्यरक्षणम् आतुरस्य विकारप्रशमनं च"
VERSE_EN = "“To keep the healthy in health, and to heal the sick.”   Charaka Saṃhitā"

GOLD = QColor("#D9A54A")
GOLD_LIGHT = QColor("#F2CC7A")
_VIRAMA = "्"


def aksharas(text: str) -> list[str]:
    """Split Devanagari into written syllables: a consonant cluster with its vowel signs."""
    out: list[str] = []
    cur = ""
    for ch in text:
        if ch.isspace():
            if cur:
                out.append(cur)
            out.append(" ")
            cur = ""
            continue
        joins = unicodedata.category(ch) in ("Mn", "Mc") or ch in "‌‍" or cur.endswith(_VIRAMA)
        if joins and cur:
            cur += ch
        else:
            if cur:
                out.append(cur)
            cur = ch
    if cur:
        out.append(cur)
    return out


# -- small helpers ----------------------------------------------------------------------------------------
def _image(w: float, h: float) -> QImage:
    im = QImage(max(1, int(w)), max(1, int(h)), QImage.Format.Format_ARGB32_Premultiplied)
    im.fill(Qt.GlobalColor.transparent)
    return im


def _c(hex_or_rgb, a: int | None = None) -> QColor:
    c = QColor(hex_or_rgb) if isinstance(hex_or_rgb, str) else QColor(*hex_or_rgb)
    if a is not None:
        c.setAlpha(a)
    return c


def radial_sprite(diameter: float, stops: list[tuple[float, QColor]], dpr: float = 1.0) -> QPixmap:
    px = QPixmap(max(1, int(diameter * dpr)), max(1, int(diameter * dpr)))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    g = QRadialGradient(QPointF(diameter / 2, diameter / 2), diameter / 2)
    for at, c in stops:
        g.setColorAt(at, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QRectF(0, 0, diameter, diameter))
    p.end()
    return px


def blur(img: QImage, factor: int = 6) -> QImage:
    """A cheap soft blur: shrink, then smooth-scale back up."""
    small = img.scaled(max(1, img.width() // factor), max(1, img.height() // factor),
                       Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return small.scaled(img.width(), img.height(), Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)


def draw_on_quad(p: QPainter, img: QImage, quad: list[QPointF]) -> None:
    """Draw an image onto any four screen points (TL, TR, BR, BL) with perspective."""
    w, h = img.width(), img.height()
    src = QPolygonF([QPointF(0, 0), QPointF(w, 0), QPointF(w, h), QPointF(0, h)])
    tr = QTransform()
    if QTransform.quadToQuad(src, QPolygonF(quad), tr):
        p.save()
        p.setTransform(tr, True)
        p.drawImage(0, 0, img)
        p.restore()


# -- the view ---------------------------------------------------------------------------------------------
class View:
    """World (x right, y away from the viewer, z up) to screen, looking down at `elev` degrees."""

    def __init__(self, cx: float, cy: float, scale: float, elev: float = 56.0, focal: float = 1800.0):
        e = math.radians(elev)
        self.cx, self.cy, self.s, self.f = cx, cy, scale, focal
        self.se, self.ce = math.sin(e), math.cos(e)
        self.cam = (0.0, -focal * self.ce, focal * self.se)

    def k(self, y: float, z: float = 0.0) -> float:
        return self.f / (self.f + y * self.ce - z * self.se) * self.s

    def pt(self, x: float, y: float, z: float = 0.0) -> QPointF:
        k = self.k(y, z)
        return QPointF(self.cx + x * k, self.cy - (y * self.se + z * self.ce) * k)

    def faces_camera(self, point: tuple, normal: tuple) -> bool:
        c = self.cam
        return sum((c[i] - point[i]) * normal[i] for i in range(3)) > 0


# -- the manuscript ------------------------------------------------------------------------------------
L, D = 600.0, 110.0           # covers: length, width (world units = px at scale 1)
CT, LT = 8.0, 30.0            # cover thickness, stack of leaves
IX, IY = 7.0, 5.0             # leaves sit this far inside the covers
LL, LD = L - 2 * IX, D - 2 * IY
Z_LEAF = CT + LT              # top of the leaves
HOLE_X = 180.0                # binding holes at +-HOLE_X
CORD_X = (100.0, 108.0, 116.0)
TS = 2.0                      # texture pixels per world unit


def _grain(p: QPainter, w: float, h: float, rnd: random.Random, n: int, colour: QColor, lo: int, hi: int) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    for _ in range(n):
        y = rnd.uniform(1, h - 1)
        x0, ln, wob = rnd.uniform(-60, w), rnd.uniform(60, 320), rnd.uniform(-1.4, 1.4)
        c = QColor(colour)
        c.setAlpha(rnd.randint(lo, hi))
        p.setPen(QPen(c, rnd.uniform(0.3, 1.1)))
        path = QPainterPath(QPointF(x0, y))
        path.cubicTo(x0 + ln * .33, y + wob, x0 + ln * .66, y - wob, x0 + ln, y + wob * .5)
        p.drawPath(path)


def _vine(p: QPainter, x0: float, x1: float, cy: float, amp: float, colour: QColor) -> None:
    period = 52.0
    path = QPainterPath(QPointF(x0, cy))
    steps = max(8, int((x1 - x0) / 2))
    for i in range(1, steps + 1):
        x = x0 + (x1 - x0) * i / steps
        path.lineTo(x, cy + amp * math.sin(2 * math.pi * (x - x0) / period))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(colour, 1.1))
    p.drawPath(path)
    leaf = QColor(colour)
    leaf.setAlpha(210)
    x = x0 + period / 4
    side = 1
    while x < x1 - 6:
        y = cy + amp * math.sin(2 * math.pi * (x - x0) / period)
        p.save()
        p.translate(x, y)
        p.rotate(-35 * side)
        lp = QPainterPath(QPointF(0, 0))
        lp.cubicTo(3, -5 * side, 9, -6 * side, 13, -1 * side)
        lp.cubicTo(8, 1 * side, 3, 1.5 * side, 0, 0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(leaf)
        p.drawPath(lp)
        p.restore()
        p.setBrush(leaf)
        p.drawEllipse(QPointF(x + period / 4, cy), 1.6, 1.6)
        x += period / 2
        side = -side


def _lotus_motif(p: QPainter, c: QPointF, size: float, colour: QColor) -> None:
    p.save()
    p.translate(c)
    p.setPen(QPen(colour, 0.9))
    p.setBrush(_c(colour.name(), 70))
    for ang in (-50, 0, 50):
        p.save()
        p.rotate(ang)
        path = QPainterPath(QPointF(0, 0))
        path.cubicTo(-size * .45, -size * .4, -size * .25, -size * .9, 0, -size)
        path.cubicTo(size * .25, -size * .9, size * .45, -size * .4, 0, 0)
        p.drawPath(path)
        p.restore()
    p.restore()


def cover_texture() -> QImage:
    im = _image(L * TS, D * TS)
    p = QPainter(im)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    p.scale(TS, TS)
    r = QRectF(0, 0, L, D)
    body = QPainterPath()
    body.addRoundedRect(r, 5, 5)
    g = QLinearGradient(0, 0, 0, D)
    g.setColorAt(0, _c("#9A321E"))
    g.setColorAt(0.55, _c("#7E2516"))
    g.setColorAt(1, _c("#5C190E"))
    p.fillPath(body, g)
    p.setClipPath(body)
    _grain(p, L, D, random.Random(11), 150, QColor(30, 6, 2), 10, 38)
    sheen = QLinearGradient(0, 0, 0, D)
    sheen.setColorAt(0, QColor(255, 210, 160, 46))
    sheen.setColorAt(0.3, QColor(255, 210, 160, 0))
    p.fillPath(body, sheen)
    p.setClipping(False)
    # gilded border, a dotted channel between two rules
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(GOLD, 1.5))
    p.drawRoundedRect(r.adjusted(5, 5, -5, -5), 3, 3)
    p.setPen(QPen(GOLD, 0.7))
    p.drawRoundedRect(r.adjusted(11, 11, -11, -11), 2, 2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(GOLD.name(), 200))
    x = 14.0
    while x < L - 12:
        p.drawEllipse(QPointF(x, 8), 0.8, 0.8)
        p.drawEllipse(QPointF(x, D - 8), 0.8, 0.8)
        x += 6
    # cartouche with the title
    cw, ch = 176.0, 62.0
    cr = QRectF(L / 2 - cw / 2, D / 2 - ch / 2, cw, ch)
    p.setPen(QPen(GOLD, 1.4))
    p.setBrush(_c("#4A1009"))
    p.drawRoundedRect(cr, 12, 12)
    p.setPen(QPen(GOLD, 0.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(cr.adjusted(4, 4, -4, -4), 9, 9)
    for sx in (-1, 1):
        p.save()
        p.translate(L / 2 + sx * (cw / 2 + 4), D / 2)
        p.rotate(90 * sx)
        _lotus_motif(p, QPointF(0, 0), 12, GOLD)
        p.restore()
    p.save()
    p.resetTransform()
    p.setFont(_serif_px(29 * TS))
    p.setPen(GOLD_LIGHT)
    p.drawText(QRectF(cr.x() * TS, cr.y() * TS + 2 * TS, cr.width() * TS, cr.height() * TS),
               Qt.AlignmentFlag.AlignCenter, COVER_TITLE)
    p.restore()
    # vines in the side panels, brass-ringed binding holes on top of them
    _vine(p, 20, L / 2 - cw / 2 - 26, D / 2, 13, GOLD)
    _vine(p, L / 2 + cw / 2 + 26, L - 20, D / 2, 13, GOLD)
    for hx in (L / 2 - HOLE_X, L / 2 + HOLE_X):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c("#5C190E"))
        p.drawEllipse(QPointF(hx, D / 2), 13, 13)
        rg = QRadialGradient(QPointF(hx - 2, D / 2 - 2), 10)
        rg.setColorAt(0, _c("#F6D489"))
        rg.setColorAt(0.6, _c("#B98A34"))
        rg.setColorAt(1, _c("#6E4A12"))
        p.setBrush(rg)
        p.drawEllipse(QPointF(hx, D / 2), 8.5, 8.5)
        p.setBrush(_c("#1E0A04"))
        p.drawEllipse(QPointF(hx, D / 2), 4.2, 4.2)
    p.end()
    return im


@functools.lru_cache(maxsize=1)
def cover_image() -> QImage:
    """The cover, made once and shared by the welcome screen and the drop zone."""
    return cover_texture()


def inner_texture() -> QImage:
    im = _image(L * TS / 2, D * TS / 2)
    p = QPainter(im)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(TS / 2, TS / 2)
    body = QPainterPath()
    body.addRoundedRect(QRectF(0, 0, L, D), 5, 5)
    g = QLinearGradient(0, 0, 0, D)
    g.setColorAt(0, _c("#875230"))
    g.setColorAt(1, _c("#5A3119"))
    p.fillPath(body, g)
    p.setClipPath(body)
    _grain(p, L, D, random.Random(5), 120, QColor(40, 18, 6), 18, 60)
    p.end()
    return im


def _serif_px(px: float) -> QFont:
    f = QFont(theme.SERIF)
    f.setFamilies([theme.SERIF, "Nirmala UI"])
    f.setPixelSize(max(1, int(round(px))))
    return f


def leaf_layout() -> list[tuple[str, float, float]]:
    """(akshara, centre x, baseline y) in leaf units, filling 5 lines around the binding holes."""
    fm = QFontMetricsF(_serif_px(12.5 * TS))
    stream = aksharas(LEAF_TEXT)
    h1, h2 = LL / 2 - HOLE_X, LL / 2 + HOLE_X
    segments = [(30.0, h1 - 18), (h1 + 18, h2 - 18), (h2 + 18, LL - 30.0)]
    out, i = [], 0
    for line in range(5):
        base = 22.0 + line * 17.5
        for a, b in segments:
            x = a
            while True:
                s = stream[i % len(stream)]
                wpx = fm.horizontalAdvance(s) / TS
                if x + wpx > b:
                    break
                if s != " ":
                    out.append((s, x + wpx / 2, base))
                x += wpx
                i += 1
    return out


def _leaf_shape() -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, LL, LD), 16, 16)
    return path


def leaf_texture(layout) -> QImage:
    im = _image(LL * TS, LD * TS)
    p = QPainter(im)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    p.scale(TS, TS)
    shape = _leaf_shape()
    g = QLinearGradient(0, 0, 0, LD)
    g.setColorAt(0, _c("#D9BC82"))
    g.setColorAt(0.5, _c("#EEDBAA"))
    g.setColorAt(1, _c("#D5B67A"))
    p.fillPath(shape, g)
    p.setClipPath(shape)
    rnd = random.Random(3)
    for _ in range(240):   # fibres run the length of the leaf
        y = rnd.uniform(0, LD)
        c = QColor(120, 84, 30, rnd.randint(8, 30)) if rnd.random() < 0.6 else QColor(255, 246, 214, rnd.randint(14, 40))
        p.setPen(QPen(c, rnd.uniform(0.25, 0.8)))
        p.drawLine(QPointF(rnd.uniform(-20, LL * 0.4), y), QPointF(rnd.uniform(LL * 0.6, LL + 20), y + rnd.uniform(-.6, .6)))
    ends = QLinearGradient(0, 0, LL, 0)
    ends.setColorAt(0, QColor(110, 70, 20, 70))
    ends.setColorAt(0.06, QColor(110, 70, 20, 0))
    ends.setColorAt(0.94, QColor(110, 70, 20, 0))
    ends.setColorAt(1, QColor(110, 70, 20, 70))
    p.fillPath(shape, ends)
    ink = QColor(43, 24, 10, 120)
    p.setPen(QPen(ink, 0.6))
    for x in (22.0, 25.0, LL - 25.0, LL - 22.0):
        p.drawLine(QPointF(x, 8), QPointF(x, LD - 8))
    for hx in (LL / 2 - HOLE_X, LL / 2 + HOLE_X):
        p.setPen(QPen(QColor(120, 80, 30, 120), 0.8))
        p.setBrush(_c("#24110A"))
        p.drawEllipse(QPointF(hx, LD / 2), 4.4, 4.4)
    p.setClipping(False)
    p.resetTransform()
    p.setFont(_serif_px(12.5 * TS))
    p.setPen(QColor(40, 22, 10, 228))
    fm = QFontMetricsF(p.font())
    for s, cx, base in layout:
        p.drawText(QPointF((cx * TS) - fm.horizontalAdvance(s) / 2, base * TS), s)
    p.end()
    return im


def leaf_glow_texture(layout) -> QImage:
    """The same writing as light: a soft gold halo with bright letters on top."""
    im = _image(LL * TS, LD * TS)
    p = QPainter(im)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    p.setFont(_serif_px(12.5 * TS))
    fm = QFontMetricsF(p.font())
    p.setPen(QColor(255, 178, 70, 255))
    for s, cx, base in layout:
        p.drawText(QPointF((cx * TS) - fm.horizontalAdvance(s) / 2, base * TS), s)
    p.end()
    halo = blur(im, 5)
    out = _image(LL * TS, LD * TS)
    p = QPainter(out)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    wash = QRadialGradient(QPointF(LL * TS / 2, LD * TS / 2), LL * TS * 0.55)
    wash.setColorAt(0, QColor(255, 200, 110, 90))
    wash.setColorAt(1, QColor(255, 170, 60, 0))
    p.fillRect(out.rect(), wash)
    p.drawImage(0, 0, halo)
    p.drawImage(0, 0, halo)
    p.setFont(_serif_px(12.5 * TS))
    p.setPen(QColor(255, 246, 220))
    for s, cx, base in layout:
        p.drawText(QPointF((cx * TS) - fm.horizontalAdvance(s) / 2, base * TS), s)
    p.end()
    return out


def leaves_edge_texture() -> QImage:
    im = _image(LL * TS / 2, LT * TS)
    p = QPainter(im)
    w, h = im.width(), im.height()
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, _c("#C9A869"))
    g.setColorAt(1, _c("#9E7E45"))
    p.fillRect(im.rect(), g)
    rnd = random.Random(8)
    y = 0.0
    while y < h:
        p.setPen(QPen(QColor(250, 232, 190, rnd.randint(60, 140)), 1.0))
        wob = rnd.uniform(-0.8, 0.8)
        p.drawLine(QPointF(0, y + wob), QPointF(w, y - wob))
        p.setPen(QPen(QColor(70, 44, 14, rnd.randint(70, 140)), 0.7))
        p.drawLine(QPointF(0, y + 1.3), QPointF(w, y + 1.3 + wob))
        y += rnd.uniform(2.0, 2.8)
    ends = QLinearGradient(0, 0, w, 0)
    ends.setColorAt(0, QColor(60, 36, 10, 120))
    ends.setColorAt(0.05, QColor(60, 36, 10, 0))
    ends.setColorAt(0.95, QColor(60, 36, 10, 0))
    ends.setColorAt(1, QColor(60, 36, 10, 120))
    p.fillRect(im.rect(), ends)
    p.end()
    return im


class Pothi:
    """The manuscript: textures made once, drawn for any opening angle.

    Only what the closed manuscript shows is made up front; the leaf and its writing are
    made by prepare(), which the welcome screen calls once it is on screen.
    """

    def __init__(self):
        self.cover = cover_image()
        self.edge = leaves_edge_texture()
        self.layout: list | None = None
        self.leaf = self.glow = self.inner = None

    def prepare(self) -> None:
        if self.layout is None:
            self.layout = leaf_layout()
            self.inner = inner_texture()
            self.leaf = leaf_texture(self.layout)
            self.glow = leaf_glow_texture(self.layout)

    # world corners of the leaves' top, as the texture maps them (far-left first)
    @staticmethod
    def leaf_quad(v: View) -> list[QPointF]:
        x0, x1, y0, y1 = -LL / 2, LL / 2, -LD / 2, LD / 2
        return [v.pt(x0, y1, Z_LEAF), v.pt(x1, y1, Z_LEAF), v.pt(x1, y0, Z_LEAF), v.pt(x0, y0, Z_LEAF)]

    @staticmethod
    def leaf_point(v: View, lx: float, ly: float) -> QPointF:
        """A point on the top leaf given in leaf texture units."""
        return v.pt(-LL / 2 + lx, LD / 2 - ly, Z_LEAF)

    def bounds(self, v: View) -> QRectF:
        pts = [v.pt(x, y, z) for x in (-L / 2, L / 2) for y in (-D / 2, D / 2) for z in (0, Z_LEAF + CT)]
        poly = QPolygonF(pts)
        return poly.boundingRect()

    def _box_face(self, p: QPainter, pts: list[QPointF], top: QColor, bottom: QColor, line: QColor | None = None):
        path = QPainterPath(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        path.closeSubpath()
        ys = [q.y() for q in pts]
        g = QLinearGradient(0, min(ys), 0, max(ys))
        g.setColorAt(0, top)
        g.setColorAt(1, bottom)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(path, g)
        if line is not None:
            p.setPen(QPen(line, 0.8))
            p.drawLine(pts[0], pts[1])

    def paint(self, p: QPainter, v: View, open_deg: float = 0.0, cord: float = 1.0, glow: float = 0.0) -> None:
        p.save()
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        hx, hy = L / 2, D / 2
        # bottom cover: top (mostly hidden under the leaves) and front edge
        self._box_face(p, [v.pt(-hx, hy, CT), v.pt(hx, hy, CT), v.pt(hx, -hy, CT), v.pt(-hx, -hy, CT)],
                       _c("#7A2415"), _c("#6A1E12"))
        self._box_face(p, [v.pt(-hx, -hy, CT), v.pt(hx, -hy, CT), v.pt(hx, -hy, 0), v.pt(-hx, -hy, 0)],
                       _c("#6E2013"), _c("#3E0F08"), GOLD)
        # leaves: front edge, then the top leaf
        lx, ly = LL / 2, LD / 2
        draw_on_quad(p, self.edge, [v.pt(-lx, -ly, Z_LEAF), v.pt(lx, -ly, Z_LEAF), v.pt(lx, -ly, CT), v.pt(-lx, -ly, CT)])
        quad = self.leaf_quad(v)
        if open_deg > 0:
            self.prepare()
            draw_on_quad(p, self.leaf, quad)
        if glow > 0 and self.glow is not None:
            p.save()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            p.setOpacity(min(1.0, glow))
            draw_on_quad(p, self.glow, quad)
            p.restore()
        # top cover on its hinge (the far edge of the leaves)
        self._paint_cover(p, v, open_deg)
        if cord > 0 and open_deg < 1:
            self._paint_cord(p, v, cord)
        p.restore()

    def _paint_cover(self, p: QPainter, v: View, deg: float) -> None:
        th = math.radians(deg)
        st, ctt = math.sin(th), math.cos(th)
        hy = D / 2

        def w(x, dy, dz):     # hinge-local -> world
            return (x, hy + dy * ctt + dz * st, Z_LEAF + (-dy * st + dz * ctt))

        def P(c):
            return v.pt(*c)

        x0, x1 = -L / 2, L / 2
        top = [w(x0, 0, CT), w(x1, 0, CT), w(x1, -D, CT), w(x0, -D, CT)]        # far-left first
        bottom = [w(x0, -D, 0), w(x1, -D, 0), w(x1, 0, 0), w(x0, 0, 0)]
        front = [w(x0, -D, CT), w(x1, -D, CT), w(x1, -D, 0), w(x0, -D, 0)]
        back = [w(x0, 0, 0), w(x1, 0, 0), w(x1, 0, CT), w(x0, 0, CT)]
        n_top = (0.0, st, ctt)
        n_front = (0.0, -ctt, st)
        faces = []
        if v.faces_camera(top[0], n_front):
            faces.append(("front", front))
        else:
            faces.append(("back", back))
        if v.faces_camera(top[0], n_top):
            faces.append(("top", top))
        else:
            faces.append(("bottom", bottom))
        for kind, pts in faces:
            q = [P(c) for c in pts]
            if kind == "top":
                draw_on_quad(p, self.cover, q)
                if 0 < deg:
                    shade = min(0.35, deg / 160)          # the lid darkens as it turns from the lamp
                    p.save()
                    p.setOpacity(shade)
                    path = QPainterPath(q[0])
                    for qq in q[1:]:
                        path.lineTo(qq)
                    p.fillPath(path, QColor(20, 4, 0))
                    p.restore()
            elif kind == "bottom":
                self.prepare()
                draw_on_quad(p, self.inner, q)
            else:
                self._box_face(p, q, _c("#702114"), _c("#430F08"), GOLD)

    def _paint_cord(self, p: QPainter, v: View, alpha: float) -> None:
        hy, ztop = D / 2, Z_LEAF + CT
        p.save()
        p.setOpacity(alpha)
        for i, x in enumerate(CORD_X):
            path = QPainterPath(v.pt(x - 1.5, hy, ztop))
            path.lineTo(v.pt(x, -hy, ztop))
            path.lineTo(v.pt(x + .6, -hy, 0.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_c("#4A0E0A"), 4.4 * v.s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(_c("#B23A2C"), 3.0 * v.s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(QColor(255, 190, 160, 90), 1.0 * v.s))
            p.drawPath(path)
        # knot on the front edge and the tasselled tail lying on the cloth
        knot = v.pt(CORD_X[1], -hy, ztop * 0.55)
        tail = QPainterPath(knot)
        end = v.pt(CORD_X[1] + 46, -hy - 58, 0)
        tail.cubicTo(v.pt(CORD_X[1] + 6, -hy - 6, 6), v.pt(CORD_X[1] + 40, -hy - 30, 0), end)
        p.setPen(QPen(_c("#4A0E0A"), 4.0 * v.s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(tail)
        p.setPen(QPen(_c("#B23A2C"), 2.6 * v.s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(tail)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c("#8E2219"))
        p.drawEllipse(knot, 5.5 * v.s, 4.5 * v.s)
        # tassel: gold bead, red threads
        p.setBrush(GOLD)
        p.drawEllipse(end, 4 * v.s, 3.4 * v.s)
        p.setPen(QPen(_c("#C0412F"), 1.1 * v.s))
        for j in range(-4, 5):
            p.drawLine(end, QPointF(end.x() + 4 * v.s + j * 1.6 * v.s, end.y() + 16 * v.s - abs(j) * 0.8 * v.s))
        p.restore()


# -- the cloth ----------------------------------------------------------------------------------------
CLOTH_X, CLOTH_Y0, CLOTH_Y1 = 400.0, -150.0, 160.0


def cloth_texture(ts: float = 1.3) -> QImage:
    w, h = 2 * CLOTH_X, CLOTH_Y1 - CLOTH_Y0
    im = _image(w * ts, h * ts)
    p = QPainter(im)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(ts, ts)
    g = QRadialGradient(QPointF(w / 2, h * 0.45), w * 0.6)
    g.setColorAt(0, _c("#98222A"))
    g.setColorAt(0.7, _c("#741820"))
    g.setColorAt(1, _c("#560F16"))
    p.fillRect(QRectF(0, 0, w, h), g)
    # folds: soft diagonal light and shade
    rnd = random.Random(21)
    for _ in range(7):
        x = rnd.uniform(-100, w)
        wid = rnd.uniform(30, 90)
        band = QLinearGradient(x, 0, x + wid, wid * 0.35)
        light = rnd.random() < 0.5
        c = QColor(255, 190, 180, 11) if light else QColor(30, 0, 4, 40)
        band.setColorAt(0, QColor(c.red(), c.green(), c.blue(), 0))
        band.setColorAt(0.5, c)
        band.setColorAt(1, QColor(c.red(), c.green(), c.blue(), 0))
        p.fillRect(QRectF(0, 0, w, h), band)
    # small woven gold flowers (buti)
    p.setPen(Qt.PenStyle.NoPen)
    for row, y in enumerate(range(44, int(h) - 36, 34)):
        for x in range(46 + (row % 2) * 22, int(w) - 40, 44):
            p.setBrush(QColor(226, 168, 80, 70))
            for a in range(4):
                ang = a * math.pi / 2
                p.drawEllipse(QPointF(x + 2.6 * math.cos(ang), y + 2.6 * math.sin(ang)), 1.6, 1.6)
            p.setBrush(QColor(255, 214, 140, 90))
            p.drawEllipse(QPointF(x, y), 1.1, 1.1)
    # zari border
    outer, inner = QRectF(10, 10, w - 20, h - 20), QRectF(30, 30, w - 60, h - 60)
    band = QPainterPath()
    band.addRect(outer)
    band.addRect(inner)
    band.setFillRule(Qt.FillRule.OddEvenFill)
    p.fillPath(band, _c("#5A0E14"))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(GOLD, 1.6))
    p.drawRect(outer)
    p.drawRect(inner)
    p.setPen(QPen(_c(GOLD.name(), 170), 0.9))
    p.drawRect(outer.adjusted(4, 4, -4, -4))
    p.drawRect(inner.adjusted(-4, -4, 4, 4))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(GOLD.name(), 190))

    def chevrons(x0, y0, x1, y1):
        n = int(math.hypot(x1 - x0, y1 - y0) / 9)
        for i in range(n):
            t = (i + 0.5) / n
            cx, cy = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            p.drawPolygon(QPolygonF([QPointF(cx, cy - 3), QPointF(cx + 3, cy), QPointF(cx, cy + 3), QPointF(cx - 3, cy)]))

    chevrons(20, 20, w - 20, 20)
    chevrons(20, h - 20, w - 20, h - 20)
    chevrons(20, 20, 20, h - 20)
    chevrons(w - 20, 20, w - 20, h - 20)
    p.end()
    return im


def paint_cloth(p: QPainter, v: View, tex: QImage) -> None:
    x0, x1, y0, y1 = -CLOTH_X, CLOTH_X, CLOTH_Y0, CLOTH_Y1
    p.save()
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    draw_on_quad(p, tex, [v.pt(x0, y1), v.pt(x1, y1), v.pt(x1, y0), v.pt(x0, y0)])
    rnd = random.Random(4)                     # gold fringe along the front edge
    x = x0 + 4
    while x < x1 - 2:
        a = v.pt(x, y0)
        b = v.pt(x + rnd.uniform(-2, 2), y0 - rnd.uniform(9, 14))
        p.setPen(QPen(QColor(222, 170, 80, 200), 0.9 * v.s))
        p.drawLine(a, b)
        x += 4.5
    p.restore()


# -- still life -----------------------------------------------------------------------------------------
def paint_ground_shadow(p: QPainter, c: QPointF, rx: float, ry: float, alpha: int = 150) -> None:
    g = QRadialGradient(c, 1.0)
    g.setColorAt(0, QColor(10, 3, 0, alpha))
    g.setColorAt(1, QColor(10, 3, 0, 0))
    p.save()
    p.translate(c)
    p.scale(rx, ry)
    p.translate(-c)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(c, 1.0, 1.0)
    p.restore()


def paint_plate(p: QPainter, c: QPointF, k: float) -> None:
    """A brass plate under the lamp."""
    paint_ground_shadow(p, QPointF(c.x(), c.y() + 6 * k), 82 * k, 30 * k, 170)
    rx, ry = 74 * k, 25 * k
    g = QLinearGradient(c.x() - rx, c.y() - ry, c.x() + rx, c.y() + ry)
    g.setColorAt(0, _c("#F1CE7A"))
    g.setColorAt(0.45, _c("#B8862B"))
    g.setColorAt(1, _c("#6B4710"))
    p.setPen(QPen(_c("#5A3A0C"), 1.0 * k))
    p.setBrush(g)
    p.drawEllipse(c, rx, ry)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 230, 170, 110), 1.2 * k))
    p.drawEllipse(c, rx * 0.8, ry * 0.78)
    p.setPen(QPen(QColor(90, 56, 10, 110), 1.0 * k))
    p.drawEllipse(c, rx * 0.86, ry * 0.84)


def paint_diya(p: QPainter, c: QPointF, k: float) -> QPointF:
    """A clay oil lamp, spout to the right. Returns where the flame sits."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    body = QPainterPath(QPointF(c.x() - 46 * k, c.y()))
    body.cubicTo(c.x() - 44 * k, c.y() + 30 * k, c.x() + 30 * k, c.y() + 34 * k, c.x() + 52 * k, c.y() + 2 * k)
    body.lineTo(c.x() + 66 * k, c.y() - 4 * k)
    body.cubicTo(c.x() + 30 * k, c.y() + 6 * k, c.x() - 10 * k, c.y() + 6 * k, c.x() - 46 * k, c.y())
    g = QLinearGradient(c.x(), c.y(), c.x(), c.y() + 32 * k)
    g.setColorAt(0, _c("#B9572C"))
    g.setColorAt(1, _c("#5C2410"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawPath(body)
    for i in range(7):                                         # pressed dots round the belly
        t = (i + 1) / 8
        x = c.x() - 40 * k + 84 * k * t
        y = c.y() + 14 * k + 6 * k * math.sin(math.pi * t)
        p.setBrush(QColor(240, 170, 110, 120))
        p.drawEllipse(QPointF(x, y), 1.6 * k, 1.2 * k)
    rim = QPainterPath(QPointF(c.x() - 46 * k, c.y()))
    rim.cubicTo(c.x() - 46 * k, c.y() - 22 * k, c.x() + 30 * k, c.y() - 22 * k, c.x() + 70 * k, c.y() - 6 * k)
    rim.cubicTo(c.x() + 30 * k, c.y() + 14 * k, c.x() - 46 * k, c.y() + 20 * k, c.x() - 46 * k, c.y())
    rg = QLinearGradient(c.x(), c.y() - 18 * k, c.x(), c.y() + 14 * k)
    rg.setColorAt(0, _c("#E3874F"))
    rg.setColorAt(1, _c("#A64A22"))
    p.setBrush(rg)
    p.drawPath(rim)
    oil = QTransform()
    oil.translate(c.x() + 4 * k, c.y() - 1 * k)
    oil.scale(0.76, 0.68)
    oil.translate(-(c.x() + 4 * k), -(c.y() - 1 * k))
    og = QRadialGradient(QPointF(c.x() + 10 * k, c.y() - 2 * k), 50 * k)
    og.setColorAt(0, _c("#E7B24E"))
    og.setColorAt(0.5, _c("#8A5A14"))
    og.setColorAt(1, _c("#3A2006"))
    p.setBrush(og)
    p.drawPath(oil.map(rim))
    tip = QPointF(c.x() + 56 * k, c.y() - 7 * k)
    p.setPen(QPen(_c("#F4E6C8"), 2.6 * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(c.x() + 36 * k, c.y() - 3 * k), tip)
    p.setPen(QPen(_c("#2A1508"), 2.6 * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(tip.x() - 2 * k, tip.y() + .5 * k), tip)
    p.restore()
    return QPointF(tip.x() + 1 * k, tip.y() - 2 * k)


def paint_flame(p: QPainter, base: QPointF, k: float, t: float) -> None:
    flick = 1 + 0.07 * math.sin(t * 13.1) + 0.05 * math.sin(t * 29.3 + 1.1) + 0.04 * math.sin(t * 7.7 + 2.0)
    sway = (2.2 * math.sin(t * 5.3) + 1.3 * math.sin(t * 11.9 + .4)) * k
    hgt, wid = 42 * k * flick, 9.5 * k

    def drop(scale: float) -> QPainterPath:
        b = QPointF(base.x(), base.y())
        h, w2 = hgt * scale, wid * scale
        tp = QPointF(base.x() + sway * scale, base.y() - h)
        path = QPainterPath(tp)
        path.cubicTo(tp.x() + w2 * 0.2, tp.y() + h * 0.35, b.x() + w2 * 1.1, b.y() - h * 0.35, b.x() + w2 * 0.6, b.y())
        path.cubicTo(b.x() + w2 * 0.3, b.y() + w2 * 0.55, b.x() - w2 * 0.3, b.y() + w2 * 0.55, b.x() - w2 * 0.6, b.y())
        path.cubicTo(b.x() - w2 * 1.1, b.y() - h * 0.35, tp.x() - w2 * 0.2, tp.y() + h * 0.35, tp.x(), tp.y())
        return path

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    g = QRadialGradient(QPointF(base.x(), base.y() - hgt * 0.3), hgt * 0.8)
    g.setColorAt(0, QColor(255, 236, 170, 240))
    g.setColorAt(0.5, QColor(255, 160, 50, 220))
    g.setColorAt(1, QColor(230, 80, 10, 0))
    p.setBrush(g)
    p.drawPath(drop(1.0))
    p.setBrush(QColor(90, 120, 255, 90))
    p.drawEllipse(QPointF(base.x(), base.y() - 2 * k), 3.2 * k, 4.2 * k)
    core = QRadialGradient(QPointF(base.x() + sway * 0.2, base.y() - hgt * 0.22), hgt * 0.32)
    core.setColorAt(0, QColor(255, 255, 245, 255))
    core.setColorAt(1, QColor(255, 240, 190, 0))
    p.setBrush(core)
    p.drawPath(drop(0.55))
    p.restore()


def paint_mortar(p: QPainter, c: QPointF, k: float) -> None:
    """A stone khalva with green herb paste and its pestle."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_ground_shadow(p, QPointF(c.x() + 10 * k, c.y() + 50 * k), 80 * k, 24 * k, 190)
    rx, ry, depth = 64 * k, 22 * k, 50 * k
    body = QPainterPath(QPointF(c.x() - rx, c.y()))
    body.cubicTo(c.x() - rx, c.y() + depth * 0.7, c.x() - rx * 0.72, c.y() + depth, c.x() - rx * 0.7, c.y() + depth)
    body.cubicTo(c.x() - rx * 0.4, c.y() + depth + ry * 0.55, c.x() + rx * 0.4, c.y() + depth + ry * 0.55,
                 c.x() + rx * 0.7, c.y() + depth)
    body.cubicTo(c.x() + rx * 0.72, c.y() + depth, c.x() + rx, c.y() + depth * 0.7, c.x() + rx, c.y())
    body.closeSubpath()
    g = QLinearGradient(c.x() - rx, 0, c.x() + rx, 0)
    g.setColorAt(0, _c("#8C887A"))
    g.setColorAt(0.35, _c("#6F6B5E"))
    g.setColorAt(1, _c("#2F2D27"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawPath(body)
    rnd = random.Random(9)
    p.save()
    p.setClipPath(body)
    for _ in range(110):
        x = c.x() + rnd.uniform(-rx, rx)
        y = c.y() + rnd.uniform(0, depth + ry)
        p.setBrush(QColor(255, 255, 240, rnd.randint(10, 40)) if rnd.random() < .5 else QColor(0, 0, 0, rnd.randint(14, 50)))
        p.drawEllipse(QPointF(x, y), rnd.uniform(.4, 1.3) * k, rnd.uniform(.4, 1.1) * k)
    p.restore()
    rim = QRadialGradient(QPointF(c.x() - rx * 0.3, c.y() - ry * 0.4), rx * 1.2)
    rim.setColorAt(0, _c("#A9A496"))
    rim.setColorAt(1, _c("#5E5A4F"))
    p.setBrush(rim)
    p.drawEllipse(c, rx, ry)
    bowl = QRadialGradient(QPointF(c.x() + rx * 0.2, c.y() + ry * 0.3), rx)
    bowl.setColorAt(0, _c("#45423A"))
    bowl.setColorAt(1, _c("#1E1C18"))
    p.setBrush(bowl)
    p.drawEllipse(c, rx * 0.8, ry * 0.74)
    paste = QRadialGradient(QPointF(c.x() - rx * 0.1, c.y() + ry * 0.1), rx * 0.7)
    paste.setColorAt(0, _c("#7F8E3A"))
    paste.setColorAt(1, _c("#3B4718"))
    p.setBrush(paste)
    p.drawEllipse(QPointF(c.x(), c.y() + ry * 0.12), rx * 0.66, ry * 0.5)
    for _ in range(18):
        p.setBrush(QColor(200, 220, 120, rnd.randint(40, 110)))
        p.drawEllipse(QPointF(c.x() + rnd.uniform(-.5, .5) * rx, c.y() + ry * 0.12 + rnd.uniform(-.3, .3) * ry), 1.2 * k, .9 * k)
    # pestle leaning out to the upper right
    a, b = QPointF(c.x() + 4 * k, c.y() + 2 * k), QPointF(c.x() + 66 * k, c.y() - 74 * k)
    dx, dy = b.x() - a.x(), b.y() - a.y()
    n = math.hypot(dx, dy)
    nx, ny = -dy / n, dx / n
    w0, w1 = 8 * k, 11 * k
    pestle = QPainterPath(QPointF(a.x() + nx * w0, a.y() + ny * w0))
    pestle.lineTo(b.x() + nx * w1, b.y() + ny * w1)
    pestle.cubicTo(b.x() + nx * w1 + dx / n * 10 * k, b.y() + ny * w1 + dy / n * 10 * k,
                   b.x() - nx * w1 + dx / n * 10 * k, b.y() - ny * w1 + dy / n * 10 * k,
                   b.x() - nx * w1, b.y() - ny * w1)
    pestle.lineTo(a.x() - nx * w0, a.y() - ny * w0)
    pestle.closeSubpath()
    pg = QLinearGradient(a.x() + nx * w1, a.y() + ny * w1, a.x() - nx * w1, a.y() - ny * w1)
    pg.setColorAt(0, _c("#3A3831"))
    pg.setColorAt(0.6, _c("#8E8A7C"))
    pg.setColorAt(1, _c("#B4AF9F"))
    p.setBrush(pg)
    p.drawPath(pestle)
    # the front lip of the bowl in front of the pestle
    p.save()
    p.setClipRect(QRectF(c.x() - rx - 2, c.y() + ry * 0.05, 2 * rx + 4, ry * 2))
    ring = QPainterPath()
    ring.addEllipse(c, rx, ry)
    inner = QPainterPath()
    inner.addEllipse(c, rx * 0.8, ry * 0.74)
    p.setBrush(rim)
    p.drawPath(ring.subtracted(inner))
    p.restore()
    p.restore()


def paint_sprig(p: QPainter, c: QPointF, k: float, angle: float, length: float, seed: int, squash: float = 0.83) -> None:
    """A sprig of tulsi lying on the cloth: paired leaves and a purple flower spike."""
    rnd = random.Random(seed)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(c)
    p.scale(k, k * squash)
    p.rotate(angle)

    def leaf(x, y, ang, size, shadow=False):
        p.save()
        p.translate(x, y)
        p.rotate(ang)
        path = QPainterPath(QPointF(0, 0))
        path.cubicTo(size * 0.25, -size * 0.42, size * 0.75, -size * 0.36, size, 0)
        path.cubicTo(size * 0.75, size * 0.36, size * 0.25, size * 0.42, 0, 0)
        if shadow:
            p.translate(2.5, 3.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 0, 0, 70))
            p.drawPath(path)
        else:
            g = QLinearGradient(0, -size * 0.4, 0, size * 0.4)
            g.setColorAt(0, _c("#7FA34B"))
            g.setColorAt(1, _c("#3E6024"))
            p.setPen(QPen(QColor(30, 50, 14, 160), 0.6))
            p.setBrush(g)
            p.drawPath(path)
            p.setPen(QPen(QColor(200, 230, 150, 130), 0.7))
            p.drawLine(QPointF(1, 0), QPointF(size * 0.85, 0))
        p.restore()

    stem = QPainterPath(QPointF(0, 0))
    stem.cubicTo(length * 0.35, -6, length * 0.7, 5, length, -2)
    pairs = []
    for i in range(6):
        t = 0.1 + i * 0.15
        x = length * t
        y = -6 * 3 * t * (1 - t) * 0.5 + 2 * math.sin(t * 6)
        size = (30 - 15 * t) * rnd.uniform(0.9, 1.1)
        pairs.append((x, y, size))
    for shadow in (True, False):
        if not shadow:
            p.setPen(QPen(_c("#4A5A22"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(stem)
        for x, y, size in pairs:
            leaf(x, y, -58 + rnd.uniform(-6, 6), size, shadow)
            leaf(x, y, 58 + rnd.uniform(-6, 6), size, shadow)
    # flower spike: whorls of tiny purple buds
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(7):
        x = length + i * 4.2
        for s in (-1, 1):
            p.setBrush(QColor(150, 92, 140, 220) if i % 2 else QColor(120, 70, 116, 220))
            p.drawEllipse(QPointF(x, s * (2.6 - i * 0.25)), 1.9, 1.5)
    p.restore()


def paint_amla(p: QPainter, c: QPointF, r: float) -> None:
    paint_ground_shadow(p, QPointF(c.x() + r * 0.25, c.y() + r * 0.75), r * 1.2, r * 0.45, 170)
    g = QRadialGradient(QPointF(c.x() - r * 0.35, c.y() - r * 0.4), r * 1.35)
    g.setColorAt(0, _c("#EEF1B8"))
    g.setColorAt(0.35, _c("#B9C567"))
    g.setColorAt(1, _c("#55621F"))
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(c, r, r * 0.92)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(90, 100, 30, 70), 0.8))
    for f in (0.25, 0.6):
        p.drawEllipse(c, r * f, r * 0.92)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c("#5A4A1C"))
    p.drawEllipse(QPointF(c.x(), c.y() - r * 0.86), r * 0.12, r * 0.07)
    p.restore()


# -- mandala, letters, light ----------------------------------------------------------------------------
def mandala(radius: float, dpr: float, colour: QColor) -> QPixmap:
    size = radius * 2 + 4
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(size / 2, size / 2)
    R = radius
    pen = QPen(colour, max(0.8, R / 300))
    thin = QPen(colour, max(0.5, R / 520))
    p.setBrush(Qt.BrushStyle.NoBrush)

    def petal_ring(n, r0, r1, width, offset=0.0, double=True):
        for i in range(n):
            p.save()
            p.rotate(360 * i / n + offset)
            path = QPainterPath(QPointF(0, -r0))
            path.cubicTo(-width, -r0 - (r1 - r0) * 0.3, -width * 0.6, -r0 - (r1 - r0) * 0.8, 0, -r1)
            path.cubicTo(width * 0.6, -r0 - (r1 - r0) * 0.8, width, -r0 - (r1 - r0) * 0.3, 0, -r0)
            p.setPen(pen)
            p.drawPath(path)
            if double:
                p.setPen(thin)
                p.drawLine(QPointF(0, -r0 - (r1 - r0) * 0.15), QPointF(0, -r1 + (r1 - r0) * 0.22))
            p.restore()

    for f, pp in ((1.0, pen), (0.975, thin), (0.84, pen), (0.5, pen), (0.47, thin), (0.2, pen)):
        p.setPen(pp)
        p.drawEllipse(QPointF(0, 0), R * f, R * f)
    petal_ring(48, R * 0.86, R * 0.965, R * 0.035, double=False)
    petal_ring(16, R * 0.52, R * 0.835, R * 0.11, offset=11.25)
    petal_ring(16, R * 0.52, R * 0.74, R * 0.08)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)
    for i in range(72):
        a = 2 * math.pi * i / 72
        p.drawEllipse(QPointF(R * 0.485 * math.cos(a), R * 0.485 * math.sin(a)), R * 0.0045 + 0.4, R * 0.0045 + 0.4)
    p.setBrush(Qt.BrushStyle.NoBrush)
    petal_ring(8, R * 0.22, R * 0.45, R * 0.1)
    p.setPen(pen)
    for rot in (0, 45):
        p.save()
        p.rotate(rot)
        s = R * 0.12
        p.drawRect(QRectF(-s, -s, 2 * s, 2 * s))
        p.restore()
    p.setBrush(colour)
    p.drawEllipse(QPointF(0, 0), R * 0.025, R * 0.025)
    p.end()
    return px


def glyph_sprite(text: str, px: float, dpr: float) -> QPixmap:
    """One syllable as light: bright core, warm halo."""
    font = _serif_px(px * dpr)
    fm = QFontMetricsF(font)
    w = fm.horizontalAdvance(text) + px * dpr * 1.2
    h = fm.height() + px * dpr * 1.0
    img = _image(w, h)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    p.setFont(font)
    p.setPen(QColor(255, 160, 50))
    p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    halo = blur(img, 4)
    out = _image(w, h)
    p = QPainter(out)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    p.drawImage(0, 0, halo)
    p.drawImage(0, 0, halo)
    p.setFont(font)
    p.setPen(QColor(255, 247, 222))
    p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    pm = QPixmap.fromImage(out)
    pm.setDevicePixelRatio(dpr)
    return pm


def rays_sprite(diameter: float, dpr: float, n: int = 14) -> QPixmap:
    px = QPixmap(int(diameter * dpr), int(diameter * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    c = QPointF(diameter / 2, diameter / 2)
    con = QConicalGradient(c, 0)
    for i in range(n * 2 + 1):
        a = i / (n * 2)
        con.setColorAt(min(1.0, a), QColor(255, 214, 140, 110 if i % 2 == 0 else 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(con)
    p.drawEllipse(c, diameter / 2, diameter / 2)
    # fade the rays out towards the rim
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    fade = QRadialGradient(c, diameter / 2)
    fade.setColorAt(0, QColor(0, 0, 0, 255))
    fade.setColorAt(0.25, QColor(0, 0, 0, 200))
    fade.setColorAt(1, QColor(0, 0, 0, 0))
    p.setBrush(fade)
    p.drawEllipse(c, diameter / 2, diameter / 2)
    p.end()
    return px


# -- the app's mark ------------------------------------------------------------------------------------------
def paint_mark(p: QPainter, r: QRectF) -> None:
    """A maroon tile with a gold सं: the window icon and the header mark."""
    p.save()
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    rad = r.width() * 0.22
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, _c("#8E2A18"))
    g.setColorAt(1, _c("#4A1009"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(r, rad, rad)
    inset = max(1.5, r.width() * 0.07)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_c("#D9A54A", 200), max(0.8, r.width() * 0.03)))
    p.drawRoundedRect(r.adjusted(inset, inset, -inset, -inset), rad * 0.7, rad * 0.7)
    p.setFont(_serif_px(r.height() * 0.56))
    p.setPen(_c("#F6D58C"))
    p.drawText(r.adjusted(0, r.height() * 0.04, 0, 0), Qt.AlignmentFlag.AlignCenter, "सं")
    p.restore()
