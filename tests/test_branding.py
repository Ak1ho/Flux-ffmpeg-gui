from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel

from studio import APP_ENGLISH_NAME, APP_NAME, APP_TITLE, VERSION
from studio import paths, ui
from studio.paths import ROOT, write_json
from studio.theme import icon
from test_motion import window
from test_ui import application, isolated


def test_window_sidebar_and_about_use_flux(window):
    assert window.windowTitle() == APP_TITLE == "流转 · Flux"
    texts = [label.text() for label in window.centralWidget().findChildren(QLabel)]
    assert APP_NAME in texts
    assert APP_ENGLISH_NAME.upper() in texts
    assert any(APP_TITLE in text and VERSION in text for text in texts)
    assert "媒体工坊" not in texts
    assert "MEDIA WORKBENCH" not in texts
    assert window.windowIcon().pixmap(64, 64).toImage() == icon("brand").pixmap(64, 64).toImage()


def test_brand_icon_uses_new_multisize_asset(application):
    brand = icon("brand")
    expected = QIcon(str(ROOT / "assets/app.ico"))
    assert not brand.isNull()
    assert {16, 24, 32, 48, 256}.issubset({size.width() for size in brand.availableSizes()})
    assert brand.pixmap(256, 256).toImage() == expected.pixmap(256, 256).toImage()
    assert brand.pixmap(256, 256).toImage().pixelColor(0, 0).alpha() == 0


def test_export_report_uses_flux(window, monkeypatch, tmp_path):
    destination = tmp_path / "Flux-report.json"
    requested = []
    def choose(parent, title, filename, filters):
        requested.append(filename)
        return str(destination), "JSON (*.json)"
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", choose)
    window.export_report()
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert requested == ["Flux-report.json"]
    assert report["application"] == "Flux"
    assert report["version"] == VERSION
    assert report["jobs"] == window.queue.jobs


def test_legacy_settings_queue_and_presets_survive(application, isolated, tmp_path):
    output = str(tmp_path / "existing-output")
    saved = {"output_dir": output, "concurrency": 3, "motion_intensity": 75, "motion_enabled": False}
    old_job = {"id": "legacy-job", "kind": "audio", "operation": "convert", "inputs": [str(tmp_path / "old.wav")], "status": "success", "options": {"output_dir": output}, "logs": ["old log preserved"]}
    presets = {"我的旧预设": {"kind": "video", "operation": "convert", "values": {"format": "mp4", "quality": 18}}}
    write_json(isolated / "settings.json", saved)
    write_json(isolated / "queue.json", [old_job])
    write_json(isolated / "presets.json", presets)
    window = ui.MainWindow()
    try:
        assert window.preferences["output_dir"] == output
        assert window.preferences["concurrency"] == 3
        assert window.motion.intensity == 0.75
        assert not window.motion.enabled
        assert window.queue.jobs == [old_job]
        assert window.inspector.presets == presets
        assert paths.defaults()["output_dir"] == str(Path.home() / "Downloads/MediaWorkbench")
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_frozen_workers_use_renamed_executable(monkeypatch, tmp_path):
    binary = str(tmp_path / "Flux.exe")
    job = tmp_path / "job.json"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", binary)
    assert paths.worker_command(job) == (binary, ["--worker", str(job)])
