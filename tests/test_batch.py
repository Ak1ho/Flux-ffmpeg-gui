from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel, Qt
from PySide6.QtTest import QTest

from studio.catalog import OPERATIONS
from studio.ui import MainWindow
from test_ui import application, isolated, wait_until


@pytest.fixture
def window(application, isolated):
    window = MainWindow()
    window.show()
    application.processEvents()
    yield window
    wait_until(application, lambda: not window.workers)
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def videos(media, tmp_path):
    folder = tmp_path / "batch-inputs"
    folder.mkdir()
    files = [folder / f"片段 {index}.mp4" for index in range(3)]
    for path in files:
        shutil.copy2(media["video"], path)
    return files


@pytest.mark.parametrize("folder_import", [False, True])
@pytest.mark.parametrize("start", [False, True])
def test_import_batch_enqueues_every_file(window, application, videos, tmp_path, folder_import, start):
    errors = []
    window.error = errors.append
    window.inspector.output.setText(str(tmp_path / "results"))
    window.queue.preferences["concurrency"] = 1
    window.import_paths([str(videos[0].parent)] if folder_import else [str(path) for path in videos])
    wait_until(application, lambda: len(window.files) == 3)
    window.navigate("video")
    assert set(window.selected_paths()) == {str(path) for path in videos}
    assert "3 个素材" in window.inspector.selection_text.text()
    panel = window.inspector
    panel.operation.setCurrentIndex(panel.operation.findData("compress"))
    QTest.mouseClick(panel.start_button if start else panel.queue_button, Qt.MouseButton.LeftButton)
    assert not errors
    assert len(window.queue.jobs) == 3
    assert {job["inputs"][0] for job in window.queue.jobs} == {str(path) for path in videos}
    assert all(job["kind"] == "video" and job["operation"] == "compress" for job in window.queue.jobs)
    if start:
        wait_until(application, lambda: all(job["status"] == "success" for job in window.queue.jobs))
        assert all(Path(job["output"]).is_file() for job in window.queue.jobs)
    else:
        assert all(job["status"] == "pending" for job in window.queue.jobs)


@pytest.mark.parametrize("kind,operation,title", [(kind, operation, title) for kind, operations in OPERATIONS.items() for operation, title in operations])
def test_queue_operation_label_uses_media_kind(window, media, kind, operation, title):
    window.queue.add([str(media["video"])], kind, operation, {"format": "mp4"})
    window.refresh_queue()
    assert window.queue_table.item(0, 1).text() == title + " → MP4"


def test_batch_respects_explicit_subset_and_refresh(window, application, videos, tmp_path):
    window.inspector.output.setText(str(tmp_path / "results"))
    window.import_paths([str(path) for path in videos])
    wait_until(application, lambda: len(window.files) == 3)
    window.files_table.clearSelection()
    selection = window.files_table.selectionModel()
    for row in (0, 2):
        selection.select(window.files_table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    expected = set(window.selected_paths())
    window.refresh_files()
    window.enqueue_files(False)
    assert len(window.queue.jobs) == 2
    assert {job["inputs"][0] for job in window.queue.jobs} == expected


def test_imported_batch_concat_is_one_multi_input_job(window, application, videos, tmp_path):
    errors = []
    window.error = errors.append
    window.inspector.output.setText(str(tmp_path / "results"))
    window.import_paths([str(path) for path in videos])
    wait_until(application, lambda: len(window.files) == 3)
    window.inspector.operation.setCurrentIndex(window.inspector.operation.findData("concat"))
    window.enqueue_files(False)
    assert not errors
    assert len(window.queue.jobs) == 1
    assert window.queue.jobs[0]["inputs"] == [item["path"] for item in window.visible_files()]


def test_filter_limits_batch_to_visible_files(window, application, videos, tmp_path):
    window.inspector.output.setText(str(tmp_path / "results"))
    window.import_paths([str(path) for path in videos])
    wait_until(application, lambda: len(window.files) == 3)
    window.search.setText(videos[1].stem)
    window.enqueue_files(False)
    assert len(window.queue.jobs) == 1
    assert window.queue.jobs[0]["inputs"] == [str(videos[1])]


def test_duplicate_import_does_not_expand_manual_selection(window, application, videos):
    window.import_paths([str(path) for path in videos])
    wait_until(application, lambda: len(window.files) == 3)
    window.files_table.selectRow(1)
    selected = window.selected_paths()
    window.scan_finished(None, {"files": list(window.files), "rejected": 0, "errors": []})
    assert window.selected_paths() == selected
    assert len(window.files) == 3


def test_additional_import_extends_visible_selection(window, application, videos):
    window.import_paths([str(videos[0])])
    wait_until(application, lambda: len(window.files) == 1)
    window.import_paths([str(path) for path in videos[1:]])
    wait_until(application, lambda: len(window.files) == 3)
    assert set(window.selected_paths()) == {str(path) for path in videos}
    assert "3 个素材" in window.inspector.selection_text.text()


def test_mixed_batch_requires_classification_before_enqueue(window, application, videos, media, tmp_path):
    errors = []
    window.error = errors.append
    window.inspector.output.setText(str(tmp_path / "results"))
    window.import_paths([str(path) for path in videos] + [str(media["audio"])])
    wait_until(application, lambda: len(window.files) == 4)
    window.enqueue_files(False)
    assert len(errors) == 1 and "同一类型" in str(errors[0])
    assert not window.queue.jobs
    window.navigate("video")
    window.enqueue_files(False)
    assert len(errors) == 1
    assert len(window.queue.jobs) == 3
    assert all(job["kind"] == "video" for job in window.queue.jobs)
