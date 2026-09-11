from __future__ import annotations

import pytest
from PIL import Image, ImageChops, ImageStat
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtTest import QTest

from studio.motion import glyph_mask, pillow_image
from studio.ui import MainWindow
from test_ui import application, isolated, wait_until


@pytest.fixture
def window(application, isolated):
    window = MainWindow()
    window.show()
    application.processEvents()
    yield window
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_glyph_mask_rejects_dark_and_accent_backgrounds():
    image = Image.new("RGBA", (4, 1))
    image.putdata([(16, 17, 18, 255), (94, 106, 210, 255), (231, 232, 236, 255), (150, 155, 166, 255)])
    assert list(glyph_mask(image).get_flattened_data()) == [0, 0, 255, 180]


def test_sidebar_navigation_only(window, application):
    window.navigate("audio")
    assert not window.motion.navigation.active
    window.nav_buttons["video"].click()
    assert window.motion.navigation.phase == "out"
    assert window.current_view == "audio"
    assert window.motion.navigation.sprites
    wait_until(application, lambda: not window.motion.navigation.active, 4)
    assert window.current_view == "video"
    window.inspector.operation.setCurrentIndex(1)
    assert not window.motion.navigation.active
    window.nav_buttons["video"].click()
    assert not window.motion.navigation.active


def test_rapid_sidebar_clicks_keep_latest_target(window, application):
    window.nav_buttons["video"].click()
    window.nav_buttons["audio"].click()
    window.nav_buttons["image"].click()
    wait_until(application, lambda: window.motion.navigation.phase == "in", 4)
    assert window.current_view == "image"
    window.nav_buttons["settings"].click()
    window.nav_buttons["queue"].click()
    wait_until(application, lambda: not window.motion.navigation.active, 5)
    assert window.current_view == "queue"
    assert window.nav_buttons["queue"].isChecked()


@pytest.mark.parametrize("action", ["disable", "resize", "direct", "hide"])
def test_interrupted_navigation_settles(window, action, application):
    window.motion.sidebar("settings")
    if action == "disable":
        window.motion.configure({"motion_enabled": False})
    elif action == "resize":
        window.resize(1200, 800)
    elif action == "hide":
        window.hide()
    else:
        window.navigate("audio")
    application.processEvents()
    assert not window.motion.navigation.active
    assert window.current_view == ("audio" if action == "direct" else "settings")
    assert not window.motion.navigation.isVisible()


def test_halo_lights_actual_text_and_stops_idle_timer(window, application):
    motion = window.motion
    motion.configure({"motion_enabled": False})
    title = window.page_title
    origin = title.mapTo(window, QPoint())
    region = (origin.x(), origin.y(), origin.x() + title.width(), origin.y() + title.height())
    baseline = pillow_image(window.grab().toImage())
    ratio = window.devicePixelRatioF()
    region = tuple(round(value * ratio) for value in region)
    baseline_text = baseline.crop(region)
    motion.configure({"motion_enabled": True})
    center = title.mapToGlobal(QPoint(min(80, title.width() // 2), title.height() // 2))
    motion.move_pointer(QPointF(center))
    wait_until(application, lambda: not motion.timer.isActive(), 4)
    assert motion.opacity == 1
    illuminated = pillow_image(window.grab().toImage()).crop(region)
    difference = ImageChops.difference(baseline_text, illuminated).convert("RGB")
    mask = glyph_mask(baseline_text)
    assert sum(ImageStat.Stat(difference, mask).mean) > 8
    assert not motion.effects[0].cached_glow.isNull()
    motion.inside = False
    motion.wake()
    wait_until(application, lambda: not motion.timer.isActive(), 4)
    assert motion.opacity == 0
    assert not any(effect.isEnabled() for effect in motion.effects)


def test_ripples_bounded_and_expire(window, application):
    motion = window.motion
    for index in range(12):
        motion.press(QPointF(window.mapToGlobal(QPoint(400 + index * 3, 300))))
    assert len(motion.ripples) == 6
    wait_until(application, lambda: not motion.ripples, 4)
    wait_until(application, lambda: not motion.timer.isActive(), 4)


def test_mouse_events_preserve_input_editing(window, application):
    window.navigate("settings")
    control = window.settings_controls["output_dir"]
    QTest.mouseClick(control, Qt.MouseButton.LeftButton)
    assert control.hasFocus()
    assert window.motion.ripples
    control.selectAll()
    QTest.keyClicks(control, "C:/motion-test")
    assert control.text() == "C:/motion-test"
    assert not window.motion.navigation.active


def test_settings_live_preview_and_save(window, application):
    window.navigate("settings")
    window.settings_controls["motion_intensity"].setValue(70)
    assert window.motion.intensity == 0.7
    window.settings_controls["motion_enabled"].setChecked(False)
    assert not window.motion.enabled
    window.apply_settings()
    assert window.preferences["motion_enabled"] is False
    assert window.preferences["motion_intensity"] == 70
    window.nav_buttons["audio"].click()
    assert window.current_view == "audio"
    assert not window.motion.navigation.active


def test_text_layer_preserves_panels(window, application):
    navigation = window.motion.navigation
    original = pillow_image(window.pages.grab().toImage())
    navigation.begin("audio")
    background = pillow_image(navigation.background.toImage())
    difference = ImageChops.difference(original, background).convert("RGB")
    channels = difference.split()
    mask = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2]).point(lambda value: 255 if value > 4 else 0)
    coverage = ImageStat.Stat(mask).mean[0] / 255
    assert 0.002 < coverage < 0.12
    assert len(navigation.sprites) >= 5
    assert window.queue_timer.isActive()
    assert window.status_timer.isActive()


def test_close_stops_animation_resources(window):
    motion = window.motion
    motion.sidebar("queue")
    motion.press(QPointF(window.mapToGlobal(QPoint(450, 300))))
    window.close()
    assert motion.closed
    assert not motion.timer.isActive()
    assert not motion.navigation.active


@pytest.mark.parametrize("region", ["blank", "table", "status", "log"])
def test_pointer_and_ripple_across_client_area(window, application, region):
    if region == "log":
        window.navigate("queue")
        window.log_view.setPlainText("FFmpeg · 转码进度 50%\n日志更新不触发转场")
        widget = window.log_view.viewport()
    else:
        widget = {"blank": window.page_title, "table": window.files_table.viewport(), "status": window.statusBar()}[region]
    QTest.mouseMove(widget, QPoint(20, 10))
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(20, 10))
    application.processEvents()
    assert window.motion.inside
    assert window.motion.ripples
    assert not window.motion.navigation.active
    assert not window.grab().isNull()


def test_tasks_complete_during_navigation(window, application, media, tmp_path):
    options = {**window.preferences, "format": "flac", "output_dir": str(tmp_path / "results")}
    job = window.queue.add([str(media["audio"])], "audio", "convert", options)
    window.queue.start()
    window.motion.sidebar("queue")
    assert window.motion.navigation.active
    wait_until(application, lambda: job["status"] == "success", 15)
    wait_until(application, lambda: not window.motion.navigation.active, 4)
    assert window.current_view == "queue"
    assert window.queue_table.rowCount() == 1


def test_shortcut_settles_transition_before_dispatch(window, application):
    window.motion.sidebar("settings")
    QTest.keyClick(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    QTest.keyRelease(window, Qt.Key.Key_Control)
    application.processEvents()
    assert not window.motion.navigation.active
    assert window.current_view == "queue"
