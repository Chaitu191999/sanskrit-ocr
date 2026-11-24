"""Interface pieces for Sanskrit OCR. They take their colours from theme.P each time they paint,
so the light/dark switch repaints them in place."""
from __future__ import annotations

from PySide6.QtCore import (QAbstractListModel, QByteArray, QEvent, QModelIndex, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from . import theme
from .art import cover_image, paint_mark

_SVG = {
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M12 12v6M9 15h6"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 10v6M9 13h6"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
           'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
}


def icon(name: str, color: str, px: int = 16, dpr: float = 2.0) -> QIcon:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{_SVG[name]}</svg>')
    pm = QPixmap(int(px * dpr), int(px * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QIcon(pm)


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def fmt_time(s) -> str:
    if s is None:
        return ""
    s = round(s)
    if s < 60:
        return f"{s} s"
    m = s // 60
    if m < 60:
        return f"{m} min {s % 60} s"
    return f"{m // 60} h {m % 60} min"


def set_kind(w, kind: str) -> None:
    w.setProperty("kind", kind)
    w.style().unpolish(w)
    w.style().polish(w)


def label(text: str, role: str | None = None, font=None) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    if font is not None:
        lb.setFont(font)
    return lb


def _c(c) -> QColor:
    return QColor(c)


# -- containers ----------------------------------------------------------------------------------------------
class Card(QFrame):
    """A sheet of ivory paper (or lamp-lit wood, in the dark)."""

    def __init__(self, parent=None, radius: float = 12):
        super().__init__(parent)
        self.radius = radius

    def paintEvent(self, e) -> None:
        P = theme.P
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(P.line, 1))
        p.setBrush(P.surface)
        p.drawRoundedRect(r, self.radius, self.radius)


class HLine(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, e) -> None:
        QPainter(self).fillRect(self.rect(), theme.P.line)


class Ornament(QWidget):
    """A manuscript rule: fine gold lines either side of a small lotus."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)

    def paintEvent(self, e) -> None:
        P = theme.P
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, cy = self.width(), self.height() / 2
        gold = QColor(P.gold)
        for side in (-1, 1):
            g = QLinearGradient(w / 2, 0, w / 2 + side * w / 2, 0)
            c0, c1 = QColor(gold), QColor(gold)
            c0.setAlpha(150)
            c1.setAlpha(0)
            g.setColorAt(0, c0)
            g.setColorAt(1, c1)
            p.setPen(QPen(g, 1))
            x0 = w / 2 + side * 16
            p.drawLine(QPointF(x0, cy - 1.5), QPointF(w / 2 + side * w / 2, cy - 1.5))
            p.drawLine(QPointF(x0, cy + 1.5), QPointF(w / 2 + side * w / 2, cy + 1.5))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gold)
        for dx in (-9, 0, 9):
            r = 2.6 if dx == 0 else 1.6
            p.drawEllipse(QPointF(w / 2 + dx, cy), r, r)


class Mark(QWidget):
    def __init__(self, size: int = 32, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, e) -> None:
        paint_mark(QPainter(self), QRectF(0.5, 0.5, self.width() - 1, self.height() - 1))


class LanguageTile(QWidget):
    """What this edition reads. Not a control: Sanskrit is the only language."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(58)
        self.setAccessibleName("Language: Sanskrit, in Devanagari script")
        self.setToolTip("This edition reads Sanskrit in Devanagari script")

    def paintEvent(self, e) -> None:
        P = theme.P
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(P.line_strong, 1))
        p.setBrush(P.accent_soft)
        p.drawRoundedRect(r, 9, 9)
        disc = QRectF(12, (r.height() - 36) / 2, 36, 36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(P.accent))
        p.drawEllipse(disc)
        p.setPen(QColor(P.on_accent))
        p.setFont(theme.serif(19))
        p.drawText(disc.adjusted(0, 2, 0, 0), Qt.AlignmentFlag.AlignCenter, "सं")
        p.setPen(QColor(P.ink))
        p.setFont(theme.font(15, 600))
        p.drawText(QRectF(60, 9, r.width() - 70, 20), Qt.AlignmentFlag.AlignVCenter, "Sanskrit")
        fm = QFontMetrics(theme.font(15, 600))
        p.setPen(QColor(P.muted))
        p.setFont(theme.serif(16))
        p.drawText(QRectF(60 + fm.horizontalAdvance("Sanskrit") + 8, 7, 200, 22), Qt.AlignmentFlag.AlignVCenter,
                   "संस्कृतम्")
        p.setFont(theme.font(12))
        p.drawText(QRectF(60, 30, r.width() - 70, 18), Qt.AlignmentFlag.AlignVCenter, "Devanagari script")


class PothiBadge(QWidget):
    """The manuscript's cover, small and flat: a reminder of the welcome screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(236, 54)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        tex = cover_image()
        w = 220.0
        h = w * tex.height() / tex.width()
        r = QRectF((self.width() - w) / 2, 4, w, h)
        shade = QColor(theme.P.shadow)
        for i, a in enumerate((1.0, 0.6, 0.3)):
            c = QColor(shade)
            c.setAlpha(int(shade.alpha() * a * 1.6))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            g = 1 + i * 2.5
            p.drawRoundedRect(r.adjusted(-g, -g + 3, g, g + 4), 4 + g, 4 + g)
        p.drawImage(r, tex)
        edge = QRectF(r.x() + 3, r.bottom(), w - 6, 5)
        g2 = QLinearGradient(0, edge.top(), 0, edge.bottom())
        g2.setColorAt(0, QColor("#E8D3A0"))
        g2.setColorAt(1, QColor("#A88A52"))
        p.fillRect(edge, g2)
        p.fillRect(QRectF(r.x(), edge.bottom(), w, 3), QColor("#5C190E"))


class DropZone(QWidget):
    files_clicked = Signal()
    folder_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dragging = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)
        lay.addStretch(1)
        lay.addWidget(PothiBadge(), 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(8)
        big = label("Drop scanned pages, PDFs or folders here", "title", theme.serif(30))
        big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        big.setWordWrap(True)
        lay.addWidget(big)
        sub = label("Folders are searched, including every folder inside them.", "muted")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        self.b_files = QPushButton("Choose files")
        set_kind(self.b_files, "primary")
        self.b_folder = QPushButton("Choose a folder")
        for b in (self.b_files, self.b_folder):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(b)
        row.addStretch(1)
        lay.addSpacing(6)
        lay.addLayout(row)
        self.exts = label("", "small")
        self.exts.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.exts)
        lay.addStretch(1)
        self.b_files.clicked.connect(self.files_clicked)
        self.b_folder.clicked.connect(self.folder_clicked)

    def set_dragging(self, on: bool) -> None:
        self.dragging = on
        self.update()

    def paintEvent(self, e) -> None:
        P = theme.P
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.dragging:
            p.setBrush(P.accent_soft)
            pen = QPen(QColor(P.accent), 1.5)
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(P.line_strong, 1.5)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.drawRoundedRect(r, 12, 12)


# -- file list ---------------------------------------------------------------------------------------------
class FileModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.files: list[dict] = []
        self.busy = False

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.files)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        f = self.files[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f["name"]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f["path"] + (f"\n{f['error']}" if f.get("error") else "")
        if role == Qt.ItemDataRole.UserRole:
            return f
        return None

    def set_files(self, files: list[dict], busy: bool) -> None:
        same = len(files) == len(self.files) and all(a["path"] == b["path"] for a, b in zip(files, self.files))
        self.busy = busy
        if same:
            self.files = files
            if files:
                self.dataChanged.emit(self.index(0), self.index(len(files) - 1))
        else:
            self.beginResetModel()
            self.files = files
            self.endResetModel()


class FileDelegate(QStyledItemDelegate):
    """Paints a file row; reports clicks on its output buttons and its remove button."""

    open_output = Signal(str)
    remove_file = Signal(str)
    ROW = 58

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f_name = theme.font(15, 500)
        self.f_small = theme.font(12)
        self.f_pages = theme.font(13)
        self.f_badge = theme.font(11, 600)
        self.f_chip = theme.font(12, 600)
        self.f_state = theme.font(13)

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), self.ROW)

    @staticmethod
    def _cols(r: QRect):
        x0, w = r.x() + 16, r.width() - 32
        badge = QRectF(x0, r.y() + (r.height() - 20) / 2, 44, 20)
        remove = QRectF(x0 + w - 24, r.y() + (r.height() - 24) / 2, 24, 24)
        state = QRectF(remove.left() - 12 - 150, r.y() + 8, 150, r.height() - 16)
        pages = QRectF(state.left() - 12 - 70, r.y(), 70, r.height())
        name = QRectF(badge.right() + 12, r.y() + 9, pages.left() - 12 - badge.right() - 12, r.height() - 18)
        return badge, name, pages, state, remove

    def _output_rects(self, f: dict, state: QRectF) -> list[tuple[QRectF, str]]:
        fm = QFontMetrics(self.f_chip)
        x, out = state.left(), []
        for o in f.get("outputs") or []:
            text = "Word" if o.lower().endswith(".docx") else "Text"
            w = fm.horizontalAdvance(text) + 16
            out.append((QRectF(x, state.top() + (4 if f.get("error") else 9), w, 22), o))
            x += w + 6
        return out

    @staticmethod
    def _chip(p: QPainter, r: QRectF, text: str, fg: str, bg: QColor) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor(fg))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def paint(self, p: QPainter, option, index) -> None:
        P = theme.P
        f = index.data(Qt.ItemDataRole.UserRole)
        busy = index.model().busy
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state & QStyle.StateFlag.State_MouseOver:
            p.fillRect(r, P.sunk)
        if index.row() < index.model().rowCount() - 1:
            p.fillRect(QRectF(r.x(), r.bottom(), r.width(), 1), P.line)
        badge, name, pages, state, remove = self._cols(r)
        p.setFont(self.f_badge)
        if f["ext"] == "pdf":
            self._chip(p, badge, f["ext"], P.stop, P.stop_soft)
        else:
            p.setPen(QPen(P.line, 1))
            p.setBrush(P.sunk)
            p.drawRoundedRect(badge, 5, 5)
            p.setPen(QColor(P.muted))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, f["ext"])
        p.setFont(self.f_name)
        p.setPen(QColor(P.ink))
        fm = QFontMetrics(self.f_name)
        p.drawText(QRectF(name.x(), name.y(), name.width(), 21), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(f["name"], Qt.TextElideMode.ElideMiddle, int(name.width())))
        p.setFont(self.f_small)
        p.setPen(QColor(P.muted))
        fm2 = QFontMetrics(self.f_small)
        p.drawText(QRectF(name.x(), name.y() + 21, name.width(), 18), Qt.AlignmentFlag.AlignVCenter,
                   fm2.elidedText(f.get("folder") or "Top folder", Qt.TextElideMode.ElideMiddle, int(name.width())))
        if f.get("pages"):
            p.setFont(self.f_pages)
            p.drawText(pages, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, plural(f["pages"], "page"))
        st = f.get("status")
        p.setFont(self.f_chip)
        if st == "done":
            for rr, o in self._output_rects(f, state):
                p.setPen(QPen(P.line_strong, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rr, 5, 5)
                p.setPen(QColor(P.accent))
                p.drawText(rr, Qt.AlignmentFlag.AlignCenter, "Word" if o.lower().endswith(".docx") else "Text")
            if f.get("error"):
                fmc = QFontMetrics(self.f_chip)
                txt = fmc.elidedText(f["error"], Qt.TextElideMode.ElideRight, int(state.width()) - 16)
                self._chip(p, QRectF(state.left(), state.top() + 26, fmc.horizontalAdvance(txt) + 16, 18), txt,
                           P.warn, P.warn_soft)
        elif st == "failed":
            self._chip(p, QRectF(state.left(), state.top() + 2, 56, 20), "Failed", P.stop, P.stop_soft)
            p.setFont(self.f_state)
            p.setPen(QColor(P.muted))
            fm3 = QFontMetrics(self.f_state)
            p.drawText(QRectF(state.left(), state.top() + 24, state.width(), 18), Qt.AlignmentFlag.AlignVCenter,
                       fm3.elidedText(f.get("error") or "", Qt.TextElideMode.ElideRight, int(state.width())))
        elif st == "cancelled":
            self._chip(p, QRectF(state.left(), state.center().y() - 10, 64, 20), "Stopped", P.muted, P.sunk)
        elif st == "running":
            n, done = f.get("pages") or 0, f.get("done") or 0
            p.setFont(self.f_state)
            p.setPen(QColor(P.muted))
            p.drawText(QRectF(state.left(), state.top() + 4, state.width(), 18), Qt.AlignmentFlag.AlignVCenter,
                       f"Page {min(done + 1, n)} of {n}" if n > 1 else "Reading…")
            bar = QRectF(state.left(), state.top() + 27, state.width(), 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(P.line)
            p.drawRoundedRect(bar, 2, 2)
            if n:
                p.setBrush(QColor(P.accent))
                p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * done / n, 4), 2, 2)
        elif busy:
            self._chip(p, QRectF(state.left(), state.center().y() - 10, 62, 20), "Waiting", P.muted, P.sunk)
        if not busy:
            p.setPen(QPen(QColor(P.muted), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            c = remove.center()
            for dx, dy in ((-4.5, -4.5), (4.5, -4.5)):
                p.drawLine(QPointF(c.x() + dx, c.y() + dy), QPointF(c.x() - dx, c.y() - dy))
        p.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        if event.type() != QEvent.Type.MouseButtonRelease or event.button() != Qt.MouseButton.LeftButton:
            return False
        f = index.data(Qt.ItemDataRole.UserRole)
        _, _, _, state, remove = self._cols(option.rect)
        pos = event.position()
        if f.get("status") == "done":
            for rr, o in self._output_rects(f, state):
                if rr.contains(pos):
                    self.open_output.emit(o)
                    return True
        if not model.busy and remove.adjusted(-4, -4, 4, 4).contains(pos):
            self.remove_file.emit(f["path"])
            return True
        return False


# -- settings controls ---------------------------------------------------------------------------------------
class ToggleCard(QFrame):
    """A bordered card with a checkbox, title and explanation; click anywhere to toggle."""

    toggled = Signal(bool)

    def __init__(self, title: str, sub: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.box = QCheckBox()
        self.box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        lay.addWidget(self.box, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(title, font=theme.font(14, 600)))
        col.addWidget(label(sub, "tiny"))
        lay.addLayout(col, 1)
        self.box.toggled.connect(self._changed)
        self._hover = False

    def _changed(self, on: bool) -> None:
        self.update()
        self.toggled.emit(on)

    def isChecked(self) -> bool:
        return self.box.isChecked()

    def setChecked(self, on: bool) -> None:
        self.box.blockSignals(True)
        self.box.setChecked(on)
        self.box.blockSignals(False)
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.box.toggle()

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def paintEvent(self, e) -> None:
        P = theme.P
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.box.isChecked()
        edge = QColor(P.accent)
        edge.setAlpha(150)
        p.setPen(QPen(edge if on else (P.line_strong if self._hover else P.line), 1))
        p.setBrush(P.accent_soft if on else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)


class CheckRow(QWidget):
    """A plain checkbox whose label wraps."""

    toggled = Signal(bool)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.box = QCheckBox()
        lb = label(text, font=theme.font(13))
        lb.setWordWrap(True)
        lb.setCursor(Qt.CursorShape.PointingHandCursor)
        lb.mouseReleaseEvent = lambda e: self.box.toggle()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self.box, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(lb, 1)
        self.box.toggled.connect(self.toggled)

    def isChecked(self) -> bool:
        return self.box.isChecked()

    def setChecked(self, on: bool) -> None:
        self.box.blockSignals(True)
        self.box.setChecked(on)
        self.box.blockSignals(False)


class SegButton(QAbstractButton):
    def __init__(self, title: str, sub: str = "", ic: str | None = None, parent=None):
        super().__init__(parent)
        self.title, self.sub, self.ic = title, sub, ic
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(52 if sub else 30)
        self.setAccessibleName(f"{title}: {sub}" if sub else title)

    def focusInEvent(self, e) -> None:
        # a focus ring only for keyboard users, not when focus lands here by itself
        self._kb = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        super().focusInEvent(e)

    def sizeHint(self) -> QSize:
        if not self.sub:
            fm = QFontMetrics(theme.font(13, 600))
            return QSize(fm.horizontalAdvance(self.title) + (44 if self.ic else 24), 30)
        return QSize(140, 52)

    def paintEvent(self, e) -> None:
        P = theme.P
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.isChecked():
            p.setPen(QPen(QColor(P.accent), 1.5))
            p.setBrush(P.accent_soft)
            p.drawRoundedRect(r, 6, 6)
        elif self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(P.sunk)
            p.drawRoundedRect(r, 6, 6)
        if self.hasFocus() and getattr(self, "_kb", False):
            p.setPen(QPen(QColor(P.accent), 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 5, 5)
        colour = P.accent if self.isChecked() else (P.ink if self.sub else P.muted)
        if not self.sub:      # one line, optional icon: the theme switch
            p.setFont(theme.font(13, 600))
            x = 12.0
            if self.ic:
                p.drawPixmap(QPointF(x, r.center().y() - 7), icon(self.ic, colour, 14).pixmap(14, 14))
                x += 20
            p.setPen(QColor(colour))
            p.drawText(QRectF(x, 0, r.width() - x, self.height()), Qt.AlignmentFlag.AlignVCenter, self.title)
            return
        p.setFont(theme.font(14, 600))
        p.setPen(QColor(colour))
        p.drawText(QRectF(10, 7, r.width() - 12, 20), Qt.AlignmentFlag.AlignVCenter, self.title)
        p.setFont(theme.font(12))
        p.setPen(QColor(P.muted))
        p.drawText(QRectF(10, 27, r.width() - 12, 18), Qt.AlignmentFlag.AlignVCenter, self.sub)


class Segmented(QFrame):
    changed = Signal(str)

    def __init__(self, options: list[tuple], parent=None, radius: float = 8):
        super().__init__(parent)
        self.radius = radius
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(3)
        self.buttons: dict[str, SegButton] = {}
        for key, title, sub, *rest in options:
            b = SegButton(title, sub, rest[0] if rest else None)
            b.clicked.connect(lambda _=False, k=key: self.set_value(k, emit=True))
            lay.addWidget(b)
            self.buttons[key] = b

    def set_value(self, key: str, emit: bool = False) -> None:
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        if emit:
            self.changed.emit(key)

    def paintEvent(self, e) -> None:
        P = theme.P
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(P.line, 1))
        p.setBrush(P.well)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self.radius, self.radius)


# -- progress + toast --------------------------------------------------------------------------------------------
class GlowBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.setFixedHeight(10)

    def set_value(self, v: float) -> None:
        v = max(0.0, min(1.0, v))
        if abs(v - self.value) > 1e-4:
            self.value = v
            self.update()

    def paintEvent(self, e) -> None:
        P = theme.P
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 1.5, -0.5, -0.5)
        p.setPen(QPen(P.line, 1))
        p.setBrush(P.well)
        p.drawRoundedRect(r, 4, 4)
        if self.value > 0:
            fill = QRectF(r.x(), r.y(), max(8.0, r.width() * self.value), r.height())
            g = QLinearGradient(fill.left(), 0, fill.right(), 0)
            g.setColorAt(0, QColor(P.accent))
            g.setColorAt(1, QColor(P.gold))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(fill, 4, 4)


class Toast(QLabel):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setFont(theme.font(14))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.fx = QGraphicsOpacityEffect(self)
        self.fx.setOpacity(0)
        self.setGraphicsEffect(self.fx)
        self.anim = QPropertyAnimation(self.fx, b"opacity", self)
        self.anim.setDuration(200)
        self.timer = QTimer(self, singleShot=True, interval=2600)
        self.timer.timeout.connect(lambda: self._fade(0))
        self.hide()

    def show_text(self, text: str) -> None:
        self.setText(text)
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 24)
        self.show()
        self.raise_()
        self._fade(1)
        self.timer.start()

    def _fade(self, to: float) -> None:
        self.anim.stop()
        self.anim.setStartValue(self.fx.opacity())
        self.anim.setEndValue(to)
        self.anim.start()
