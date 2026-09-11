from __future__ import annotations

import math
import time

from PIL import Image, ImageChops, ImageFilter
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QGraphicsEffect, QLabel, QWidget


def pillow_image(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes("RGBA", (image.width(), image.height()), bytes(image.constBits()), "raw", "RGBA", image.bytesPerLine())


def qt_image(image):
    image = image.convert("RGBA")
    return QImage(image.tobytes(), image.width, image.height, image.width * 4, QImage.Format.Format_RGBA8888).copy()


def glyph_mask(image):
    red, green, blue, alpha = image.convert("RGBA").split()
    low = ImageChops.darker(ImageChops.darker(red, green), blue)
    high = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    neutral = ImageChops.subtract(high, low).point(lambda value: 255 if value < 110 else 0)
    bright = low.point(lambda value: max(0, min(255, (value - 90) * 3)))
    return ImageChops.multiply(ImageChops.multiply(bright, neutral), alpha)


class LightEffect(QGraphicsEffect):
    def __init__(self, surface, controller):
        super().__init__(surface)
        self.surface = surface
        self.controller = controller
        self.cached_key = None
        self.cached_glow = QImage()
        self.setEnabled(False)

    def draw(self, painter):
        controller = self.controller
        if controller.closed or controller.capturing:
            self.drawSource(painter)
            return
        offset = QPoint()
        source = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates, offset, QGraphicsEffect.PixmapPadMode.NoPad)
        if source.isNull():
            return
        painter.drawPixmap(offset, source)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        position = self.surface.mapFromGlobal(controller.position.toPoint())
        radius = controller.radius
        if controller.halo and controller.opacity > 0.001:
            strength = controller.opacity * controller.intensity
            gradient = QRadialGradient(QPointF(position), radius)
            gradient.setColorAt(0, QColor(111, 119, 255, round(28 * strength)))
            gradient.setColorAt(0.45, QColor(94, 106, 210, round(13 * strength)))
            gradient.setColorAt(1, QColor(94, 106, 210, 0))
            painter.fillRect(self.surface.rect(), gradient)
            crop = QRect(position.x() - radius, position.y() - radius, radius * 2, radius * 2)
            visible = crop.intersected(self.surface.rect())
            if not visible.isEmpty():
                key = (source.cacheKey(), crop.x(), crop.y(), source.devicePixelRatio())
                if key != self.cached_key:
                    ratio = source.devicePixelRatio()
                    physical = QRect(round((visible.x() - offset.x()) * ratio), round((visible.y() - offset.y()) * ratio), round(visible.width() * ratio), round(visible.height() * ratio))
                    image = pillow_image(source.copy(physical).toImage()).resize((visible.width(), visible.height()), Image.Resampling.BILINEAR)
                    mask = glyph_mask(image)
                    for label in self.surface.findChildren(QLabel):
                        if label.isVisible() and label.pixmap() is not None and not label.pixmap().isNull():
                            origin = label.mapTo(self.surface, QPoint()) - visible.topLeft()
                            mask.paste(0, (origin.x(), origin.y(), origin.x() + label.width(), origin.y() + label.height()))
                    radial = controller.radial.crop((visible.x() - crop.x(), visible.y() - crop.y(), visible.right() - crop.x() + 1, visible.bottom() - crop.y() + 1))
                    mask = ImageChops.multiply(mask, radial)
                    bloom = ImageChops.add(mask.filter(ImageFilter.GaussianBlur(4)), mask.filter(ImageFilter.GaussianBlur(11)))
                    glow = Image.new("RGBA", mask.size, (130, 144, 255, 0))
                    glow.putalpha(ImageChops.add(bloom, mask.point(lambda value: round(value * 0.32))))
                    self.cached_glow = qt_image(glow)
                    self.cached_key = key
                painter.setOpacity(min(1, strength * 0.9))
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
                painter.drawImage(visible.topLeft(), self.cached_glow)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                painter.setOpacity(1)
        now = controller.now
        for point, started in controller.ripples:
            progress = min(1, max(0, (now - started) / 0.68))
            center = self.surface.mapFromGlobal(point.toPoint())
            expansion = 8 + 155 * (1 - (1 - progress) ** 2)
            opacity = (1 - progress) ** 2 * controller.intensity
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(158, 170, 255, min(255, round(150 * opacity))), 1.4))
            painter.drawEllipse(QPointF(center), expansion, expansion)
            painter.setPen(QPen(QColor(112, 125, 238, min(255, round(65 * opacity))), 3))
            painter.drawEllipse(QPointF(center), expansion * 0.78, expansion * 0.78)
        painter.restore()


