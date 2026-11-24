"""The main window: files on the left, settings on the right, progress at the bottom.

Light (palm leaf and parchment) by default; the switch in the header changes to dark and is
remembered.
"""
from __future__ import annotations

import ctypes
import threading

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QListView, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import art, theme
from .splash import Splash
from .widgets import (Card, CheckRow, DropZone, FileDelegate, FileModel, GlowBar, HLine, LanguageTile, Mark,
                      Ornament, Segmented, Toast, ToggleCard, fmt_time, icon, label, plural, set_kind)

TITLE = "Sanskrit OCR"


class _Bridge(QObject):
    """Carries results from worker threads back to the UI thread."""
    done = Signal(object, object)


def _animations_enabled() -> bool:
    """Windows' "Show animations in Windows" setting (SPI_GETCLIENTAREAANIMATION)."""
    try:
        on = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)
        return bool(on.value)
    except Exception:
        return True


class MainWindow(QWidget):
    def __init__(self, api, autostart: bool = False):
        super().__init__()
        self.api = api
        self.setWindowTitle(TITLE)
        self.resize(1180, 740)
        self.setMinimumSize(920, 600)
        self.setAcceptDrops(True)
        info = api.init()
        self.extensions = info["extensions"]
        self.S = info["settings"]
        theme.use(self.S.get("theme", "light"))
        QApplication.instance().setStyleSheet(theme.style_sheet())
        self.last: dict = {"state": "idle", "files": [], "pages": 0}
        self.dismissed_state = None
        self._bg: QPixmap | None = None
        self._bridge = _Bridge()
        self._bridge.done.connect(lambda cb, r: cb(r))
        self._poll = QTimer(self, interval=400)
        self._poll.timeout.connect(self._tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 14, 24, 18)
        root.setSpacing(10)
        root.addLayout(self._header())
        root.addWidget(Ornament())
        main = QHBoxLayout()
        main.setSpacing(18)
        self.files_card = self._files_card(info["extensions"])
        self.settings_card = self._settings_card()
        main.addWidget(self.files_card, 1)
        main.addWidget(self.settings_card)
        root.addLayout(main, 1)
        root.addWidget(self._run_card())

        for card in (self.files_card, self.settings_card, self.run):
            card.installEventFilter(self)       # their shadows are painted in the background
        self.toast = Toast(self)
        self._apply_settings()
        self._render(api.list_files())

        self.splash = Splash(self, still=not _animations_enabled())
        self.splash.entered.connect(self._entered)
        self.splash.setGeometry(self.rect())
        self.splash.raise_()
        self.splash.setFocus()
        self._autostart = autostart
        if autostart:
            QTimer.singleShot(1500, self.splash.enter)

    # -- layout --------------------------------------------------------------------------------------
    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(Mark(34))
        title = label(TITLE, "title", theme.serif(30))
        row.addWidget(title)
        deva = label("संस्कृतम्", "muted", theme.serif(21))
        deva.setContentsMargins(0, 3, 0, 0)
        row.addWidget(deva)
        row.addStretch(1)
        self.theme_switch = Segmented([("light", "Light", "", "sun"), ("dark", "Dark", "", "moon")], radius=9)
        self.theme_switch.setAccessibleName("Colour theme")
        self.theme_switch.changed.connect(self._set_theme)
        row.addWidget(self.theme_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _quiet(self, text: str, ic: str | None = None) -> QPushButton:
        b = QPushButton(text)
        set_kind(b, "quiet")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if ic:
            b.setProperty("icon_name", ic)
            b.setIcon(icon(ic, theme.P.muted))
            b.setIconSize(QSize(16, 16))
        return b

    def _files_card(self, exts: list[str]) -> Card:
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 10, 12, 10)
        head.addWidget(label("Files", "title", theme.serif(24)))
        head.addStretch(1)
        self.b_add_files = self._quiet("Add files", "file")
        self.b_add_folder = self._quiet("Add folder", "folder")
        head.addWidget(self.b_add_files)
        head.addWidget(self.b_add_folder)
        lay.addLayout(head)
        lay.addWidget(HLine())

        self.stack = QStackedWidget()
        self.drop = DropZone()
        self.drop.exts.setText("  ·  ".join(e.upper() for e in exts))
        drop_wrap = QWidget()
        dl = QVBoxLayout(drop_wrap)
        dl.setContentsMargins(16, 16, 16, 16)
        dl.addWidget(self.drop)
        self.stack.addWidget(drop_wrap)

        self.model = FileModel()
        self.view = QListView()
        self.view.setModel(self.model)
        self.delegate = FileDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.view.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.view.viewport().setAutoFillBackground(False)
        self.stack.addWidget(self.view)
        lay.addWidget(self.stack, 1)

        self.foot_line = HLine()
        lay.addWidget(self.foot_line)
        self.foot = QWidget()
        fl = QHBoxLayout(self.foot)
        fl.setContentsMargins(16, 6, 12, 6)
        self.summary = label("", "small")
        fl.addWidget(self.summary)
        fl.addStretch(1)
        self.b_clear = self._quiet("Clear list")
        fl.addWidget(self.b_clear)
        lay.addWidget(self.foot)

        self.b_add_files.clicked.connect(self._pick_files)
        self.drop.files_clicked.connect(self._pick_files)
        self.b_add_folder.clicked.connect(self._pick_folder)
        self.drop.folder_clicked.connect(self._pick_folder)
        self.b_clear.clicked.connect(lambda: self._render(self.api.clear()))
        self.delegate.open_output.connect(self.api.open_path)
        self.delegate.remove_file.connect(lambda p: self._render(self.api.remove(p)))
        return card

    def _settings_card(self) -> Card:
        card = Card()
        card.setFixedWidth(336)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 12, 16, 12)
        head.addWidget(label("Settings", "title", theme.serif(24)))
        lay.addLayout(head)
        lay.addWidget(HLine())

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 4, 16, 14)
        bl.setSpacing(7)

        def section(text):
            lb = label(text, "label")
            lb.setContentsMargins(0, 10, 0, 0)
            bl.addWidget(lb)

        section("Language")
        bl.addWidget(LanguageTile())
        section("Save as")
        self.t_docx = ToggleCard("Word document", "Keeps columns, headings and pictures")
        self.t_txt = ToggleCard("Text file", "Plain text in reading order")
        bl.addWidget(self.t_docx)
        bl.addWidget(self.t_txt)
        section("Speed")
        self.speed = Segmented([("fast", "Fast", "Clear prints"), ("best", "Accurate", "Worn pages, slower")])
        bl.addWidget(self.speed)
        section("Options")
        self.c_clean = CheckRow("Even out yellowed, stained or faded paper")
        self.c_rotate = CheckRow("Straighten sideways or upside-down pages")
        self.c_text = CheckRow("Use text already inside PDFs when it is correct")
        bl.addWidget(self.c_clean)
        bl.addWidget(self.c_rotate)
        bl.addWidget(self.c_text)
        bl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        body.setAutoFillBackground(False)
        lay.addWidget(scroll, 1)

        lay.addWidget(HLine())
        cta = QVBoxLayout()
        cta.setContentsMargins(16, 14, 16, 14)
        cta.setSpacing(8)
        self.b_start = QPushButton("Start")
        set_kind(self.b_start, "primary")
        self.b_start.setStyleSheet("padding: 11px; font-size: 16px;")
        self.b_start.setCursor(Qt.CursorShape.PointingHandCursor)
        cta.addWidget(self.b_start)
        note = label("Results are saved next to each original file", "small")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cta.addWidget(note)
        lay.addLayout(cta)

        self.t_docx.toggled.connect(lambda v: self._set("docx", v))
        self.t_txt.toggled.connect(lambda v: self._set("txt", v))
        self.speed.changed.connect(lambda v: self._set("quality", v))
        self.c_clean.toggled.connect(lambda v: self._set("clean", v))
        self.c_rotate.toggled.connect(lambda v: self._set("rotate", v))
        self.c_text.toggled.connect(lambda v: self._set("textLayer", v))
        self.b_start.clicked.connect(self._start)
        return card

    def _run_card(self) -> Card:
        self.run = Card()
        lay = QVBoxLayout(self.run)
        lay.setContentsMargins(18, 12, 18, 14)
        lay.setSpacing(8)
        top = QHBoxLayout()
        self.nums = label("")
        self.nums.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.nums, 1)
        self.b_stop = QPushButton("Stop")
        self.b_reveal = QPushButton("Show in folder")
        self.b_close = self._quiet("Close")
        for b in (self.b_stop, self.b_reveal, self.b_close):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            top.addWidget(b)
        lay.addLayout(top)
        self.bar = GlowBar()
        lay.addWidget(self.bar)
        self.run.hide()
        self.b_stop.clicked.connect(self._cancel)
        self.b_reveal.clicked.connect(self._reveal)
        self.b_close.clicked.connect(self._dismiss)
        return self.run

    # -- background ----------------------------------------------------------------------------------
    def paintEvent(self, e) -> None:
        dpr = self.devicePixelRatioF()
        if self._bg is None or self._bg.size() != self.size() * dpr:
            self._bg = self._paint_background(dpr)
        r = e.rect()
        src = QRect(int(r.x() * dpr), int(r.y() * dpr), int(r.width() * dpr), int(r.height() * dpr))
        QPainter(self).drawPixmap(r, self._bg, src)

    def _paint_background(self, dpr: float) -> QPixmap:
        P = theme.P
        w, h = self.width(), self.height()
        px = QPixmap(self.size() * dpr)
        px.setDevicePixelRatio(dpr)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor(P.bg_top))
        g.setColorAt(1, QColor(P.bg_bottom))
        p.fillRect(self.rect(), g)
        # a large lotus mandala, mostly off the page, like a watermark in old paper
        rad = max(w, h) * 0.42
        md = art.mandala(rad, dpr, P.watermark)
        p.drawPixmap(QPointF(w - rad * 0.62 - rad, h - rad * 0.55 - rad), md)
        p.drawPixmap(QPointF(-rad * 0.45 - rad * 0.55, -rad * 0.5 - rad * 0.6), md)
        # soft shadows under the cards
        for card in (self.files_card, self.settings_card, self.run):
            if not card.isVisible():
                continue
            gr = QRectF(card.geometry())
            for i, a in enumerate((10, 7, 4)):
                c = QColor(P.shadow)
                c.setAlpha(int(P.shadow.alpha() * a / 10))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                grow = 2 + i * 3
                p.drawRoundedRect(gr.adjusted(-grow + 1, -grow + 3, grow - 1, grow + 4), 14 + grow, 14 + grow)
        p.end()
        return px

    def eventFilter(self, obj, e) -> bool:
        if e.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.Hide):
            self._bg = None
            self.update()
        return False

    def resizeEvent(self, e) -> None:
        self._bg = None
        if getattr(self, "splash", None) is not None:
            self.splash.setGeometry(self.rect())
        super().resizeEvent(e)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._title_bar()

    def _title_bar(self) -> None:
        """Title bar colours to match the theme (Windows 10 2004+ / 11)."""
        try:
            hwnd = int(self.winId())
            dark = ctypes.c_int(1 if theme.P.dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)
            c = QColor(theme.P.bg_top)
            colour = ctypes.c_int(c.red() | c.green() << 8 | c.blue() << 16)   # COLORREF 0x00BBGGRR
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colour), 4)
        except Exception:
            pass

    def _entered(self) -> None:
        self.splash = None
        if self._autostart:
            QTimer.singleShot(200, self._start)

    # -- theme ---------------------------------------------------------------------------------------------
    def _set_theme(self, name: str) -> None:
        if name == theme.P.name:
            return
        theme.use(name)
        self.theme_switch.set_value(name)
        self._set("theme", name)
        app = QApplication.instance()
        app.setStyleSheet(theme.style_sheet())
        for b in (self.b_add_files, self.b_add_folder):
            b.setIcon(icon(b.property("icon_name"), theme.P.muted))
        self._bg = None
        self._title_bar()
        self._render_run(self.last)
        for w in self.findChildren(QWidget):
            w.update()
        self.update()

    # -- settings -------------------------------------------------------------------------------------
    def _apply_settings(self) -> None:
        s = self.S
        self.t_docx.setChecked(bool(s.get("docx")))
        self.t_txt.setChecked(bool(s.get("txt")))
        self.speed.set_value(s.get("quality", "fast"))
        self.c_clean.setChecked(bool(s.get("clean")))
        self.c_rotate.setChecked(bool(s.get("rotate")))
        self.c_text.setChecked(bool(s.get("textLayer")))
        self.theme_switch.set_value(theme.P.name)
        self._update_start()

    def _set(self, key: str, value) -> None:
        self.S[key] = value
        self.api.save_settings(self.S)
        self._update_start()

    # -- files ------------------------------------------------------------------------------------------
    def _busy(self) -> bool:
        return self.last.get("state") in ("running", "counting")

    def _in_background(self, fn, cb) -> None:
        def work():
            r = fn()
            self._bridge.done.emit(cb, r)
        threading.Thread(target=work, daemon=True).start()

    def _add(self, paths: list[str]) -> None:
        if not paths:
            return
        self._in_background(lambda: self.api.add_paths(paths), self._after_add)

    def _after_add(self, r: dict) -> None:
        self._render(r)
        if r.get("ignored"):
            self.toast.show_text("No PDFs or images found there")
        elif r.get("added") == 0:
            self.toast.show_text("No new PDFs or images found")
        self._poll.start()

    def _pick_files(self) -> None:
        exts = " ".join(f"*.{e}" for e in self.extensions)
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files", "",
                                                f"Documents and images ({exts});;All files (*.*)")
        self._add(paths)

    def _pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose a folder")
        self._add([d] if d else [])

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and not self._busy() and self.splash is None:
            e.acceptProposedAction()
            self.drop.set_dragging(True)

    def dragLeaveEvent(self, e) -> None:
        self.drop.set_dragging(False)

    def dropEvent(self, e) -> None:
        self.drop.set_dragging(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        e.acceptProposedAction()
        self._add(paths)

    # -- running -----------------------------------------------------------------------------------------
    def _update_start(self) -> None:
        n = len(self.last.get("files") or [])
        want = self.S.get("docx") or self.S.get("txt")
        self.b_start.setEnabled(bool(n and want and not self._busy()))
        self.b_start.setText("Choose an output" if not want else (f"Start · {plural(n, 'file')}" if n else "Start"))

    def _start(self) -> None:
        if not self.b_start.isEnabled():
            return
        self.dismissed_state = None
        self._render(self.api.start(self.S))
        self._poll.start()

    def _cancel(self) -> None:
        self.b_stop.setEnabled(False)
        self.b_stop.setText("Stopping…")
        self._render(self.api.cancel())

    def _reveal(self) -> None:
        out = next((f["outputs"][0] for f in self.last.get("files") or [] if f.get("outputs")), None)
        if out:
            self.api.reveal(out)

    def _dismiss(self) -> None:
        self.dismissed_state = self.last.get("state")
        self.run.hide()

    def _tick(self) -> None:
        r = self.api.status()
        self._render(r)
        if not (r.get("state") in ("running", "counting") or r.get("counting")):
            self._poll.stop()

    def _render(self, r: dict) -> None:
        if not r:
            return
        if "state" not in r:
            r = {**r, "state": self.last.get("state", "idle") if self._busy() else "idle"}
        self.last = r
        files = r.get("files") or []
        busy = self._busy()
        self.stack.setCurrentIndex(1 if files else 0)
        self.foot.setVisible(bool(files))
        self.foot_line.setVisible(bool(files))
        self.model.set_files(files, busy)
        pages = r.get("pages") or 0
        self.summary.setText(plural(len(files), "file") + (f" · {plural(pages, 'page')}" if pages else "") +
                             (" · counting pages…" if r.get("counting") else ""))
        self.b_clear.setEnabled(not busy)
        self.b_add_files.setEnabled(not busy)
        self.b_add_folder.setEnabled(not busy)
        self._render_run(r)
        self._update_start()

    def _render_run(self, r: dict) -> None:
        state = r.get("state", "idle")
        if state == "idle" or state == self.dismissed_state:
            self.run.hide()
            return
        self.dismissed_state = None
        self.run.show()
        P = theme.P
        total, done = r.get("total") or 0, r.get("done") or 0
        self.bar.set_value(1.0 if state == "done" else (done / total if total else 0))
        big = f"font-family:'{theme.SERIF}'; font-size:26px; color:{P.title};"
        small = f"font-family:'{theme.SANS}'; font-size:14px; color:{P.muted};"

        def nums(a, b):
            self.nums.setText(f"<span style=\"{big}\">{a}</span>&nbsp;&nbsp;&nbsp;<span style=\"{small}\">{b}</span>")

        if state == "counting":
            nums("Getting ready", "counting pages")
        elif state == "running":
            rate = f"{r['rate']:.1f} pages a second" if r.get("rate") else "starting"
            eta = f" · about {fmt_time(r['eta'])} left" if r.get("eta") is not None and done > 2 else ""
            nums(f"{done:,} of {plural(total, 'page')}", rate + eta)
        elif state == "cancelled":
            nums("Stopped", f"{plural(r.get('completed') or 0, 'file')} finished before stopping")
        else:
            fail = f" · {r['failed']} could not be read" if r.get("failed") else ""
            nums("Done", f"{plural(r.get('completed') or 0, 'file')}, {plural(total, 'page')} "
                         f"in {fmt_time(r.get('elapsed'))}{fail}")
        busy = self._busy()
        self.b_stop.setVisible(busy)
        if busy and self.b_stop.text() != "Stopping…":
            self.b_stop.setEnabled(True)
        if not busy:
            self.b_stop.setText("Stop")
        has_out = any(f.get("outputs") for f in r.get("files") or [])
        self.b_reveal.setVisible(not busy and has_out)
        self.b_close.setVisible(not busy)
