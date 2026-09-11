from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPersistentModelIndex, QPoint, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox, QListView, QSpinBox, QStyle, QStyledItemDelegate, QWidget


class ScrollSafeSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class ScrollSafeDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class OptionList(QListView):
    def __init__(self, parent):
        super().__init__(parent)
        self.hover_index = QPersistentModelIndex()
        self.hover_opacity = 0.0
        self.hover_animation = QVariantAnimation(self)
        self.hover_animation.setDuration(100)
        self.hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.hover_animation.valueChanged.connect(self.update_hover)

    def update_hover(self, opacity):
        self.hover_opacity = float(opacity)
        self.viewport().update()

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if index != self.hover_index:
            self.hover_index = QPersistentModelIndex(index)
            self.hover_animation.stop()
            if self.parentWidget().animated():
                self.hover_animation.setStartValue(0.0)
                self.hover_animation.setEndValue(1.0)
                self.hover_animation.start()
            else:
                self.update_hover(1.0)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_animation.stop()
        self.hover_index = QPersistentModelIndex()
        self.update_hover(0.0)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.hover_animation.stop()
        self.hover_index = QPersistentModelIndex()
        self.hover_opacity = 0.0
        super().hideEvent(event)


class OptionDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(160, 36)

    def paint(self, painter, option, index):
        popup = self.parent().parentWidget()
        chosen = index.row() == popup.combo.currentIndex()
        focused = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index == popup.list.hover_index
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        if chosen or focused:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#343750" if focused else "#292c40"))
            painter.drawRoundedRect(rect, 7, 7)
        if hovered and enabled:
            painter.setPen(Qt.PenStyle.NoPen)
            tint = QColor("#555b88")
            tint.setAlphaF(0.35 * popup.list.hover_opacity)
            painter.setBrush(tint)
            painter.drawRoundedRect(rect, 7, 7)
        painter.setFont(option.font)
        painter.setPen(QColor("#eef0ff" if enabled else "#62666d"))
        text_rect = option.rect.adjusted(12, 0, -34, 0)
        text = option.fontMetrics.elidedText(str(index.data() or ""), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        if chosen:
            center = QPointF(option.rect.right() - 17, option.rect.center().y())
            painter.setPen(QPen(QColor("#a6acff"), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            path = QPainterPath(center + QPointF(-4, 0))
            path.lineTo(center + QPointF(-1, 3))
            path.lineTo(center + QPointF(5, -3))
            painter.drawPath(path)
        painter.restore()


class DropdownPopup(QWidget):
    def __init__(self, combo):
        super().__init__(combo, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.combo = combo
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.setAutoFillBackground(False)
        self.setObjectName("fluxDropdown")
        self.setStyleSheet("QWidget#fluxDropdown { background: transparent; border: none; } QListView { background: transparent; border: none; padding: 0; outline: none; } QListView::item { background: transparent; border: none; }")
        self.list = OptionList(self)
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setItemDelegate(OptionDelegate(self.list))
        self.list.clicked.connect(self.choose)
        self.list.installEventFilter(self)
        self.animation = QVariantAnimation(self)
        self.animation.valueChanged.connect(self.animate)
        self.animation.finished.connect(self.animation_finished)
        self.closing = False
        self.target_rect = QRect()
        self.above = False
        self.commit_index = None
        self.owner = combo.window()
        self.owner.installEventFilter(self)
        ancestor = combo.parentWidget()
        while ancestor is not None and ancestor != self.owner:
            ancestor.installEventFilter(self)
            ancestor = ancestor.parentWidget()
        self.bound_model = None
        self.list.setAccessibleName("可选参数")

    def animated(self):
        motion = getattr(self.combo.window(), "motion", None)
        return motion.enabled if motion is not None else True

    def open(self):
        if self.isVisible():
            return
        self.animation.stop()
        self.closing = False
        self.commit_index = None
        self.list.setModel(self.combo.model())
        if self.bound_model != self.combo.model():
            if self.bound_model is not None:
                for signal in (self.bound_model.modelAboutToBeReset, self.bound_model.rowsAboutToBeRemoved, self.bound_model.rowsAboutToBeInserted, self.bound_model.layoutAboutToBeChanged):
                    signal.disconnect(self.model_changing)
            self.bound_model = self.combo.model()
            for signal in (self.bound_model.modelAboutToBeReset, self.bound_model.rowsAboutToBeRemoved, self.bound_model.rowsAboutToBeInserted, self.bound_model.layoutAboutToBeChanged):
                signal.connect(self.model_changing)
        self.list.setRootIndex(self.combo.rootModelIndex())
        self.list.setModelColumn(self.combo.modelColumn())
        screen = self.combo.screen().availableGeometry()
        anchor = self.combo.mapToGlobal(QPoint(0, self.combo.height()))
        top = self.combo.mapToGlobal(QPoint()).y()
        text_width = max((self.combo.fontMetrics().horizontalAdvance(self.combo.itemText(row)) for row in range(self.combo.count())), default=0)
        width = min(screen.width() - 16, max(self.combo.width(), min(420, text_width + 64)))
        desired = min(self.combo.count(), 8) * 36 + 16
        below_space = screen.bottom() - anchor.y() - 12
        above_space = top - screen.top() - 12
        self.above = below_space < desired and above_space > below_space
        height = min(desired, max(48, above_space if self.above else below_space))
        left = max(screen.left() + 8, min(anchor.x(), screen.right() - width - 7))
        vertical = top - height - 6 if self.above else anchor.y() + 6
        self.target_rect = QRect(left, max(screen.top() + 8, vertical), width, height)
        self.setGeometry(self.target_rect)
        self.list.setGeometry(8, 8, width - 16, height - 16)
        selected = self.combo.model().index(self.combo.currentIndex(), self.combo.modelColumn(), self.combo.rootModelIndex())
        self.list.setCurrentIndex(selected)
        self.list.setAccessibleName(self.combo.accessibleName() or "可选参数")
        self.list.setAccessibleDescription("方向键浏览，回车确认，Esc 取消。滚轮只滚动列表，不修改参数。")
        self.combo.setProperty("popupOpen", True)
        self.combo.style().unpolish(self.combo)
        self.combo.style().polish(self.combo)
        self.setWindowOpacity(0 if self.animated() else 1)
        self.show()
        self.list.scrollTo(selected, QAbstractItemView.ScrollHint.EnsureVisible)
        self.list.setFocus(Qt.FocusReason.PopupFocusReason)
        self.start_animation(0, 1, 170)

    def model_changing(self, *args):
        self.commit_index = None
        self.dismiss(immediate=True)

    def start_animation(self, start, end, duration):
        self.animation.stop()
        if not self.animated():
            self.animate(end)
            self.animation_finished()
            return
        self.animation.setDuration(duration)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.setStartValue(float(start))
        self.animation.setEndValue(float(end))
        self.animation.start()

    def animate(self, progress):
        self.setWindowOpacity(float(progress))
        rect = QRect(self.target_rect)
        rect.translate(0, round((1 - progress) * (8 if self.above else -8)))
        self.setGeometry(rect)
        self.combo.arrow_progress = float(progress)
        self.combo.update()

    def dismiss(self, commit_index=None, immediate=False):
        if not self.isVisible():
            return
        if self.closing and not immediate:
            return
        self.closing = True
        self.commit_index = QPersistentModelIndex(commit_index) if commit_index is not None else None
        if immediate:
            self.animation.stop()
            self.animation_finished()
        else:
            self.start_animation(self.windowOpacity(), 0, 110)

    def animation_finished(self):
        if self.closing:
            selection = self.commit_index
            self.commit_index = None
            self.hide()
            if selection is not None and selection.isValid() and self.combo.isEnabled() and selection.flags() & Qt.ItemFlag.ItemIsEnabled and selection.flags() & Qt.ItemFlag.ItemIsSelectable:
                row = selection.row()
                text = str(selection.data() or "")
                self.combo.setCurrentIndex(row)
                self.combo.activated.emit(row)
                self.combo.textActivated.emit(text)
            if self.combo.isVisible() and self.combo.isEnabled():
                self.combo.setFocus(Qt.FocusReason.PopupFocusReason)

    def choose(self, index):
        if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEnabled and index.flags() & Qt.ItemFlag.ItemIsSelectable:
            self.dismiss(index)

    def hideEvent(self, event):
        self.animation.stop()
        self.commit_index = None
        self.closing = False
        self.list.hover_animation.stop()
        if self.bound_model is not None:
            for signal in (self.bound_model.modelAboutToBeReset, self.bound_model.rowsAboutToBeRemoved, self.bound_model.rowsAboutToBeInserted, self.bound_model.layoutAboutToBeChanged):
                signal.disconnect(self.model_changing)
            self.bound_model = None
        self.combo.arrow_progress = 0
        self.combo.setProperty("popupOpen", False)
        self.combo.style().unpolish(self.combo)
        self.combo.style().polish(self.combo)
        self.combo.update()
        QComboBox.hidePopup(self.combo)
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#45485f"), 1))
        painter.setBrush(QColor("#1d1f28"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

    def mousePressEvent(self, event):
        if not self.rect().contains(event.position().toPoint()):
            if self.combo.rect().contains(self.combo.mapFromGlobal(event.globalPosition().toPoint())):
                self.combo.dismissed_press = (event.timestamp(), event.globalPosition().toPoint())
            self.dismiss(immediate=True)
        else:
            super().mousePressEvent(event)

    def eventFilter(self, watched, event):
        if watched == self.list and event.type() == QEvent.Type.ShortcutOverride:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Escape, Qt.Key.Key_F4, Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
                event.accept()
                return True
        if watched == self.list and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self.choose(self.list.currentIndex())
                return True
            if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F4):
                self.dismiss()
                return True
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                self.dismiss(immediate=True)
                self.combo.focusNextPrevChild(event.key() == Qt.Key.Key_Tab)
                return True
        if watched != self.list and event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Hide, QEvent.Type.Close, QEvent.Type.WindowStateChange):
            self.dismiss(immediate=True)
        return super().eventFilter(watched, event)


class AnimatedComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.popup = None
        self.dismissed_press = None
        self.arrow_progress = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()

    def showPopup(self):
        if not self.isEnabled() or not self.count():
            return
        if self.popup is None:
            self.popup = DropdownPopup(self)
        self.popup.open()

    def hidePopup(self):
        if self.popup is not None:
            self.popup.dismiss()

    def setModel(self, model):
        if self.popup is not None:
            self.popup.dismiss(immediate=True)
        super().setModel(model)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.isEditable():
            replayed = self.dismissed_press == (event.timestamp(), event.globalPosition().toPoint())
            self.dismissed_press = None
            if replayed:
                event.accept()
                return
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            if self.popup is not None and self.popup.isVisible():
                self.hidePopup()
            else:
                self.showPopup()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.isEditable():
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if not self.isEditable() and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F4, Qt.Key.Key_Up, Qt.Key.Key_Down) and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self.showPopup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled() and self.popup is not None:
            self.popup.dismiss(immediate=True)
        super().changeEvent(event)

    def hideEvent(self, event):
        if self.popup is not None:
            self.popup.dismiss(immediate=True)
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() - 17, self.height() / 2)
        painter.rotate(180 * self.arrow_progress)
        color = "#62666d" if not self.isEnabled() else "#aab1ff" if self.arrow_progress else "#969ba6"
        painter.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath(QPointF(-4, -2))
        path.lineTo(0, 2)
        path.lineTo(4, -2)
        painter.drawPath(path)
