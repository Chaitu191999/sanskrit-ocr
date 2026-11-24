"""Welcome screen: a palm-leaf manuscript on red silk, lit by a clay lamp, among the things of an
Ayurvedic physician's table. Click it and it opens; its letters rise out of the leaf as light,
the light fills the screen and becomes the app.

It is an overlay on top of the main window; when it fades out, the interface is already there.
Frame budget while waiting: the lamp flame repaints at 30 fps inside its own small rectangle;
everything else (the turning mandala, dust in the lamplight, the glow) at 15 fps.
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import art, theme

DESIGN_W, DESIGN_H = 1200.0, 760.0
OPEN_SECONDS = 3.5
DIYA = (-480.0, -40.0)
MORTAR = (472.0, -26.0)


def _smooth(a: float, b: float, x: float) -> float:
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def _ease_io(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


class Splash(QWidget):
    entered = Signal()

    def __init__(self, parent: QWidget, still: bool = False):
        super().__init__(parent)
        self.still = still                      # Windows "Show animations" is off
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Welcome. Press Enter or click the manuscript to open Sanskrit OCR")
        self.pothi = art.Pothi()
        self.cloth = art.cloth_texture()
        self._layers: dict | None = None
        self._sprites: dict[str, QPixmap] = {}
        self._letters: list[dict] = []
        self._rng = random.Random(108)
        self._motes = [self._new_mote(initial=True) for _ in range(46)]
        self._t0 = time.perf_counter()
        self._enter_t: float | None = None
        self._frame = 0
        self._last_full = 0.0
        self._glow = 0.85
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if not still:
            self._timer.start(33)
        QTimer.singleShot(350, self._prepare)  # leaf, writing and letters, made once we are on screen

    # -- geometry -----------------------------------------------------------------------------------------
    def _now(self) -> float:
        return time.perf_counter() - self._t0

    def _fit(self) -> tuple[float, float, float]:
        s = min(self.width() / DESIGN_W, self.height() / DESIGN_H)
        return s, (self.width() - DESIGN_W * s) / 2, (self.height() - DESIGN_H * s) / 2

    def _view(self) -> art.View:
        s, ox, oy = self._fit()
        return art.View(ox + 600 * s, oy + 452 * s, s)

    def _flame_base(self) -> QPointF:
        return self._layers["flame"]

    def _flame_rect(self) -> QRect:
        f, s = self._flame_base(), self._fit()[0]
        return QRect(int(f.x() - 26 * s), int(f.y() - 78 * s), int(52 * s) + 2, int(90 * s) + 2)

    def resizeEvent(self, e) -> None:
        self._layers = None
        super().resizeEvent(e)

    # -- cached layers ------------------------------------------------------------------------------------------
    def _canvas(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        px = QPixmap(self.size() * dpr)
        px.setDevicePixelRatio(dpr)
        px.fill(Qt.GlobalColor.transparent)
        return px

    def _ensure_layers(self) -> dict:
        if self._layers is not None:
            return self._layers
        dpr = self.devicePixelRatioF()
        s, ox, oy = self._fit()
        v = self._view()
        w, h = self.width(), self.height()
        L: dict = {}
        # room: warm dark, a pool of lamplight on the floor, darker corners
        bg = self._canvas()
        p = QPainter(bg)
        g = QRadialGradient(QPointF(w / 2, v.cy - 30 * s), max(w, h) * 0.75)
        g.setColorAt(0, QColor("#4E2617"))
        g.setColorAt(0.5, QColor("#2A120B"))
        g.setColorAt(1, QColor("#0D0503"))
        p.fillRect(self.rect(), g)
        p.save()
        p.translate(v.cx, v.cy + 40 * s)
        p.scale(1, 0.3)
        pool = QRadialGradient(QPointF(0, 0), 700 * s)
        pool.setColorAt(0, QColor(255, 170, 90, 38))
        pool.setColorAt(1, QColor(255, 170, 90, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pool)
        p.drawEllipse(QPointF(0, 0), 700 * s, 700 * s)
        p.restore()
        p.end()
        L["bg"] = bg
        L["mandala"] = art.mandala(300 * s, dpr, QColor(236, 184, 104, 62))
        L["aura"] = art.radial_sprite(820 * s, [(0, QColor(255, 176, 90, 70)), (0.5, QColor(255, 140, 60, 24)),
                                                (1, QColor(0, 0, 0, 0))], dpr)
        L["lamp"] = art.radial_sprite(600 * s, [(0, QColor(255, 200, 120, 190)), (0.22, QColor(255, 150, 60, 72)),
                                                (1, QColor(0, 0, 0, 0))], dpr)
        L["beam"] = self._beam_sprite()
        L["mote"] = art.radial_sprite(10, [(0, QColor(255, 236, 180, 255)), (0.4, QColor(255, 196, 110, 120)),
                                           (1, QColor(0, 0, 0, 0))], dpr)
        # the table: cloth, lamp, mortar, herbs
        props = self._canvas()
        p = QPainter(props)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        art.paint_cloth(p, v, self.cloth)
        dx, dy = DIYA
        lk = v.k(dy) * 1.3
        art.paint_plate(p, v.pt(dx, dy), lk)
        L["flame"] = art.paint_diya(p, v.pt(dx, dy, 6), lk)
        art.paint_mortar(p, v.pt(*MORTAR), v.k(MORTAR[1]))
        art.paint_sprig(p, v.pt(-250, -118), v.k(-118), -12, 120, 1)
        art.paint_sprig(p, v.pt(236, -116), v.k(-116), 196, 96, 2)
        for x, y, r in ((300, -128, 13), (326, -137, 12), (318, -106, 12.5)):
            art.paint_amla(p, v.pt(x, y), r * v.k(y))
        art.paint_ground_shadow(p, v.pt(0, -8), 330 * s, 58 * s, 170)
        p.end()
        L["props"] = props
        closed = self._canvas()
        p = QPainter(closed)
        self.pothi.paint(p, v)
        p.end()
        L["closed"] = closed
        L["words"] = self._words(s, dpr)
        L["verse"] = self._verse(s, dpr)
        L["field_r"] = math.hypot(w, h) * 1.15
        self._layers = L
        return L

    @staticmethod
    def _beam_sprite() -> QImage:
        """A soft column of light: bright in the middle and at the bottom, fading up and out."""
        w, h = 96, 256
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        across = QLinearGradient(0, 0, w, 0)
        for x, a in ((0, 0), (0.2, 60), (0.5, 200), (0.8, 60), (1, 0)):
            across.setColorAt(x, QColor(255, 226, 168, a))
        p.fillRect(img.rect(), across)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        up = QLinearGradient(0, h, 0, 0)
        up.setColorAt(0, QColor(0, 0, 0, 255))
        up.setColorAt(0.5, QColor(0, 0, 0, 140))
        up.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(img.rect(), up)
        p.end()
        return img

    def _words(self, s: float, dpr: float) -> QPixmap:
        w, h = 760 * s, 190 * s
        px = QPixmap(int(w * dpr), int(h * dpr))
        px.setDevicePixelRatio(dpr)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        p.setPen(QColor("#D9A54A"))
        p.setFont(theme.serif(23 * s))
        p.drawText(QRectF(0, 0, w, 36 * s), Qt.AlignmentFlag.AlignCenter, "॥ संस्कृतम् ॥")
        title_rect = QRectF(0, 30 * s, w, 84 * s)
        glow = QPixmap(int(w * dpr / 5), int(84 * s * dpr / 5))   # a soft glow: draw small, scale up
        glow.fill(Qt.GlobalColor.transparent)
        gp = QPainter(glow)
        gp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        gp.setPen(QColor(255, 160, 60, 210))
        gp.setFont(theme.serif(64 * s * dpr / 5))
        gp.drawText(QRectF(0, 0, glow.width(), glow.height()), Qt.AlignmentFlag.AlignCenter, "Sanskrit OCR")
        gp.end()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(0.55)
        p.drawPixmap(title_rect, glow, QRectF(glow.rect()))
        p.setOpacity(1)
        p.setPen(QColor("#F7E7C6"))
        p.setFont(theme.serif(64 * s))
        p.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, "Sanskrit OCR")
        p.setPen(QColor("#CDB596"))
        p.setFont(theme.font(16 * s))
        p.drawText(QRectF((w - 560 * s) / 2, 122 * s, 560 * s, 60 * s),
                   Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap,
                   "Turns scanned Sanskrit pages, from old printed books to Ayurvedic texts, "
                   "into Word and text files, without the internet.")
        p.end()
        return px

    def _verse(self, s: float, dpr: float) -> QPixmap:
        w, h = 900 * s, 64 * s
        px = QPixmap(int(w * dpr), int(h * dpr))
        px.setDevicePixelRatio(dpr)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        p.setPen(QColor("#E6BE72"))
        p.setFont(theme.serif(22 * s))
        p.drawText(QRectF(0, 0, w, 32 * s), Qt.AlignmentFlag.AlignCenter, art.VERSE)
        p.setPen(QColor("#B39B7C"))
        p.setFont(theme.serif(15 * s, italic=True))
        p.drawText(QRectF(0, 34 * s, w, 26 * s), Qt.AlignmentFlag.AlignCenter, art.VERSE_EN)
        p.end()
        return px

    def _prepare(self) -> None:
        """Make the leaf, its writing and one bright sprite per written syllable."""
        self.pothi.prepare()
        dpr = self.devicePixelRatioF()
        s = max(0.6, self._fit()[0])
        for sy, _, _ in self.pothi.layout:
            if sy not in self._sprites:
                self._sprites[sy] = art.glyph_sprite(sy, 34 * s, dpr)

    # -- motes and letters ----------------------------------------------------------------------------------
    def _new_mote(self, initial: bool = False) -> dict:
        r = self._rng
        return {"x": r.uniform(150, 1050), "y": r.uniform(220, 640) if initial else r.uniform(560, 660),
                "vy": r.uniform(7, 18), "amp": r.uniform(6, 20), "f": r.uniform(0.2, 0.6), "ph": r.uniform(0, 6.3),
                "size": r.uniform(0.35, 1.0), "tw": r.uniform(0.6, 1.8)}

    def _step_motes(self, dt: float) -> None:
        for i, m in enumerate(self._motes):
            m["y"] -= m["vy"] * dt
            if m["y"] < 150:
                self._motes[i] = self._new_mote()

    def _spawn_letters(self) -> None:
        self._prepare()
        v = self._view()
        s = v.s
        r = self._rng
        lay = self.pothi.layout
        centre = art.Pothi.leaf_point(v, art.LL / 2, art.LD / 2)
        n = 230
        self._letters = []
        for i in range(n):
            sy, lx, ly = lay[r.randrange(len(lay))]
            o = art.Pothi.leaf_point(v, lx, ly)
            self._letters.append({
                "sy": sy, "x": o.x(), "y": o.y(),
                "birth": 0.95 + 1.45 * (i / n) ** 0.85 + r.uniform(-0.08, 0.08),
                "life": r.uniform(1.3, 2.1),
                "vx": (o.x() - centre.x()) * r.uniform(0.25, 0.6) + r.uniform(-50, 50) * s,
                "vy": -r.uniform(150, 330) * s, "acc": r.uniform(40, 140) * s,
                "amp": r.uniform(8, 38) * s, "f": r.uniform(1.4, 3.6), "ph": r.uniform(0, 6.3),
                "grow": r.uniform(1.4, 2.6), "spin": r.uniform(-28, 28),
            })

    # -- animation -------------------------------------------------------------------------------------------
    def _tick(self) -> None:
        self._frame += 1
        t = self._now()
        if self._enter_t is not None:
            if t - self._enter_t >= OPEN_SECONDS:
                self._finish()
                return
            self._full_frame_state(t)
            self.update()
            return
        if self._frame % 2 == 0:
            self._full_frame_state(t)
            self.update()                          # glow, mandala, dust: 15 fps
        elif self._layers is not None:
            self.update(self._flame_rect())        # the flame alone: the other 15 fps

    def _full_frame_state(self, t: float) -> None:
        dt = min(0.2, t - self._last_full) if self._last_full else 0.066
        self._last_full = t
        self._step_motes(dt)
        self._glow = 0.78 + 0.1 * math.sin(t * 7.3) + 0.06 * math.sin(t * 17.1 + 1.3)
        self._angle = (t * 2.2) % 360

    def enter(self) -> None:
        if self._enter_t is not None:
            # a second click or key press skips to the end of the opening
            self._enter_t = min(self._enter_t, self._now() - (OPEN_SECONDS - 0.5))
            return
        if self.still:
            self._finish()
            return
        self._enter_t = self._now()
        self._spawn_letters()
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _finish(self) -> None:
        self._timer.stop()
        self.hide()
        self.entered.emit()
        self.deleteLater()

    def _over_pothi(self, pos) -> bool:
        if self._layers is None:
            return False
        return self.pothi.bounds(self._view()).adjusted(-24, -30, 24, 24).contains(pos)

    def mouseMoveEvent(self, e) -> None:
        over = self._enter_t is None and self._over_pothi(e.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and (self._enter_t is not None or self._over_pothi(e.position())):
            self.enter()

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Escape):
            self.enter()
        else:
            super().keyPressEvent(e)

    # -- painting ----------------------------------------------------------------------------------------------
    def paintEvent(self, e) -> None:
        L = self._ensure_layers()
        t = self._now()
        o = None if self._enter_t is None else t - self._enter_t
        s, ox, oy = self._fit()
        v = self._view()
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setClipRect(e.rect())
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        base = 1.0 if o is None else 1 - _smooth(OPEN_SECONDS - 0.75, OPEN_SECONDS, o)
        p.setOpacity(base)
        p.drawPixmap(0, 0, L["bg"])

        # the mandala turns slowly; while the book opens it brightens and turns faster
        lift = 0.0 if o is None else _smooth(0.3, 2.0, o)
        mand = L["mandala"]
        md = mand.width() / mand.devicePixelRatio()
        p.save()
        p.translate(v.cx, v.cy - 40 * s)
        p.rotate(self._angle + (0 if o is None else 40 * _smooth(0.2, 3.0, o) ** 2))
        p.setOpacity(base * (0.85 + 1.2 * lift))
        p.drawPixmap(QPointF(-md / 2, -md / 2), mand)
        p.restore()

        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        aura = L["aura"]
        ad = aura.width() / aura.devicePixelRatio()
        p.setOpacity(base * (0.75 + 0.25 * math.sin(t * 1.4) if not self.still else 0.85) * (1 + 1.5 * lift))
        p.drawPixmap(QPointF(v.cx - ad / 2, v.cy - 40 * s - ad / 2), aura)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setOpacity(base)
        p.drawPixmap(0, 0, L["props"])

        if o is None:
            p.drawPixmap(0, 0, L["closed"])
        else:
            deg = 166 * _ease_io((o - 0.22) / 0.9)
            self.pothi.paint(p, v, deg, cord=1 - _smooth(0.0, 0.24, o), glow=1.25 * _smooth(0.55, 1.3, o))

        # the lamp: flame, and its light on everything near it
        f = L["flame"]
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        lamp = L["lamp"]
        ld = lamp.width() / lamp.devicePixelRatio()
        p.setOpacity(base * self._glow)
        p.drawPixmap(QPointF(f.x() - ld / 2, f.y() - 18 * s - ld / 2), lamp)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setOpacity(base)
        art.paint_flame(p, f, v.k(DIYA[1]) * 1.3, 0.35 if self.still else t)

        # dust drifting up through the lamplight
        if not self.still:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            mote = L["mote"]
            for m in self._motes:
                x = ox + (m["x"] + m["amp"] * math.sin(m["f"] * t + m["ph"])) * s
                y = oy + m["y"] * s
                a = (0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * m["tw"] + m["ph"]))) * min(1.0, (m["y"] - 150) / 120)
                p.setOpacity(base * max(0.0, a) * 0.8)
                d = 10 * m["size"] * max(0.7, s)
                p.drawPixmap(QRectF(x - d / 2, y - d / 2, d, d), mote, QRectF(mote.rect()))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # words
        words_a = 1.0 if o is None else 1 - _smooth(0.0, 0.45, o)
        if words_a > 0:
            p.setOpacity(base * words_a)
            wp = L["words"]
            p.drawPixmap(QPointF(w / 2 - wp.width() / wp.devicePixelRatio() / 2, oy + 40 * s), wp)
            vp = L["verse"]
            p.drawPixmap(QPointF(w / 2 - vp.width() / vp.devicePixelRatio() / 2, oy + 628 * s), vp)
            pulse = 1.0 if self.still else 0.55 + 0.45 * (0.5 - 0.5 * math.cos(t * 2 * math.pi / 3.2))
            p.setOpacity(base * words_a * pulse)
            p.setPen(QColor("#E9A23B"))
            p.setFont(theme.font(max(12.0, 14.5 * s), 500))
            p.drawText(QRectF(0, oy + 704 * s, w, 26 * s), Qt.AlignmentFlag.AlignHCenter,
                       "Click the manuscript to open it")

        if o is not None:
            self._paint_opening(p, v, o, base)
        p.end()

    def _paint_opening(self, p: QPainter, v: art.View, o: float, base: float) -> None:
        s = v.s
        w, h = self.width(), self.height()
        c = art.Pothi.leaf_point(v, art.LL / 2, art.LD / 2)
        lift = _smooth(0.9, 1.8, o)
        # a column of light rising from the open leaf
        if lift > 0:
            half = art.LL / 2 * v.k(0, art.Z_LEAF) * 1.05
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
            p.setOpacity(base * lift)
            p.drawImage(QRectF(c.x() - half, 0, 2 * half, c.y() + 20 * s), self._layers["beam"])
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # the letters, lifting off the leaf as light
        if self._letters:
            p.setOpacity(base)
            for L in self._letters:
                a = o - L["birth"]
                if a <= 0 or a >= L["life"]:
                    continue
                spr = self._sprites.get(L["sy"])
                if spr is None:
                    continue
                k = a / L["life"]
                x = L["x"] + L["vx"] * a + L["amp"] * (math.sin(L["f"] * a + L["ph"]) - math.sin(L["ph"]))
                y = L["y"] + L["vy"] * a - 0.5 * L["acc"] * a * a
                alpha = _smooth(0.0, 0.16, a) * (1 - _smooth(0.55, 1.0, k))
                if alpha <= 0.01:
                    continue
                scale = 0.42 + (L["grow"] - 0.42) * k ** 0.8
                sw, sh = spr.width() / spr.devicePixelRatio(), spr.height() / spr.devicePixelRatio()
                p.save()
                p.translate(x, y)
                p.rotate(L["spin"] * k)
                p.scale(scale, scale)
                p.setOpacity(base * alpha)
                p.drawPixmap(QPointF(-sw / 2, -sh / 2), spr)
                p.restore()

        # the field of light, growing from the leaf until it fills the screen; the letters
        # nearest the leaf dissolve into it, the ones further out still show at its rim
        grow = _smooth(1.55, 2.85, o)
        if grow > 0:
            r = 40 * s + grow ** 1.6 * self._layers["field_r"]
            g = QRadialGradient(c, r)
            g.setColorAt(0, QColor(255, 253, 244, 255))
            g.setColorAt(0.55, QColor(255, 248, 230, 255))
            g.setColorAt(0.8, QColor(255, 220, 150, 170))
            g.setColorAt(1, QColor(255, 196, 110, 0))
            p.setOpacity(base)
            p.fillRect(self.rect(), g)
