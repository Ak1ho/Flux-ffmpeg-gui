from __future__ import annotations

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QStandardItem, QStandardItemModel, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QLabel, QScrollArea, QSpinBox, QVBoxLayout, QWidget

from studio.controls import AnimatedComboBox, DropdownPopup, ScrollSafeDoubleSpinBox, ScrollSafeSpinBox
from studio.widgets import combo, spin
from test_motion import window
from test_ui import application, isolated, wait_until


@pytest.fixture
def controls(application):
    host = QWidget()
    layout = QVBoxLayout(host)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    body = QWidget()
    content = QVBoxLayout(body)
    dropdown = combo([(f"选项 {index:02}", index) for index in range(35)])
    integer = spin(0, 100, 25)
    decimal = spin(0, 10, 1.5, 2)
    for widget in (dropdown, integer, decimal):
        content.addWidget(widget)
    content.addWidget(QLabel("滚轮仅滚动页面"))
    content.addSpacing(900)
    scroll.setWidget(body)
    layout.addWidget(scroll)
    host.resize(420, 400)
    host.show()
    host.activateWindow()
    application.processEvents()
    yield host, scroll, dropdown, integer, decimal
    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def open_dropdown(application, dropdown):
    QTest.mouseClick(dropdown, Qt.MouseButton.LeftButton)
    popup = dropdown.popup
    assert isinstance(popup, DropdownPopup)
    wait_until(application, lambda: popup.isVisible() and popup.animation.state() == QAbstractAnimation.State.Stopped, 3)
    return popup


def current_value(widget):
    return widget.currentIndex() if isinstance(widget, QComboBox) else widget.value()


def test_all_application_parameter_widgets_are_scroll_safe(window):
    dropdowns = window.findChildren(QComboBox)
    integers = window.findChildren(QSpinBox)
    decimals = window.findChildren(QDoubleSpinBox)
    assert len(dropdowns) >= 10 and len(integers) >= 8 and len(decimals) >= 5
    assert all(isinstance(widget, AnimatedComboBox) for widget in dropdowns)
    assert all(isinstance(widget, ScrollSafeSpinBox) for widget in integers)
    assert all(isinstance(widget, ScrollSafeDoubleSpinBox) for widget in decimals)


@pytest.mark.parametrize("widget_index", [2, 3, 4])
@pytest.mark.parametrize("focused", [False, True])
def test_wheel_never_changes_parameter(controls, application, widget_index, focused):
    host, scroll, *widgets = controls
    widget = controls[widget_index]
    if focused:
        widget.setFocus()
    else:
        widget.clearFocus()
    before = current_value(widget)
    center = widget.rect().center()
    for delta in (-120, 120, -360):
        event = QWheelEvent(QPointF(center), QPointF(widget.mapToGlobal(center)), QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget, event)
        assert not event.isAccepted()
        assert current_value(widget) == before


@pytest.mark.parametrize("widget_index", [2, 3, 4])
def test_real_wheel_over_parameter_scrolls_page(controls, application, widget_index):
    host, scroll, *widgets = controls
    widget = controls[widget_index]
    scroll.ensureWidgetVisible(widget)
    widget.setFocus()
    application.processEvents()
    before_value = current_value(widget)
    before_scroll = scroll.verticalScrollBar().value()
    position = widget.mapTo(host, widget.rect().center())
    QTest.wheelEvent(host.windowHandle(), position, QPoint(0, -120))
    application.processEvents()
    assert current_value(widget) == before_value
    assert scroll.verticalScrollBar().value() > before_scroll


@pytest.mark.parametrize("widget_index", [3, 4])
@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("touchpad", [False, True])
def test_wheel_over_internal_editor_preserves_value(controls, application, widget_index, focused, touchpad):
    host, scroll, dropdown, integer, decimal = controls
    widget = controls[widget_index]
    editor = widget.lineEdit()
    scroll.ensureWidgetVisible(widget)
    if focused:
        editor.setFocus()
    else:
        dropdown.setFocus()
    application.processEvents()
    assert editor.hasFocus() == focused
    before_value = widget.value()
    before_scroll = scroll.verticalScrollBar().value()
    for delta in (-120, 120, -360):
        position = editor.mapTo(host, editor.rect().center())
        assert host.childAt(position) is editor
        QTest.wheelEvent(
            host.windowHandle(), position,
            QPoint() if touchpad else QPoint(0, delta),
            QPoint(0, delta) if touchpad else QPoint(),
            phase=Qt.ScrollPhase.ScrollUpdate if touchpad else Qt.ScrollPhase.NoScrollPhase,
        )
        application.processEvents()
        assert widget.value() == before_value
    if not touchpad:
        assert scroll.verticalScrollBar().value() > before_scroll


