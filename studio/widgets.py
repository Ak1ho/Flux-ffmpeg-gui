from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from studio.catalog import classify
from studio.controls import AnimatedComboBox, ScrollSafeDoubleSpinBox, ScrollSafeSpinBox
from studio.engine import HIDDEN, probe
from studio.paths import engine_path
from studio.theme import icon


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, callback=None, symbol: str = "", primary: bool = False, ghost: bool = False) -> QPushButton:
    widget = QPushButton(text)
    if symbol:
        widget.setIcon(icon(symbol, "#ffffff" if primary else "#a5a8b2"))
    if primary:
        widget.setObjectName("primary")
    elif ghost:
        widget.setObjectName("ghost")
    if callback:
        widget.clicked.connect(callback)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def divider() -> QFrame:
    widget = QFrame()
    widget.setObjectName("divider")
    return widget


def combo(items: list[tuple[str, object]]) -> QComboBox:
    widget = AnimatedComboBox()
    for title, value in items:
        widget.addItem(title, value)
    return widget


def spin(minimum: float, maximum: float, value: float, decimals: int = 0, suffix: str = ""):
    widget = ScrollSafeDoubleSpinBox() if decimals else ScrollSafeSpinBox()
    if decimals:
        widget.setDecimals(decimals)
        widget.setSingleStep(0.1 if decimals == 1 else 0.25)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    if suffix:
        widget.setSuffix(suffix)
    return widget


class Field(QWidget):
    def __init__(self, title: str, control: QWidget):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        caption = label(title, "muted")
        caption.setBuddy(control)
        control.setAccessibleName(title)
        layout.addWidget(caption)
        layout.addWidget(control)


class WorkSignals(QObject):
    result = Signal(object)


class ScanWork(QRunnable):
    def __init__(self, sources: list[str], recursive: bool):
        super().__init__()
        self.sources = sources
        self.recursive = recursive
        self.signals = WorkSignals()

    def run(self):
        found, rejected, errors = [], 0, []
        seen = set()
        candidates = []
        for text in self.sources:
            source = Path(text)
            if source.is_dir():
                for parent, directories, files in os.walk(source, onerror=lambda error: errors.append(str(error)), followlinks=False):
                    directories[:] = sorted(directory for directory in directories if not directory.startswith(".media-"))
                    candidates.extend(Path(parent) / name for name in sorted(files))
                    if not self.recursive:
                        break
            else:
                candidates.append(source)
        for path in candidates:
            try:
                resolved = str(path.resolve())
                key = resolved.casefold()
                if key in seen:
                    continue
                seen.add(key)
                kind = classify(path)
                if kind and path.is_file():
                    found.append({"path": resolved, "kind": kind, "name": path.name, "size": path.stat().st_size, "info": None})
                else:
                    rejected += 1
            except OSError as error:
                errors.append(str(error))
        self.signals.result.emit({"files": found, "rejected": rejected, "errors": errors})


class ProbeWork(QRunnable):
    def __init__(self, path: str, options: dict, kind: str):
        super().__init__()
        self.path, self.options, self.kind = path, dict(options), kind
        self.signals = WorkSignals()

    def run(self):
        try:
            information = probe(Path(self.path), self.options)
            thumbnail = None
            if information["video"]:
                command = [str(engine_path("ffmpeg", self.options)), "-hide_banner", "-loglevel", "error", "-nostdin"]
                if self.kind == "video" and information["duration"] > 2:
                    command += ["-ss", "1"]
                command += ["-i", self.path, "-map", "0:v:0", "-vf", "scale=560:320:force_original_aspect_ratio=decrease", "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1"]
                rendered = subprocess.run(command, capture_output=True, timeout=20, **HIDDEN)
                if rendered.returncode == 0:
                    thumbnail = rendered.stdout
            self.signals.result.emit({"path": self.path, "info": information, "thumbnail": thumbnail})
        except Exception as error:
            self.signals.result.emit({"path": self.path, "error": str(error)})