TEXTLESS = """
QLabel, QPushButton, QToolButton, QComboBox, QLineEdit, QAbstractSpinBox,
QPlainTextEdit, QTextEdit, QCheckBox, QRadioButton, QGroupBox,
QTableView, QHeaderView, QProgressBar {
    color: transparent; selection-color: transparent;
}
QTableView::item, QTableView::item:selected, QHeaderView::section {
    color: transparent; selection-color: transparent;
}
"""


class TextTransition(QWidget):
    def __init__(self, controller):
        super().__init__(controller.window.pages)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.background = QPixmap()
        self.sprites = []
        self.phase = ""
        self.started = 0.0
        self.target = None
        self.pending = None
        self.committing = False
        self.hide()

    @property
    def active(self):
        return bool(self.phase)

    def capture(self):
        pages = self.controller.window.pages
        self.hide()
        self.controller.capturing = True
        original = pages.styleSheet()
        try:
            full = pages.grab()
            pages.setStyleSheet(original + TEXTLESS)
            self.background = pages.grab()
        finally:
            pages.setStyleSheet(original)
            self.controller.capturing = False
        foreground = pillow_image(full.toImage())
        background = pillow_image(self.background.toImage())
        difference = ImageChops.difference(foreground, background).convert("RGB")
        channels = difference.split()
        mask = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2]).point(lambda value: 255 if value > 4 else 0)
        ratio = full.devicePixelRatio()
        rows = mask.resize((1, mask.height), Image.Resampling.BOX)
        spans = []
        start = None
        for row in range(mask.height + 1):
            occupied = row < mask.height and rows.getpixel((0, row)) > 0
            if occupied and start is None:
                start = row
            if not occupied and start is not None:
                if spans and start - spans[-1][1] < round(4 * ratio):
                    spans[-1] = (spans[-1][0], row)
                else:
                    spans.append((start, row))
                start = None
        self.sprites = []
        for top, bottom in spans:
            bounds = mask.crop((0, top, mask.width, bottom)).getbbox()
            if bounds is None:
                continue
            left, _, right, _ = bounds
            box = (left, top, right, bottom)
            sprite = foreground.crop(box)
            sprite.putalpha(mask.crop(box))
            self.sprites.append((QRectF(left / ratio, top / ratio, (right - left) / ratio, (bottom - top) / ratio), qt_image(sprite)))
        self.setGeometry(pages.rect())
        self.show()
        self.raise_()

    def begin(self, view):
        window = self.controller.window
        if self.phase == "out":
            self.target = view
            return
        if self.phase == "in":
            self.pending = view
            return
        if view == window.current_view:
            return
        self.target = view
        self.phase = "out"
        self.capture()
        self.started = time.monotonic()
        self.controller.wake()

    def commit(self, view):
        self.committing = True
        try:
            self.controller.window.navigate(view)
        finally:
            self.committing = False

    def finish(self, settle=True):
        target = self.pending or self.target
        self.phase = ""
        self.pending = None
        self.target = None
        self.hide()
        self.sprites.clear()
        self.background = QPixmap()
        if settle and target and self.controller.window.current_view != target:
            self.commit(target)

    def advance(self, now):
        elapsed = now - self.started
        if self.phase == "out" and elapsed >= 0.16:
            self.hide()
            self.commit(self.target)
            self.capture()
            self.phase = "in"
            self.started = time.monotonic()
        elif self.phase == "in" and elapsed >= 0.36:
            pending = self.pending
            self.finish(False)
            if pending:
                self.begin(pending)
        if self.active:
            self.update()

    def paintEvent(self, event):
        if not self.active:
            return
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.background)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        elapsed = max(0, self.controller.now - self.started)
        for rect, sprite in self.sprites:
            stagger = 0.035 * rect.top() / max(1, self.height())
            if self.phase == "out":
                progress = min(1, max(0, (elapsed - stagger) / 0.125))
                scale = 1 - 0.24 * progress ** 2
                shift = -9 * progress ** 2
                opacity = 1 - progress ** 2
            else:
                progress = min(1, max(0, (elapsed - stagger) / 0.32))
                eased = 1 + 2.2 * (progress - 1) ** 3 + 1.2 * (progress - 1) ** 2
                scale = 0.8 + 0.2 * eased
                shift = 12 * (1 - eased)
                opacity = min(1, progress * 4)
            target = QRectF(rect.left(), rect.center().y() - rect.height() * scale / 2 + shift, rect.width(), rect.height() * scale)
            painter.setOpacity(opacity)
            painter.drawImage(target, sprite)


