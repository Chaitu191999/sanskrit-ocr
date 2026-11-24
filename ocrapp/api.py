"""Bridge between the interface and the OCR pipeline: file list, settings, runs."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

from . import __version__
from .langs import ui_list
from .pipeline import INPUT_EXT, FileItem, Job, Settings, count_pages, discover

_APPDATA = Path(os.environ.get("APPDATA", Path.home()))
SETTINGS_FILE = _APPDATA / "Akshar OCR" / "settings.json"
OLD_SETTINGS_FILE = _APPDATA / "Lipi OCR" / "settings.json"   # the app's earlier name
DEFAULTS = {"langs": [], "txt": True, "docx": True, "quality": "fast",
            "rotate": True, "textLayer": True}


class Api:
    """settings_file / defaults: where and what an edition remembers. fixed: settings an
    edition always runs with, whatever is saved (the Sanskrit edition fixes its model)."""

    def __init__(self, settings_file: Path = SETTINGS_FILE, defaults: dict | None = None,
                 fixed: dict | None = None, old_settings_file: Path | None = OLD_SETTINGS_FILE):
        self.settings_file = settings_file
        self.old_settings_file = old_settings_file
        self.defaults = dict(DEFAULTS if defaults is None else defaults)
        self.fixed = dict(fixed or {})
        self._files: list[FileItem] = []
        self._job: Job | None = None
        self._lock = threading.Lock()
        self._counting = False

    # -- setup -------------------------------------------------------------------
    def init(self) -> dict:
        return {"version": __version__, "languages": ui_list(), "settings": self._load(),
                "cpus": os.cpu_count() or 4,
                "extensions": sorted(e.lstrip(".") for e in INPUT_EXT)}

    def save_settings(self, s: dict) -> None:
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(json.dumps(s), encoding="utf-8")
        except OSError:
            pass

    def _load(self) -> dict:
        src = self.settings_file
        if not src.exists() and self.old_settings_file is not None:
            src = self.old_settings_file
        try:
            return {**self.defaults, **json.loads(src.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            return dict(self.defaults)

    # -- file list -------------------------------------------------------------------
    def add_paths(self, paths: list[str]) -> dict:
        if self._busy():
            return self.list_files()
        self._reset_finished()
        found = discover(paths)
        with self._lock:
            known = {f.path for f in self._files}
            new = [f for f in found if f.path not in known]
            self._files.extend(new)
        self._count_async()
        out = self.list_files()
        out["added"] = len(new)
        out["ignored"] = len(paths) > 0 and not found
        return out

    def remove(self, path: str) -> dict:
        if not self._busy():
            self._reset_finished()
            with self._lock:
                self._files = [f for f in self._files if f.path != path]
        return self.list_files()

    def clear(self) -> dict:
        if not self._busy():
            with self._lock:
                self._files = []
                self._job = None
        return self.list_files()

    def list_files(self) -> dict:
        with self._lock:
            files = [f.view() for f in self._files]
        return {"files": files, "counting": self._counting,
                "pages": sum(f["pages"] for f in files)}

    def _count_async(self) -> None:
        if self._counting:
            return
        self._counting = True

        def work():
            try:
                while True:
                    with self._lock:
                        todo = [f for f in self._files if not f.pages]
                    if not todo:
                        break
                    for f in todo:
                        f.pages = count_pages(f.path)
            finally:
                self._counting = False

        threading.Thread(target=work, daemon=True).start()

    # -- running -------------------------------------------------------------------
    def start(self, s: dict) -> dict:
        if self._busy() or not self._files:
            return self.status()
        self.save_settings(s)
        s = {**s, **self.fixed}
        for f in self._files:   # a re-run starts fresh
            f.done, f.status, f.error, f.outputs = 0, "queued", "", []
        settings = Settings(langs=list(s.get("langs") or []), want_txt=bool(s.get("txt", True)),
                            want_docx=bool(s.get("docx", True)),
                            quality="best" if s.get("quality") == "best" else "fast",
                            auto_rotate=bool(s.get("rotate", True)),
                            use_text_layer=bool(s.get("textLayer", True)),
                            model=str(s.get("model") or ""), clean_paper=bool(s.get("clean", False)))
        self._job = Job(self._files, settings)
        self._job.start()
        return self.status()

    def cancel(self) -> dict:
        if self._job:
            self._job.cancel()
        return self.status()

    def status(self) -> dict:
        if not self._job:
            return {"state": "idle", **self.list_files()}
        snap = self._job.snapshot()
        snap["counting"] = False
        snap["pages"] = snap["total"] or sum(f["pages"] for f in snap["files"])
        return snap

    def _reset_finished(self) -> None:
        """Editing the list after a run starts a new batch: drop the old results."""
        if self._job and not self._busy():
            self._job = None
            for f in self._files:
                f.done, f.status, f.error, f.outputs = 0, "queued", "", []

    def _busy(self) -> bool:
        return bool(self._job and self._job.state in ("counting", "running"))

    # -- shell -------------------------------------------------------------------
    def open_path(self, path: str) -> None:
        if os.path.exists(path):
            os.startfile(path)  # noqa: S606 - opening the user's own output

    def reveal(self, path: str) -> None:
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