@pytest.mark.parametrize("widget_type", [QSpinBox, QDoubleSpinBox, ScrollSafeSpinBox, ScrollSafeDoubleSpinBox])
def test_internal_editor_wheel_differential(application, widget_type):
    host = QWidget()
    layout = QVBoxLayout(host)
    widget = widget_type()
    widget.setValue(25)
    layout.addWidget(widget)
    host.show()
    host.activateWindow()
    widget.lineEdit().setFocus()
    application.processEvents()
    try:
        editor = widget.lineEdit()
        position = editor.mapTo(host, editor.rect().center())
        assert host.childAt(position) is editor
        QTest.wheelEvent(host.windowHandle(), position, QPoint(0, 120))
        application.processEvents()
        if isinstance(widget, (ScrollSafeSpinBox, ScrollSafeDoubleSpinBox)):
            assert widget.value() == 25
        else:
            assert widget.value() > 25
    finally:
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_numbers_still_editable_by_keyboard_and_buttons(controls):
    host, scroll, dropdown, integer, decimal = controls
    for widget, typed in ((integer, "36"), (decimal, "2.75")):
        widget.setFocus()
        widget.selectAll()
        QTest.keyClicks(widget, typed)
        QTest.keyClick(widget, Qt.Key.Key_Return)
        assert widget.value() == float(typed)
        before = widget.value()
        QTest.keyClick(widget, Qt.Key.Key_Up)
        assert widget.value() > before
        before = widget.value()
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(widget.width() - 7, 5))
        assert widget.value() > before


def test_custom_popup_round_corners_and_animation(controls, application):
    dropdown = controls[2]
    dropdown.showPopup()
    popup = dropdown.popup
    assert popup.isVisible()
    assert popup.animation.state() == QAbstractAnimation.State.Running
    popup.animation.setCurrentTime(80)
    assert 0 < dropdown.arrow_progress < 1
    wait_until(application, lambda: popup.animation.state() == QAbstractAnimation.State.Stopped)
    assert dropdown.arrow_progress == 1
    assert dropdown.property("popupOpen") is True
    assert popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert popup.grab().toImage().pixelColor(0, 0).alpha() == 0
    assert dropdown.screen().availableGeometry().contains(popup.geometry())
    dropdown.hidePopup()
    assert popup.animation.state() == QAbstractAnimation.State.Running
    wait_until(application, lambda: not popup.isVisible())
    assert dropdown.arrow_progress == 0
    assert dropdown.property("popupOpen") is False


def test_mouse_selection_commits_once_after_close(controls, application):
    dropdown = controls[2]
    changed, activated, texts = [], [], []
    dropdown.currentIndexChanged.connect(changed.append)
    dropdown.activated.connect(activated.append)
    dropdown.textActivated.connect(texts.append)
    popup = open_dropdown(application, dropdown)
    index = dropdown.model().index(3, 0)
    QTest.mouseClick(popup.list.viewport(), Qt.MouseButton.LeftButton, pos=popup.list.visualRect(index).center())
    assert dropdown.currentIndex() == 0
    wait_until(application, lambda: not popup.isVisible())
    assert dropdown.currentData() == 3
    assert changed == activated == [3]
    assert texts == ["选项 03"]
    assert dropdown.hasFocus()


def test_keyboard_browse_escape_and_commit(controls, application):
    dropdown = controls[2]
    dropdown.setFocus()
    QTest.keyClick(dropdown, Qt.Key.Key_Space)
    popup = dropdown.popup
    QTest.keyClick(popup.list, Qt.Key.Key_Down)
    assert dropdown.currentIndex() == 0
    QTest.keyClick(popup.list, Qt.Key.Key_Escape)
    wait_until(application, lambda: not popup.isVisible())
    assert dropdown.currentIndex() == 0
    QTest.keyClick(dropdown, Qt.Key.Key_F4)
    QTest.keyClick(popup.list, Qt.Key.Key_End)
    QTest.keyClick(popup.list, Qt.Key.Key_Return)
    wait_until(application, lambda: not popup.isVisible())
    assert dropdown.currentIndex() == 34


def test_wheel_in_popup_scrolls_without_selecting(controls, application):
    dropdown = controls[2]
    popup = open_dropdown(application, dropdown)
    QTest.wheelEvent(popup.windowHandle(), QPoint(50, 80), QPoint(0, -480))
    application.processEvents()
    assert dropdown.currentIndex() == 0
    assert popup.list.verticalScrollBar().value() > 0
    QTest.keyClick(popup.list, Qt.Key.Key_Escape)
    wait_until(application, lambda: not popup.isVisible())
    assert dropdown.currentIndex() == 0


def test_hover_highlight_animates_and_stops(controls, application):
    popup = open_dropdown(application, controls[2])
    index = controls[2].model().index(2, 0)
    viewport = popup.list.viewport()
    position = popup.list.visualRect(index).center()
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(position), QPointF(viewport.mapToGlobal(position)), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, event)
    assert popup.list.hover_index.row() == 2
    popup.list.hover_animation.setCurrentTime(popup.list.hover_animation.duration())
    assert popup.list.hover_opacity == 1
    assert popup.list.hover_animation.state() == QAbstractAnimation.State.Stopped
    popup.dismiss(immediate=True)
    assert popup.list.hover_animation.state() == QAbstractAnimation.State.Stopped


