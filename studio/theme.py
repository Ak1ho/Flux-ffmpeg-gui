from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from studio.paths import ROOT


ICONS = {
    "all": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "video": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3Z"/>',
    "audio": '<path d="M9 18V5l11-2v13M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="3"/><ellipse cx="17" cy="16" rx="3" ry="3"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m21 15-5-5L5 21"/>',
    "decrypt": '<rect x="4" y="10" width="16" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 7.5-2M12 14v3"/>',
    "queue": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="#101112"/><circle cx="15" cy="17" r="3" fill="#101112"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "folder": '<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    "upload": '<path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/>',
    "play": '<path d="m8 4 13 8-13 8Z"/>',
    "pause": '<path d="M8 4v16M16 4v16"/>',
    "trash": '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "arrow": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "refresh": '<path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    "up": '<path d="m6 15 6-6 6 6"/>',
    "down": '<path d="m6 9 6 6 6-6"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "terminal": '<path d="m4 6 6 6-6 6M13 18h7"/>',
}


def icon(name: str, color: str = "#a5a8b2", size: int = 20) -> QIcon:
    if name == "brand":
        return QIcon(str(ROOT / "assets" / "app.ico"))
    content = ICONS.get(name, ICONS["all"])
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{content}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


STYLE = """
QWidget { color: #e7e8ec; background: #101112; font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 13px; }
QMainWindow, QWidget#shell { background: #101112; }
QWidget#sidebar { background: #0b0c0e; border-right: 1px solid #23252a; }
QWidget#inspector { background: #111214; border-left: 1px solid #23252a; }
QLabel { background: transparent; border: none; }
QLabel#brandTitle { font-size: 16px; font-weight: 600; color: #f7f8f8; }
QLabel#title { font-size: 26px; font-weight: 600; color: #f7f8f8; }
QLabel#subtitle, QLabel#muted { color: #969ba6; }
QLabel#section { color: #969ba6; font-size: 11px; font-weight: 600; }
QLabel#badge { color: #b3b6c0; background: #1b1c20; border: 1px solid #2a2c33; border-radius: 5px; padding: 4px 8px; font-size: 11px; }
QLabel#hint { color: #989daa; line-height: 1.5; }
QLabel#preview { background: #0b0c0e; border: 1px solid #25272d; border-radius: 8px; }
QPushButton { background: #1a1b1f; border: 1px solid #303239; border-radius: 6px; padding: 8px 12px; min-height: 18px; }
QPushButton:hover { background: #25262c; border-color: #41434d; }
QPushButton:pressed { background: #30313a; }
QPushButton:focus { border: 1px solid #828fff; }
QPushButton:disabled { color: #62666d; background: #151619; border-color: #24262c; }
QPushButton#primary { background: #5e6ad2; color: white; border: 1px solid #7380e3; font-weight: 600; }
QPushButton#primary:hover { background: #707de0; }
QPushButton#primary:disabled { background: #343952; color: #999eb8; border-color: #414762; }
QPushButton#nav { border: 1px solid transparent; background: transparent; color: #a6aab5; text-align: left; padding: 9px 12px; }
QPushButton#nav:hover { background: #17181c; color: #f0f1f4; }
QPushButton#nav:checked { background: #202127; color: #f7f8f8; border-color: #2e3039; }
QPushButton#ghost { background: transparent; border: 1px solid transparent; color: #a9aeba; }
QPushButton#ghost:hover { background: #22242a; color: #f7f8f8; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit { background: #18191d; border: 1px solid #30323a; border-radius: 6px; padding: 7px 9px; min-height: 19px; selection-background-color: #414b8d; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus { border-color: #828fff; }
QLineEdit:disabled, QComboBox:disabled { color: #62666d; background: #131417; }
QComboBox { padding-right: 28px; border-radius: 9px; }
QComboBox:hover { border-color: #555b78; background: #1d1f28; }
QComboBox[popupOpen="true"] { border-color: #828fff; background: #222536; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView { background: #202127; border: 1px solid #3a3c45; selection-background-color: #343849; padding: 4px; outline: 0; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button { width: 16px; border: none; }
QCheckBox { spacing: 8px; color: #bfc3cd; background: transparent; }
QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px; border: 1px solid #4b4e5a; background: #17181c; }
QCheckBox::indicator:checked { background: #5e6ad2; border: 2px solid #a8b0ff; }
QCheckBox:focus { color: #f7f8f8; }
QTableWidget { background: #101112; border: 1px solid #25272d; border-radius: 8px; gridline-color: #24262b; selection-background-color: #252938; selection-color: #f7f8f8; outline: 0; alternate-background-color: #131417; }
QTableWidget::item { border-bottom: 1px solid #22242a; padding: 9px 10px; }
QTableWidget::item:selected { background: #252938; }
QHeaderView::section { background: #16171a; color: #969ba6; border: none; border-bottom: 1px solid #2b2d34; padding: 11px 10px; font-size: 12px; }
QTableCornerButton::section { background: #16171a; border: none; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #34363e; min-height: 28px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: 8px; background: #151619; }
QScrollBar::handle:horizontal { background: #34363e; min-width: 28px; border-radius: 3px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QProgressBar { border: none; border-radius: 3px; background: #25272e; min-height: 5px; max-height: 5px; }
QProgressBar::chunk { background: #7c87e4; border-radius: 3px; }
QWidget#dropzone { background: #121316; border: 1px dashed #393c48; border-radius: 10px; }
QWidget#notice { background: #181a22; border: 1px solid #313649; border-radius: 8px; }
QWidget#card { background: #151619; border: 1px solid #2a2c33; border-radius: 8px; }
QFrame#divider { background: #272930; max-height: 1px; min-height: 1px; border: none; }
QStatusBar { background: #0b0c0e; color: #a2a7b3; border-top: 1px solid #23252a; font-size: 11px; }
QStatusBar::item { border: none; }
QMenu { background: #202127; border: 1px solid #383a45; padding: 6px; }
QMenu::item { padding: 8px 22px; border-radius: 4px; }
QMenu::item:selected { background: #353849; }
QToolTip { color: #e7e8ec; background: #252730; border: 1px solid #414552; padding: 6px; }
QDialog { background: #101112; }
QSplitter::handle { background: #23252a; width: 1px; }
"""
STYLE = STYLE.replace("CHEVRON_PATH", (ROOT / "assets" / "chevron.svg").as_posix())