class MotionController(QObject):
    radius = 180

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.closed = False
        self.capturing = False
        self.position = QPointF(-1000, -1000)
        self.target_position = QPointF(self.position)
        self.opacity = 0.0
        self.inside = False
        self.ripples = []
        self.now = time.monotonic()
        self.last_press = (QPointF(-1000, -1000), 0.0)
        radial = Image.new("L", (128, 128))
        radial.putdata([round(255 * max(0, 1 - math.hypot((column - 63.5) / 63.5, (row - 63.5) / 63.5)) ** 1.35) for row in range(128) for column in range(128)])
        self.radial = radial.resize((self.radius * 2, self.radius * 2), Image.Resampling.BILINEAR)
        self.effects = []
        for surface in (window.centralWidget(), window.statusBar()):
            effect = LightEffect(surface, self)
            surface.setGraphicsEffect(effect)
            self.effects.append(effect)
        self.navigation = TextTransition(self)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.configure(window.preferences)
        for widget in [window, *window.findChildren(QWidget)]:
            widget.setMouseTracking(True)
        QApplication.instance().installEventFilter(self)

    def configure(self, preferences):
        self.enabled = bool(preferences.get("motion_enabled", True))
        self.halo = self.enabled and bool(preferences.get("motion_halo", True))
        self.ripple = self.enabled and bool(preferences.get("motion_ripple", True))
        self.transitions = self.enabled and bool(preferences.get("motion_navigation", True))
        self.intensity = max(0.3, min(1.5, float(preferences.get("motion_intensity", 100)) / 100))
        if not self.transitions:
            self.navigation.finish()
        if not self.ripple:
            self.ripples.clear()
        if not self.halo:
            self.opacity = 0
        self.tick()

    def sidebar(self, view):
        if self.transitions and self.window.isVisible() and not self.window.isMinimized():
            self.navigation.begin(view)
        else:
            self.window.navigate(view)

    def wake(self):
        if not self.closed and not self.timer.isActive():
            self.now = time.monotonic()
            self.timer.start()

    def move_pointer(self, position):
        if not self.enabled:
            return
        if not self.inside:
            self.position = QPointF(position)
        self.target_position = QPointF(position)
        self.inside = True
        if self.halo:
            self.wake()

    def press(self, position):
        if not self.ripple:
            return
        now = time.monotonic()
        if self.last_press[0] == position and now - self.last_press[1] < 0.025:
            return
        self.last_press = (QPointF(position), now)
        self.ripples = (self.ripples + [(QPointF(position), now)])[-6:]
        self.wake()

    def tick(self):
        if self.closed:
            return
        now = time.monotonic()
        delta = min(0.1, max(0.001, now - self.now))
        self.now = now
        blend = 1 - math.exp(-delta / 0.045)
        self.position += (self.target_position - self.position) * blend
        target = 1.0 if self.inside and self.halo else 0.0
        self.opacity += (target - self.opacity) * (1 - math.exp(-delta / 0.07))
        self.ripples = [(point, started) for point, started in self.ripples if now - started < 0.68]
        if self.navigation.active:
            self.navigation.advance(now)
        moving = (self.target_position - self.position).manhattanLength() > 0.2
        fading = abs(target - self.opacity) > 0.003
        if not fading:
            self.opacity = target
        for effect in self.effects:
            effect.setEnabled(self.enabled and (self.opacity > 0 or bool(self.ripples)))
            if effect.isEnabled():
                effect.update()
        if not ((self.halo and moving) or fading or self.ripples or self.navigation.active):
            self.timer.stop()

    def eventFilter(self, watched, event):
        kind = event.type()
        if self.closed:
            return False
        if kind == QEvent.Type.ChildPolished:
            child = event.child()
            if isinstance(child, QWidget) and child.window() == self.window:
                child.setMouseTracking(True)
        elif kind in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            if isinstance(watched, QWidget) and watched.window() == self.window:
                position = event.globalPosition()
                self.move_pointer(position)
                if kind != QEvent.Type.MouseMove:
                    self.press(position)
        elif watched == self.window:
            if kind in (QEvent.Type.Leave, QEvent.Type.WindowDeactivate, QEvent.Type.Hide):
                self.inside = False
                self.wake()
                if kind != QEvent.Type.Leave:
                    self.navigation.finish()
            elif kind in (QEvent.Type.Resize, QEvent.Type.WindowStateChange):
                self.navigation.finish()
        elif kind in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride) and self.navigation.active:
            if isinstance(watched, QWidget) and watched.window() == self.window:
                self.navigation.finish()
        return False

    def close(self):
        self.closed = True
        self.timer.stop()
        self.navigation.finish(False)
        QApplication.instance().removeEventFilter(self)
        for effect in self.effects:
            effect.setEnabled(False)
