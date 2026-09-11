from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from studio import paths, tasks, ui
from studio.paths import BUNDLED_PATHS, defaults, engine_path, portable_resources, resource_path, write_json
from test_motion import window
from test_ui import application, isolated, wait_until


def old_options(root):
    return {**defaults(), **{name: str(root / relative) for name, relative in BUNDLED_PATHS.items()}}


def test_defaults_are_installation_relative():
    options = defaults()
    for name, relative in BUNDLED_PATHS.items():
        assert options[name] == "@app/" + relative.as_posix()
        assert resource_path(options[name]) == paths.ROOT / relative


def test_relative_resources_ignore_working_directory(tmp_path, monkeypatch):
    expected = engine_path("ffmpeg", defaults())
    monkeypatch.chdir(tmp_path)
    assert engine_path("ffmpeg", defaults()) == expected
    assert resource_path("engines") == paths.ROOT / "engines"


@pytest.mark.parametrize("exists", [True, False])
def test_legacy_bundled_paths_follow_new_root(tmp_path, monkeypatch, exists):
    origin = tmp_path / "old installation/_internal"
    current = tmp_path / "moved installation/_internal"
    if exists:
        origin.mkdir(parents=True)
        (origin.parent / "Flux.exe").touch()
    monkeypatch.setattr(paths, "ROOT", current)
    migrated = portable_resources(old_options(origin))
    for name, relative in BUNDLED_PATHS.items():
        assert migrated[name] == "@app/" + relative.as_posix()
        assert resource_path(migrated[name]) == current / relative


def test_custom_paths_do_not_get_silently_replaced(tmp_path, monkeypatch, isolated):
    custom = {"ffmpeg_dir": str(tmp_path / "external ffmpeg"), "key_file": str(tmp_path / "my keys/custom.xz"), "signature_file": str(tmp_path / "custom.json"), "output_dir": str(tmp_path / "my media"), "kgg_db_path": str(tmp_path / "KGMusicV3.db")}
    write_json(isolated / "settings.json", custom)
    loaded = paths.settings()
    for name, value in custom.items():
        assert loaded[name] == value
    with pytest.raises(ValueError, match="找不到 ffmpeg"):
        engine_path("ffmpeg", loaded)


def test_legacy_bundled_and_custom_keys_can_coexist(tmp_path):
    origin = tmp_path / "old/_internal"
    options = old_options(origin)
    options["key_file"] = str(tmp_path / "custom-key.xz")
    normalized = portable_resources(options)
    assert normalized["ffmpeg_dir"] == "@app/engines"
    assert normalized["signature_file"].startswith("@app/")
    assert normalized["key_file"] == options["key_file"]


def test_custom_engine_named_engines_is_not_mistaken_for_bundle(tmp_path):
    options = {"ffmpeg_dir": str(tmp_path / "my tools/engines")}
    assert portable_resources(options) == options


@pytest.mark.parametrize("value", ["@app/../outside", "@app/C:/outside", "@app//outside", "@app/\\outside"])
def test_resource_marker_cannot_escape_root(value):
    with pytest.raises(ValueError, match="资源目录"):
        resource_path(value)


def test_settings_save_relative_resources(window, isolated):
    window.preferences.update({name: str(paths.ROOT / relative) for name, relative in BUNDLED_PATHS.items()})
    window.save_preferences()
    saved = json.loads((isolated / "settings.json").read_text(encoding="utf-8"))
    assert saved["ffmpeg_dir"] == "@app/engines"
    assert saved["key_file"] == "@app/engines/kugou_key.xz"


def test_pending_legacy_queue_runs_with_current_engine(application, isolated, tmp_path, media):
    options = old_options(tmp_path / "old deleted installation/_internal")
    options.update(output_dir=str(tmp_path / "results"), format="flac")
    legacy = {"id": "ab" * 16, "inputs": [str(media["audio"])], "options": options, "kind": "audio", "operation": "convert", "status": "pending", "logs": [], "progress": 0}
    write_json(isolated / "queue.json", [legacy])
    queue = tasks.TaskQueue(defaults())
    try:
        assert queue.jobs[0]["options"]["ffmpeg_dir"] == "@app/engines"
        queue.start()
        wait_until(application, lambda: not queue.active)
        assert queue.jobs[0]["status"] == "success"
        assert Path(queue.jobs[0]["output"]).is_file()
        stored = json.loads((isolated / "jobs" / (legacy["id"] + ".json")).read_text(encoding="utf-8"))
        assert stored["options"]["ffmpeg_dir"] == "@app/engines"
        assert stored["inputs"] == legacy["inputs"]
        assert stored["options"]["output_dir"] == options["output_dir"]
    finally:
        queue.shutdown()
        queue.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_missing_custom_engine_does_not_fall_back_on_queue_launch(application, isolated, tmp_path, media):
    queue = tasks.TaskQueue(defaults())
    options = {**defaults(), "ffmpeg_dir": str(tmp_path / "missing custom engine"), "output_dir": str(tmp_path / "results"), "format": "flac"}
    try:
        job = queue.add([str(media["audio"])], "audio", "convert", options)
        queue.start()
        wait_until(application, lambda: not queue.active)
        assert job["status"] == "failed"
        assert job["options"]["ffmpeg_dir"] == options["ffmpeg_dir"]
    finally:
        queue.shutdown()
        queue.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
