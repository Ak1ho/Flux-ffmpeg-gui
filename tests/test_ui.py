from __future__ import annotations

import json
import time
from pathlib import Path

import psutil
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from studio import inspector, paths, tasks, ui
from studio.catalog import OPERATIONS
from studio.engine import stage_path
from studio.paths import defaults
from studio.theme import STYLE


@pytest.fixture(scope="session")
def application():
    def qt_message(message_type, context, message):
        print("QT:", message, flush=True)
    qInstallMessageHandler(qt_message)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    yield app


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    folder = tmp_path / "state"
    for module in (paths, tasks, inspector, ui):
        monkeypatch.setattr(module, "STATE", folder)
    monkeypatch.setenv("MEDIAWORKBENCH_STATE", str(folder))
    return folder


def wait_until(application, predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        QTest.qWait(25)
    raise AssertionError("Timed out waiting for application state")


def test_all_operation_forms(application, isolated):
    panel = inspector.Inspector(defaults())
    for kind, operations in OPERATIONS.items():
        panel.set_kind(kind)
        for operation, title in operations:
            panel.operation.setCurrentIndex(panel.operation.findData(operation))
            assert panel.operation.currentText() == title
            assert panel.controls["format"].count() > 0
            assert panel.controls["format"].currentData()
    panel.set_kind("video")
    values = panel.options()
    assert values["format"] == "mp4" and values["quality"] == 23
    assert "start" not in values and "width" not in values
    panel.deleteLater()


def test_gui_import_filter_selection_and_enqueue(application, isolated, media, tmp_path):
    window = ui.MainWindow()
    window.show()
    errors = []
    window.error = errors.append
    window.inspector.output.setText(str(tmp_path / "results"))
    window.import_paths([str(media["video"]), str(media["audio"]), str(media["image"])])
    wait_until(application, lambda: len(window.files) == 3)
    window.navigate("video")
    assert window.files_table.rowCount() == 1
    window.files_table.selectRow(0)
    window.refresh_files()
    assert len(window.selected_paths()) == 1
    window.enqueue_files(False)
    assert not errors
    assert len(window.queue.jobs) == 1
    assert window.queue.jobs[0]["status"] == "pending"
    window.navigate("queue")
    window.queue_table.selectRow(0)
    window.refresh_queue()
    assert len(window.selected_job_ids()) == 1
    window.queue.start()
    wait_until(application, lambda: window.queue.jobs[0]["status"] == "success")
    assert Path(window.queue.jobs[0]["output"]).is_file()
    window.navigate("audio")
    assert window.files_table.rowCount() == 1
    window.search.setText("no matching filename")
    assert window.files_table.rowCount() == 0
    window.search.clear()
    window.files_table.selectRow(0)
    window.remove_files()
    assert media["audio"].exists()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def test_queue_parallel_success_and_snapshot(application, isolated, media, tmp_path):
    preferences = defaults()
    preferences.update(output_dir=str(tmp_path / "results"), concurrency=2)
    queue = tasks.TaskQueue(preferences)
    options = {**preferences, "format": "flac"}
    first = queue.add([str(media["audio"])], "audio", "convert", options)
    second = queue.add([str(media["audio"])], "audio", "convert", options)
    options["format"] = "wav"
    assert first["options"]["format"] == "flac"
    queue.start()
    assert len(queue.active) == 2
    wait_until(application, lambda: not queue.active)
    assert first["status"] == second["status"] == "success", [first, second]
    assert first["output"] != second["output"]
    saved = json.loads((isolated / "queue.json").read_text(encoding="utf-8"))
    assert len(saved) == 2 and saved[0]["status"] == "success"
    queue.shutdown()
    queue.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_cancel_child_process_and_retry(application, isolated, media, tmp_path):
    preferences = defaults()
    preferences.update(output_dir=str(tmp_path / "results"), concurrency=1)
    queue = tasks.TaskQueue(preferences)
    job = queue.add([str(media["video"])], "video", "resize", {**preferences, "format": "mp4", "width": 3840, "height": 2160, "encoder": "libx265"})
    pending = queue.add([str(media["audio"])], "audio", "convert", {**preferences, "format": "flac"})
    queue.start()
    wait_until(application, lambda: any("ffmpeg.exe" in line for line in job["logs"]))
    queue.pause()
    process_id = int(queue.active[job["id"]].processId())
    children = psutil.Process(process_id).children(recursive=True)
    queue.cancel(job["id"])
    wait_until(application, lambda: not queue.active)
    assert job["status"] == "cancelled"
    assert pending["status"] == "pending"
    assert not stage_path(job).exists()
    assert all(not child.is_running() for child in children)
    queue.cancel(pending["id"])
    previous_id = job["id"]
    queue.retry(previous_id)
    assert job["status"] == "pending" and job["id"] != previous_id
    job["options"].update(width=160, height=90, encoder="auto")
    queue.start()
    wait_until(application, lambda: job["status"] == "success")
    queue.shutdown()
    queue.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_interrupted_queue_recovery(application, isolated, media, tmp_path):
    preferences = defaults()
    preferences.update(output_dir=str(tmp_path / "results"))
    original = tasks.TaskQueue(preferences)
    job = original.add([str(media["audio"])], "audio", "convert", {**preferences, "format": "flac"})
    job["status"] = "running"
    original.save()
    original.pump_timer.stop()
    recovered = tasks.TaskQueue(preferences)
    assert recovered.jobs[0]["status"] == "interrupted"
    assert not recovered.enabled
    recovered.retry(job["id"])
    recovered.start()
    wait_until(application, lambda: recovered.jobs[0]["status"] == "success")
    recovered.shutdown()
    recovered.deleteLater()
    original.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