@pytest.mark.parametrize("action", ["clear", "insert", "remove", "resize", "hide", "disable", "close"])
def test_popup_lifecycle_does_not_leave_stale_selection(controls, application, action):
    host, scroll, dropdown, integer, decimal = controls
    popup = open_dropdown(application, dropdown)
    popup.choose(dropdown.model().index(3, 0))
    activated = []
    dropdown.activated.connect(activated.append)
    if action == "clear":
        dropdown.clear()
    elif action == "insert":
        dropdown.insertItem(0, "新参数", -1)
    elif action == "remove":
        dropdown.removeItem(3)
    elif action == "resize":
        host.resize(500, 500)
    elif action == "disable":
        dropdown.setEnabled(False)
    elif action == "close":
        host.close()
    else:
        dropdown.hide()
    application.processEvents()
    assert not popup.isVisible()
    assert popup.animation.state() == QAbstractAnimation.State.Stopped
    assert not activated


def test_disabled_rows_cannot_commit(controls, application):
    dropdown = controls[2]
    dropdown.model().item(2).setEnabled(False)
    popup = open_dropdown(application, dropdown)
    popup.choose(dropdown.model().index(2, 0))
    assert not popup.closing
    assert dropdown.currentIndex() == 0


def test_repeated_open_close_and_outside_click(controls, application):
    dropdown = controls[2]
    for iteration in range(4):
        popup = open_dropdown(application, dropdown)
        QTest.keyClick(popup.list, Qt.Key.Key_Escape)
        wait_until(application, lambda: not popup.isVisible())
    popup = open_dropdown(application, dropdown)
    QTest.mouseClick(popup.windowHandle(), Qt.MouseButton.LeftButton, pos=QPoint(-15, 15))
    application.processEvents()
    assert not popup.isVisible()
    assert dropdown.currentIndex() == 0
    assert len(dropdown.findChildren(DropdownPopup)) == 1


def test_popup_respects_motion_switch(window, application):
    dropdown = window.inspector.category
    window.motion.configure({"motion_enabled": False})
    popup = open_dropdown(application, dropdown)
    assert popup.animation.state() == QAbstractAnimation.State.Stopped
    assert dropdown.arrow_progress == 1
    popup.choose(dropdown.model().index(1, 0))
    assert not popup.isVisible()
    assert dropdown.currentIndex() == 1


def test_popup_near_screen_bottom_opens_upward(controls, application):
    host, scroll, dropdown, integer, decimal = controls
    screen = host.screen().availableGeometry()
    host.move(screen.left() + 25, screen.bottom() - 210)
    application.processEvents()
    popup = open_dropdown(application, dropdown)
    assert popup.above
    assert screen.contains(popup.geometry())


def test_parameter_selection_does_not_trigger_page_transition(window, application):
    dropdown = window.inspector.operation
    popup = open_dropdown(application, dropdown)
    popup.choose(dropdown.model().index(1, 0))
    wait_until(application, lambda: not popup.isVisible())
    assert dropdown.currentIndex() == 1
    assert not window.motion.navigation.active


def test_popup_tab_returns_to_form_without_committing(controls, application):
    dropdown = controls[2]
    popup = open_dropdown(application, dropdown)
    QTest.keyClick(popup.list, Qt.Key.Key_Down)
    QTest.keyClick(popup.list, Qt.Key.Key_Tab)
    assert not popup.isVisible()
    assert dropdown.currentIndex() == 0
    assert controls[3].hasFocus()


def test_disabled_and_empty_dropdowns_do_not_open(controls):
    dropdown = controls[2]
    dropdown.setEnabled(False)
    dropdown.showPopup()
    assert dropdown.popup is None
    dropdown.setEnabled(True)
    dropdown.clear()
    dropdown.showPopup()
    assert dropdown.popup is None


def test_model_replacement_cancels_popup_safely(controls, application):
    dropdown = controls[2]
    popup = open_dropdown(application, dropdown)
    model = QStandardItemModel(dropdown)
    model.appendRow(QStandardItem("替换后的选项"))
    dropdown.setModel(model)
    assert not popup.isVisible()
    popup = open_dropdown(application, dropdown)
    assert popup.list.model() == model
    assert dropdown.currentText() == "替换后的选项"


def test_clicking_trigger_twice_closes_without_reopening(controls, application):
    host, scroll, dropdown, integer, decimal = controls
    popup = open_dropdown(application, dropdown)
    position = popup.mapFromGlobal(dropdown.mapToGlobal(dropdown.rect().center()))
    QTest.mouseClick(popup.windowHandle(), Qt.MouseButton.LeftButton, pos=position)
    wait_until(application, lambda: not popup.isVisible())
    QTest.qWait(150)
    assert not popup.isVisible()
    assert dropdown.currentIndex() == 0
