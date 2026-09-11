from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QItemSelectionModel, QLockFile, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import QApplication, QAbstractItemView, QButtonGroup, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from studio import APP_ENGLISH_NAME, APP_NAME, APP_TITLE, VERSION
from studio.catalog import KINDS, OP_NAMES, human_size, human_time
from studio.engine import HIDDEN, engine_path
from studio.inspector import Inspector
from studio.motion import MotionController
from studio.paths import BUNDLED_PATHS, ROOT, STATE, portable_resources, resource_path, settings, write_json
from studio.tasks import STATUS_NAMES, TaskQueue
from studio.theme import STYLE, icon
from studio.widgets import Field, ProbeWork, ScanWork, button, divider, label, spin


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.preferences = settings()
        self.files = []
        self.current_view = "all"
        self.workers = set()
        self.probing = set()
        self.players = []
        self.preview_path = ""
        self.queue_dirty = True
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(icon("brand"))
        self.resize(1460, 940)
        self.setMinimumSize(1120, 720)
        self.setAcceptDrops(True)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.queue = TaskQueue(self.preferences, self)
        self.queue.changed.connect(self.on_queue_changed)
        self.queue.notification.connect(self.notify)
        shell = QWidget()
        shell.setObjectName("shell")
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.build_sidebar())
        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_workspace())
        self.pages.addWidget(self.build_queue_page())
        self.pages.addWidget(self.build_settings_page())
        self.pages.addWidget(self.build_about_page())
        root.addWidget(self.pages, 1)
        self.setCentralWidget(shell)
        self.engine_status = label("FFmpeg 9.0.1  /  本地处理", "muted")
        self.statusBar().addPermanentWidget(self.engine_status)
        self.notify("就绪 · 拖入文件或文件夹开始 · Ctrl+O 添加文件")
        self.queue_timer = QTimer(self)
        self.queue_timer.setInterval(350)
        self.queue_timer.timeout.connect(self.refresh_queue_if_needed)
        self.queue_timer.start()
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(6000)
        self.status_timer.timeout.connect(self.update_runtime_status)
        self.status_timer.start()
        QShortcut(QKeySequence.StandardKey.Open, self, self.choose_files)
        QShortcut(QKeySequence("Ctrl+Return"), self, lambda: self.enqueue_files(True) if self.pages.currentIndex() == 0 else self.queue.start())
        QShortcut(QKeySequence("Ctrl+1"), self, lambda: self.navigate("all"))
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.navigate("queue"))
        QShortcut(QKeySequence("Ctrl+,"), self, lambda: self.navigate("settings"))
        self.refresh_files()
        self.update_runtime_status()
        self.on_queue_changed()

        self.motion = MotionController(self)

    def build_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(202)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 25, 14, 16)
        layout.setSpacing(6)
        brand = QHBoxLayout()
        brand_icon = label("")
        brand_icon.setPixmap(icon("brand").pixmap(30, 30))
        brand.addWidget(brand_icon)
        brand.addSpacing(4)
        brand.addWidget(label(APP_NAME, "brandTitle"))
        brand.addStretch()
        layout.addLayout(brand)
        tagline = label(APP_ENGLISH_NAME.upper(), "section")
        tagline.setContentsMargins(4, 8, 0, 24)
        layout.addWidget(tagline)
        layout.addWidget(label("工作空间", "section"))
        layout.addSpacing(5)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        for key, title in KINDS.items():
            nav = button(title, lambda checked=False, view=key: self.motion.sidebar(view), key)
            nav.setObjectName("nav")
            nav.setCheckable(True)
            self.nav_group.addButton(nav)
            self.nav_buttons[key] = nav
            layout.addWidget(nav)
        self.nav_buttons["all"].setChecked(True)
        layout.addSpacing(18)
        layout.addWidget(label("管理", "section"))
        layout.addSpacing(5)
        for key, title in [("queue", "任务队列"), ("settings", "设置")]:
            nav = button(title, lambda checked=False, view=key: self.motion.sidebar(view), key)
            nav.setObjectName("nav")
            nav.setCheckable(True)
            self.nav_group.addButton(nav)
            self.nav_buttons[key] = nav
            layout.addWidget(nav)
        layout.addStretch()
        local_card = QWidget()
        local_card.setObjectName("card")
        card_layout = QVBoxLayout(local_card)
        card_layout.setContentsMargins(12, 13, 12, 13)
        card_layout.setSpacing(6)
        card_layout.addWidget(label("文件始终留在本机"))
        card_layout.addWidget(label("不上传媒体文件\n独立引擎 · 安全输出", "muted", True))
        layout.addWidget(local_card)
        layout.addSpacing(12)
        layout.addWidget(button("关于与使用说明", lambda: self.motion.sidebar("about"), "info", ghost=True))
        layout.addWidget(label(f"  VERSION {VERSION}   /   WINDOWS", "section"))
        return sidebar

    def build_workspace(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        content = QWidget()
        center = QVBoxLayout(content)
        center.setContentsMargins(28, 25, 28, 20)
        center.setSpacing(17)
        breadcrumb = QHBoxLayout()
        breadcrumb.addWidget(label("工作空间  /  媒体库", "section"))
        breadcrumb.addStretch()
        breadcrumb.addWidget(label("LOCAL FIRST", "badge"))
        center.addLayout(breadcrumb)
        title_row = QHBoxLayout()
        self.page_title = label("全部素材", "title")
        title_row.addWidget(self.page_title)
        title_row.addStretch()
        self.file_count = label("0 个素材", "badge")
        title_row.addWidget(self.file_count)
        center.addLayout(title_row)
        self.page_subtitle = label("一个工作台，处理你的所有媒体。", "subtitle")
        center.addWidget(self.page_subtitle)
        self.decrypt_notice = QWidget()
        self.decrypt_notice.setObjectName("notice")
        notice_layout = QVBoxLayout(self.decrypt_notice)
        notice_layout.setContentsMargins(14, 12, 14, 12)
        notice_layout.setSpacing(7)
        notice_layout.addWidget(label("音乐解密 · 运行环境", "section"))
        self.decrypt_status = label("正在检查客户端…", "muted", True)
        notice_layout.addWidget(self.decrypt_status)
        notice_layout.addWidget(label("QQ：MFLAC / MGG / MMP4   ·   酷我：KWM\n酷狗：KGM / KGMA / VPR / KGG（KGG 依赖本机数据库）", "muted", True))
        center.addWidget(self.decrypt_notice)
        self.decrypt_notice.hide()
        self.dropzone = QWidget()
        self.dropzone.setObjectName("dropzone")
        self.dropzone.setMinimumHeight(196)
        drop_layout = QVBoxLayout(self.dropzone)
        drop_layout.setContentsMargins(24, 23, 24, 23)
        drop_layout.setSpacing(10)
        upload = label("")
        upload.setAlignment(Qt.AlignmentFlag.AlignCenter)
        upload.setPixmap(icon("upload", "#959dab", 28).pixmap(28, 28))
        drop_layout.addWidget(upload)
        drop_title = label("将文件或文件夹拖到这里")
        drop_title.setStyleSheet("font-size: 17px; font-weight: 500;")
        drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(drop_title)
        drop_hint = label("视频、音频、图片与加密音乐 · 支持批量处理", "muted")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(drop_hint)
        drop_buttons = QHBoxLayout()
        drop_buttons.addStretch()
        drop_buttons.addWidget(button("选择文件", self.choose_files, "plus"))
        drop_buttons.addWidget(button("导入文件夹", self.choose_folder, "folder", ghost=True))
        drop_buttons.addStretch()
        drop_layout.addLayout(drop_buttons)
        center.addWidget(self.dropzone)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(7)
        toolbar.addWidget(button("添加", self.choose_files, "plus"))
        toolbar.addWidget(button("文件夹", self.choose_folder, "folder", ghost=True))
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索素材…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(210)
        self.search.textChanged.connect(self.refresh_files)
        toolbar.addWidget(self.search, 1)
        toolbar.addStretch()
        toolbar.addWidget(button("全选", lambda: self.files_table.selectAll(), ghost=True))
        remove = button("", self.remove_files, "trash", ghost=True)
        remove.setToolTip("从列表移除选中素材，不删除原文件")
        remove.setAccessibleName("移除选中素材")
        toolbar.addWidget(remove)
        center.addLayout(toolbar)
        self.files_table = QTableWidget(0, 4)
        self.files_table.setHorizontalHeaderLabels(["文件名称", "格式", "大小", "时长"])
        self.configure_table(self.files_table)
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in [(1, 72), (2, 89), (3, 74)]:
            self.files_table.setColumnWidth(column, width)
        self.files_table.itemSelectionChanged.connect(self.selection_changed)
        self.files_table.cellDoubleClicked.connect(lambda row, column: self.preview_selected())
        self.files_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files_table.customContextMenuRequested.connect(self.file_context)
        center.addWidget(self.files_table, 1)
        detail = QHBoxLayout()
        self.preview_image = label("", "preview")
        self.preview_image.setFixedSize(152, 88)
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.addWidget(self.preview_image)
        details_text = QVBoxLayout()
        details_text.setSpacing(6)
        self.preview_title = label("尚未选择素材")
        self.preview_title.setMaximumWidth(460)
        self.preview_details = label("选择文件查看媒体信息", "muted", True)
        self.preview_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_text.addWidget(self.preview_title)
        details_text.addWidget(self.preview_details)
        detail_actions = QHBoxLayout()
        detail_actions.setSpacing(4)
        detail_actions.addWidget(button("预览", self.preview_selected, "play", ghost=True))
        detail_actions.addWidget(button("详细信息", self.show_metadata, "info", ghost=True))
        up = button("", lambda: self.move_file(-1), "up", ghost=True)
        up.setToolTip("向上移动，用于调整合并顺序")
        up.setAccessibleName("素材上移")
        down = button("", lambda: self.move_file(1), "down", ghost=True)
        down.setToolTip("向下移动，用于调整合并顺序")
        down.setAccessibleName("素材下移")
        detail_actions.addWidget(up)
        detail_actions.addWidget(down)
        detail_actions.addStretch()
        details_text.addLayout(detail_actions)
        detail.addLayout(details_text, 1)
        center.addLayout(detail)
        center.addWidget(divider())
        footer = QHBoxLayout()
        self.library_hint = label("支持批量选择 · 双击预览", "muted")
        footer.addWidget(self.library_hint)
        footer.addStretch()
        footer.addWidget(button("查看任务", lambda: self.navigate("queue"), "arrow", ghost=True))
        center.addLayout(footer)
        layout.addWidget(content, 1)
        self.inspector = Inspector(self.preferences)
        self.inspector.enqueue.connect(self.enqueue_files)
        self.inspector.preference_changed.connect(self.save_preferences)
        self.inspector.category.currentIndexChanged.connect(lambda: self.inspector.set_count(len(self.selected_files(True))))
        layout.addWidget(self.inspector)
        return page

    def configure_table(self, table):
        table.verticalHeader().hide()
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().setDefaultSectionSize(54)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.horizontalHeader().setSectionsMovable(False)

    def page_header(self, layout, eyebrow, title, subtitle):
        layout.addWidget(label(eyebrow, "section"))
        layout.addSpacing(2)
        layout.addWidget(label(title, "title"))
        layout.addWidget(label(subtitle, "subtitle", True))
        layout.addSpacing(12)

    def build_queue_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(16)
        self.page_header(layout, "工作空间  /  任务管理", "任务队列", "每一个任务独立运行。离开此页面，不会打断处理。")
        toolbar = QHBoxLayout()
        toolbar.addWidget(button("开始队列", self.queue.start, "play", True))
        toolbar.addWidget(button("暂停派发", self.queue.pause, "pause"))
        toolbar.addWidget(button("取消选中", self.cancel_selected, "stop", ghost=True))
        toolbar.addWidget(button("重试选中", self.retry_selected, "refresh", ghost=True))
        toolbar.addStretch()
        toolbar.addWidget(button("清理已结束", self.queue.clear_finished, "trash", ghost=True))
        layout.addLayout(toolbar)
        self.queue_summary = label("队列为空，添加素材后选择处理操作。", "muted")
        layout.addWidget(self.queue_summary)
        self.queue_table = QTableWidget(0, 5)
        self.queue_table.setHorizontalHeaderLabels(["输入文件", "处理任务", "状态", "进度", "用时"])
        self.configure_table(self.queue_table)
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in [(1, 200), (2, 110), (3, 145), (4, 85)]:
            self.queue_table.setColumnWidth(column, width)
        self.queue_table.itemSelectionChanged.connect(self.show_job_details)
        self.queue_table.cellDoubleClicked.connect(lambda row, column: self.open_job_output())
        layout.addWidget(self.queue_table, 1)
        detail_header = QHBoxLayout()
        detail_header.addWidget(label("任务详情与执行日志", "section"))
        detail_header.addStretch()
        detail_header.addWidget(button("打开结果目录", self.open_job_output, "folder", ghost=True))
        detail_header.addWidget(button("导出任务报告", self.export_report, "queue", ghost=True))
        layout.addLayout(detail_header)
        self.job_detail = label("选中任务可查看输出路径、错误原因及 FFmpeg 命令。", "muted", True)
        self.job_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.job_detail.setMaximumHeight(90)
        layout.addWidget(self.job_detail)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(180)
        self.log_view.setMinimumHeight(115)
        self.log_view.setFont(QFont("Cascadia Mono", 10))
        self.log_view.setPlaceholderText("实际运行日志将在这里显示。")
        layout.addWidget(self.log_view)
        return page

    def path_setting(self, layout, key, title, description, folder=False):
        control = QLineEdit(str(self.preferences.get(key, "")))
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(control, 1)
        def choose():
            try:
                initial = str(resource_path(control.text())) if key in BUNDLED_PATHS else control.text()
            except ValueError:
                initial = str(ROOT)
            if folder:
                path = QFileDialog.getExistingDirectory(self, title, initial)
            else:
                path, _ = QFileDialog.getOpenFileName(self, title, initial)
            if path:
                control.setText(path)
        row_layout.addWidget(button("浏览", choose, "folder"))
        layout.addWidget(Field(title, row))
        layout.addWidget(label(description, "muted", True))
        self.settings_controls[key] = control

    def build_settings_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 28, 40, 32)
        layout.setSpacing(14)
        self.settings_controls = {}
        self.page_header(layout, "偏好设置", "让工作台适合你", "设置保存在当前 Windows 用户目录，不改动原始工具目录。")
        self.path_setting(layout, "output_dir", "默认输出目录", "任务会保存参数快照；修改此设置不会更改已排队任务的输出位置。", True)
        self.path_setting(layout, "ffmpeg_dir", "FFmpeg 引擎目录", "@app/ 表示当前软件资源目录，移动整个软件文件夹后自动跟随。目录中需要 ffmpeg.exe、ffprobe.exe 与 ffplay.exe；自定义外部目录保留原位置。", True)
        self.settings_controls["concurrency"] = spin(1, 4, int(self.preferences.get("concurrency", 2)))
        layout.addWidget(Field("并发媒体任务数", self.settings_controls["concurrency"]))
        layout.addWidget(label("解密任务始终串行，避免多个任务同时连接音乐客户端。暂停派发不暂停正在执行的任务。", "muted", True))
        self.settings_controls["recursive"] = QCheckBox("导入文件夹时包含子文件夹")
        self.settings_controls["recursive"].setChecked(self.preferences.get("recursive", True))
        layout.addWidget(self.settings_controls["recursive"])
        layout.addWidget(divider())
        layout.addWidget(label("光影与动效", "brandTitle"))
        layout.addWidget(label("紫蓝光晕跟随鼠标，照亮附近文字；点击泛起水波。仅左侧导航切页时收起旧文字、弹出新文字，任务与日志更新不触发动效。", "muted", True))
        for key, title in (("motion_enabled", "启用界面动效（关闭即减少动态效果）"), ("motion_halo", "鼠标光晕与文字辉光"), ("motion_ripple", "全窗口点击水波"), ("motion_navigation", "左侧导航文字收起 / 弹出")):
            control = QCheckBox(title)
            control.setChecked(self.preferences.get(key, True))
            self.settings_controls[key] = control
            layout.addWidget(control)
            control.toggled.connect(self.preview_motion_settings)
        intensity = spin(30, 150, int(self.preferences.get("motion_intensity", 100)))
        intensity.setSuffix(" %")
        self.settings_controls["motion_intensity"] = intensity
        intensity.valueChanged.connect(self.preview_motion_settings)
        layout.addWidget(Field("光效强度 · 即时预览，保存后下次沿用", intensity))
        layout.addWidget(divider())
        layout.addWidget(label("解密引擎设置", "brandTitle"))
        self.path_setting(layout, "key_file", "酷狗 key 文件", "默认使用原项目提供的 kugou_key.xz。")
        self.path_setting(layout, "kgg_db_path", "酷狗 KGG 数据库（可留空自动查找）", "指定本机 KGMusicV3.db；没有匹配的本地密钥信息时，KGG 无法解密。")
        self.path_setting(layout, "kuwo_exe", "酷我客户端程序（可选）", "需要与当前运行的酷我版本匹配。请自行启动客户端，软件不会代替你登录。")
        self.path_setting(layout, "signature_file", "酷我签名文件", "默认使用原项目提供的 recovered_signature.json；兼容性取决于客户端版本。")
        self.settings_status = label("", "muted", True)
        layout.addWidget(self.settings_status)
        actions = QHBoxLayout()
        actions.addWidget(button("保存设置", self.apply_settings, "check", True))
        actions.addWidget(button("检查运行环境", self.update_runtime_status, "refresh"))
        actions.addWidget(button("打开日志目录", lambda: self.open_folder(STATE / "logs"), "folder", ghost=True))
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def build_about_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(18)
        self.page_header(layout, f"{APP_TITLE}  /  {VERSION}", "一个工作台，所有媒体。", "流转 · Flux，让媒体在格式之间自由流转。基于本地 FFmpeg 与 QKKDecrypt 构建。")
        sections = [
            ("01  导入与处理", "拖入文件或文件夹，按类型筛选素材。选中一个或多个文件，在右侧选择操作和参数。未选择行时，处理当前列表中与右侧类型匹配的全部素材。"),
            ("02  视频 · 音频 · 图片", "视频：转换、压缩、截取、缩放、裁剪、旋转、变速、静音、提取音频、GIF、封面帧、合并、水印、字幕和无损换封装。\n音频：转换、截取、响度、增益、变速、淡入淡出、降噪、合并。\n图片：转换、压缩、缩放、裁剪、旋转。静态图片操作只处理第一帧；HDR 与特殊色彩工作流请先验证。"),
            ("03  音乐解密", "使用你提供的 QKKDecrypt 代码和资源，不伪造解密结果。QQ 支持 MFLAC / MGG / MMP4，酷我支持 KWM，酷狗支持 KGM / KGMA / VPR / KGG。QQ 和酷我依赖运行中的客户端，KGG 依赖本机数据库。客户端更新可能影响解密；不支持的格式会明确失败。"),
            ("04  数据安全与任务恢复", "所有媒体处理均在本机完成。输出先写入独立临时目录，验证成功后发布。默认自动重命名；覆盖模式也拒绝覆盖原始输入。队列、设置、日志在本地持久化，意外退出的任务标为中断，需手动重试。暂停派发仅停止启动新任务。"),
            ("05  范围与限制", "此版本是批量处理工作台，不是多轨剪辑软件。内置常用输出格式，实际解码范围取决于你提供的 FFmpeg 构建。无损封装只保留视频与音轨；普通转码处理首条视频/音轨，不承诺保留多轨、章节、字幕及全部封面元数据。硬件编码取决于显卡和驱动，失败时可改用自动软件编码。"),
            ("06  原项目与第三方声明", "解密引擎来自 Acooldog/QQKWKG-TriMusicDecrypt；QQ 解密思路来源为 luyikk/qqmusic_decrypt。保留原项目 LICENSE、README 和第三方声明。原项目 README 要求仅供学习交流、禁止商用和倒卖。请只处理你拥有合法权限的文件。整体包含 FFmpeg、Qt / PySide6、Frida 等第三方组件，不将整个分发包宣称为 MIT-only。"),
            ("键盘快捷键", "Ctrl+O  添加文件     Ctrl+Enter  开始处理 / 启动队列\nCtrl+1  媒体库     Ctrl+2  任务队列     Ctrl+,  设置\n素材表格支持 Ctrl / Shift 多选，双击预览。"),
        ]
        for title, text in sections:
            layout.addWidget(label(title, "brandTitle"))
            layout.addWidget(label(text, "muted", True))
            layout.addWidget(divider())
        layout.addWidget(button("查看随附声明与许可证", lambda: self.open_folder(ROOT / "licenses"), "folder"))
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def navigate(self, view):
        if hasattr(self, "motion") and not self.motion.navigation.committing:
            self.motion.navigation.finish(False)
        self.current_view = view
        if view in self.nav_buttons:
            self.nav_buttons[view].setChecked(True)
        if view in KINDS:
            self.pages.setCurrentIndex(0)
            self.page_title.setText(KINDS[view])
            subtitles = {"all": "一个工作台，处理你的所有媒体。", "video": "从转码到精修，让每一帧恰到好处。", "audio": "转换、整理与优化，让声音回到作品本身。", "image": "格式、尺寸与方向，批量处理每一张图片。", "decrypt": "解密与后续转码，在同一条任务流程中完成。"}
            self.page_subtitle.setText(subtitles[view])
            self.decrypt_notice.setVisible(view == "decrypt")
            if view != "all":
                self.inspector.set_kind(view)
            self.refresh_files()
        else:
            self.pages.setCurrentIndex({"queue": 1, "settings": 2, "about": 3}[view])
            if view == "queue":
                self.refresh_queue()
            if view == "settings":
                for key in ("output_dir", "ffmpeg_dir", "key_file", "kgg_db_path", "kuwo_exe", "signature_file"):
                    self.settings_controls[key].setText(self.preferences.get(key, ""))

    def notify(self, message):
        self.statusBar().showMessage(message, 15000)

    def error(self, message):
        QMessageBox.warning(self, "请检查处理设置", str(message))

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添加媒体文件", "", "媒体文件 (*.*)")
        if paths:
            self.import_paths(paths)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "导入媒体文件夹")
        if path:
            self.import_paths([path])

    def import_paths(self, paths):
        self.notify("正在扫描素材…")
        worker = ScanWork(paths, self.preferences.get("recursive", True))
        self.workers.add(worker)
        worker.signals.result.connect(lambda result, task=worker: self.scan_finished(task, result))
        self.pool.start(worker)

    def scan_finished(self, worker, result):
        self.workers.discard(worker)
        existing = {item["path"].casefold() for item in self.files}
        added = [item for item in result["files"] if item["path"].casefold() not in existing]
        self.files.extend(added)
        if self.current_view not in KINDS or self.current_view != "all" and not any(item["kind"] == self.current_view for item in added):
            self.navigate("all")
        self.refresh_files()
        added_paths = {item["path"] for item in added}
        self.files_table.blockSignals(True)
        for row in range(self.files_table.rowCount()):
            if self.files_table.item(row, 0).data(Qt.ItemDataRole.UserRole) in added_paths:
                self.files_table.selectionModel().select(self.files_table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.files_table.blockSignals(False)
        self.selection_changed()
        self.notify(f"已导入 {len(added)} 个素材；跳过 {result['rejected']} 个不支持的文件、{len(result['files']) - len(added)} 个重复项。")
        if result["errors"]:
            self.error("部分路径无法读取：\n" + "\n".join(result["errors"][:5]))

    def visible_files(self):
        query = self.search.text().strip().casefold()
        return [item for item in self.files if (self.current_view == "all" or item["kind"] == self.current_view) and (not query or query in item["name"].casefold())]

    def selected_paths(self):
        return [self.files_table.item(row.row(), 0).data(Qt.ItemDataRole.UserRole) for row in self.files_table.selectionModel().selectedRows()]

    def selected_files(self, fallback=False):
        selected = set(self.selected_paths())
        return [item for item in self.visible_files() if item["path"] in selected or fallback and not selected and item["kind"] == self.inspector.kind]

    def refresh_files(self):
        selected = set(self.selected_paths())
        visible = self.visible_files()
        self.files_table.blockSignals(True)
        self.files_table.setRowCount(len(visible))
        self.files_table.clearSelection()
        for row, item in enumerate(visible):
            filename = QTableWidgetItem(icon(item["kind"]), item["name"])
            filename.setData(Qt.ItemDataRole.UserRole, item["path"])
            filename.setToolTip(item["path"])
            self.files_table.setItem(row, 0, filename)
            self.files_table.setItem(row, 1, QTableWidgetItem(Path(item["path"]).suffix.lstrip(".").upper()))
            self.files_table.setItem(row, 2, QTableWidgetItem(human_size(item["size"])))
            self.files_table.setItem(row, 3, QTableWidgetItem(human_time(item["info"]["duration"]) if item.get("info") and item["kind"] != "image" else "—"))
            if item["path"] in selected:
                self.files_table.selectionModel().select(self.files_table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.files_table.blockSignals(False)
        self.file_count.setText(f"{len(visible)} 个素材")
        self.dropzone.setVisible(not visible)
        self.library_hint.setText(f"{len(visible)} 个素材 · 共 {human_size(sum(item['size'] for item in visible))} · 原始文件保留")
        self.selection_changed()

    def selection_changed(self):
        selected = self.selected_files()
        if selected and all(item["kind"] == selected[0]["kind"] for item in selected) and self.inspector.kind != selected[0]["kind"]:
            self.inspector.set_kind(selected[0]["kind"])
        self.inspector.set_count(len(self.selected_files(True)))
        if not selected:
            self.preview_path = ""
            self.preview_title.setText("尚未选择素材")
            self.preview_details.setText("选择文件查看媒体信息")
            self.preview_image.setPixmap(icon("all", "#5c6270", 36).pixmap(36, 36))
            return
        item = selected[0]
        self.preview_path = item["path"]
        self.preview_title.setText(item["name"] if len(item["name"]) < 43 else item["name"][:40] + "…")
        self.preview_title.setToolTip(item["path"])
        self.preview_image.setPixmap(icon(item["kind"], "#7c8391", 36).pixmap(36, 36))
        if item["kind"] == "decrypt":
            self.preview_details.setText("加密音乐 · 解密完成后可播放\n" + human_size(item["size"]))
            return
        if item.get("info"):
            self.show_file_info(item)
        elif item.get("probe_error"):
            self.preview_details.setText(item["probe_error"][:180])
        else:
            self.preview_details.setText("正在读取媒体信息…")
            if item["path"] not in self.probing:
                self.probing.add(item["path"])
                worker = ProbeWork(item["path"], self.preferences, item["kind"])
                self.workers.add(worker)
                worker.signals.result.connect(lambda result, task=worker: self.probe_finished(task, result))
                self.pool.start(worker)

    def probe_finished(self, worker, result):
        self.workers.discard(worker)
        self.probing.discard(result["path"])
        item = next((item for item in self.files if item["path"] == result["path"]), None)
        if not item:
            return
        if result.get("error"):
            item["probe_error"] = result["error"]
        else:
            item["info"] = result["info"]
            item["thumbnail"] = result.get("thumbnail")
        for row in range(self.files_table.rowCount()):
            if self.files_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == item["path"] and item.get("info") and item["kind"] != "image":
                self.files_table.item(row, 3).setText(human_time(item["info"]["duration"]))
        if self.preview_path == item["path"]:
            if item.get("info"):
                self.show_file_info(item)
            else:
                self.preview_details.setText(result["error"][:180])

    def show_file_info(self, item):
        info = item["info"]
        parts = []
        if info.get("video"):
            video = info["video"]
            parts.append(f"{video.get('width', '—')} × {video.get('height', '—')}  ·  {video.get('codec_name', '').upper()}")
        if info.get("audio"):
            audio = info["audio"]
            parts.append(f"{audio.get('codec_name', '').upper()}  ·  {audio.get('sample_rate', '—')} Hz  ·  {audio.get('channels', '—')} 声道")
        self.preview_details.setText("\n".join(parts) or "已识别媒体文件")
        if item.get("thumbnail"):
            pixmap = QPixmap()
            pixmap.loadFromData(item["thumbnail"])
            self.preview_image.setPixmap(pixmap.scaled(150, 86, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def remove_files(self):
        selected = set(self.selected_paths())
        self.files = [item for item in self.files if item["path"] not in selected]
        self.refresh_files()
        self.notify(f"从列表移除 {len(selected)} 个素材；原始文件没有删除。")

    def move_file(self, offset):
        selected = self.selected_files()
        if len(selected) != 1:
            self.notify("请先选择一个素材来调整顺序。")
            return
        visible = self.visible_files()
        index = visible.index(selected[0])
        target_index = index + offset
        if not 0 <= target_index < len(visible):
            return
        source_position = self.files.index(selected[0])
        target_position = self.files.index(visible[target_index])
        self.files[source_position], self.files[target_position] = self.files[target_position], self.files[source_position]
        self.refresh_files()

    def file_context(self, position):
        menu = QMenu(self)
        menu.addAction("预览", self.preview_selected)
        menu.addAction("媒体详细信息", self.show_metadata)
        menu.addAction("打开源文件目录", lambda: self.open_folder(Path(self.selected_files()[0]["path"]).parent) if self.selected_files() else None)
        menu.addSeparator()
        menu.addAction("从列表移除（不删除文件）", self.remove_files)
        menu.exec(self.files_table.viewport().mapToGlobal(position))

    def preview_selected(self):
        selected = self.selected_files()
        if not selected:
            self.notify("请先选择一个素材。")
            return
        item = selected[0]
        if item["kind"] == "decrypt":
            self.notify("加密音乐需要先解密，再从任务结果目录播放。")
            return
        if item["kind"] == "image" and item.get("thumbnail"):
            dialog = QDialog(self)
            dialog.setWindowTitle(item["name"])
            dialog.resize(760, 540)
            layout = QVBoxLayout(dialog)
            preview = label("")
            pixmap = QPixmap(item["path"])
            if pixmap.isNull():
                pixmap.loadFromData(item["thumbnail"])
            preview.setPixmap(pixmap.scaled(960, 700, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(preview)
            layout.addWidget(button("关闭", dialog.accept))
            dialog.exec()
            return
        try:
            command = [str(engine_path("ffplay", self.preferences)), "-hide_banner", "-loglevel", "error", "-autoexit", "-window_title", APP_TITLE + " · " + item["name"], "-x", "960", "-y", "540"]
            if item["kind"] == "audio":
                command += ["-showmode", "waves"]
            command.append(item["path"])
            self.players = [player for player in self.players if player.poll() is None]
            self.players.append(subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **HIDDEN))
        except Exception as error:
            self.error(error)

    def show_metadata(self):
        selected = self.selected_files()
        if not selected:
            return
        item = selected[0]
        dialog = QDialog(self)
        dialog.setWindowTitle("媒体信息 · " + item["name"])
        dialog.resize(780, 600)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        payload = item.get("info", {}).get("raw") if item.get("info") else {"path": item["path"], "size": item["size"], "type": item["kind"], "note": item.get("probe_error", "加密文件需要先解密；普通文件信息可能仍在读取。")}
        text.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        layout.addWidget(text)
        layout.addWidget(button("关闭", dialog.accept))
        dialog.exec()

    def enqueue_files(self, start):
        try:
            selected = self.selected_files(True)
            if not selected:
                raise ValueError("请先添加或选择待处理素材。")
            kind = self.inspector.kind
            if any(item["kind"] != kind for item in selected):
                raise ValueError("批量任务需选择同一类型的素材。请先使用左侧分类，或只选择同类文件。")
            options = self.inspector.options()
            operation = self.inspector.operation.currentData()
            if operation == "concat" and len(selected) < 2:
                raise ValueError("至少选择两个同类文件，才能执行合并。")
            if operation == "concat":
                self.queue.add([item["path"] for item in selected], kind, operation, options)
            else:
                for item in selected:
                    self.queue.add([item["path"]], kind, operation, options)
            self.preferences["output_dir"] = options["output_dir"]
            self.preferences["collision"] = options["collision"]
            self.save_preferences()
            if start:
                self.queue.start()
                self.navigate("queue")
            self.notify(f"已将 {len(selected)} 个素材加入队列。")
        except Exception as error:
            self.error(error)

    def on_queue_changed(self):
        self.queue_dirty = True
        waiting = sum(job["status"] in {"pending", "running"} for job in self.queue.jobs)
        if hasattr(self, "nav_buttons"):
            self.nav_buttons["queue"].setText("任务队列" + (f"    {waiting}" if waiting else ""))

    def refresh_queue_if_needed(self):
        if self.pages.currentIndex() == 1 and (self.queue_dirty or self.queue.active):
            self.refresh_queue()

    def selected_job_ids(self):
        return [self.queue_table.item(row.row(), 0).data(Qt.ItemDataRole.UserRole) for row in self.queue_table.selectionModel().selectedRows()]

    def refresh_queue(self):
        self.queue_dirty = False
        selected = set(self.selected_job_ids())
        self.queue_table.blockSignals(True)
        self.queue_table.setRowCount(len(self.queue.jobs))
        self.queue_table.clearSelection()
        for row, job in enumerate(self.queue.jobs):
            title = Path(job["inputs"][0]).name + (f" 等 {len(job['inputs'])} 个文件" if len(job["inputs"]) > 1 else "")
            filename = QTableWidgetItem(icon(job["kind"]), title)
            filename.setData(Qt.ItemDataRole.UserRole, job["id"])
            filename.setToolTip("\n".join(job["inputs"]))
            self.queue_table.setItem(row, 0, filename)
            target = job["options"].get("format", "original")
            self.queue_table.setItem(row, 1, QTableWidgetItem(OP_NAMES.get(job["kind"], {}).get(job["operation"], job["operation"]) + " → " + ("原格式" if target == "original" else target.upper())))
            state = QTableWidgetItem(STATUS_NAMES.get(job["status"], job["status"]))
            state.setForeground(QColor({"success": "#a7c5ae", "failed": "#e5a0a0", "running": "#aeb7ff"}.get(job["status"], "#a2a7b3")))
            self.queue_table.setItem(row, 2, state)
            progress_cell = QWidget()
            progress_layout = QVBoxLayout(progress_cell)
            progress_layout.setContentsMargins(12, 7, 12, 8)
            progress_layout.setSpacing(5)
            progress = job.get("progress", 0)
            progress_layout.addWidget(label(job.get("message", "处理中")[:12] if progress < 0 and job["status"] == "running" else f"{max(0, int(progress))}%", "muted"))
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setRange(0, 0 if progress < 0 and job["status"] == "running" else 100)
            bar.setValue(max(0, int(progress)))
            progress_layout.addWidget(bar)
            self.queue_table.setCellWidget(row, 3, progress_cell)
            elapsed = time.time() - job["started"] if job["status"] == "running" and "started" in job else job.get("elapsed", 0)
            self.queue_table.setItem(row, 4, QTableWidgetItem(human_time(elapsed) if elapsed else "—"))
            if job["id"] in selected:
                self.queue_table.selectionModel().select(self.queue_table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.queue_table.blockSignals(False)
        counts = {status: sum(job["status"] == status for job in self.queue.jobs) for status in STATUS_NAMES}
        dispatch = "正在派发" if self.queue.enabled else "派发已暂停" if self.queue.active or counts["pending"] else "就绪"
        self.queue_summary.setText(f"{dispatch}  ·  {counts['running']} 运行中  /  {counts['pending']} 等待  /  {counts['success']} 完成  /  {counts['failed']} 失败  ·  并发 {self.preferences.get('concurrency', 2)}")
        if not selected and self.queue_table.rowCount():
            self.queue_table.selectRow(self.queue_table.rowCount() - 1)
        else:
            self.show_job_details()

    def show_job_details(self):
        selected = self.selected_job_ids()
        job = self.queue.find(selected[0]) if selected else None
        if not job:
            self.log_view.clear()
            self.job_detail.setText("选中任务可查看输出路径、错误原因及 FFmpeg 命令。")
            return
        output = job.get("output") or job["options"]["output_dir"]
        self.job_detail.setText(f"{job.get('message') or STATUS_NAMES.get(job['status'])}\n输出：{output}")
        self.job_detail.setToolTip(job.get("message", ""))
        logs = "\n".join(job.get("logs", []))
        if self.log_view.toPlainText() != logs:
            at_bottom = self.log_view.verticalScrollBar().value() >= self.log_view.verticalScrollBar().maximum() - 5
            self.log_view.setPlainText(logs)
            if at_bottom:
                self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def cancel_selected(self):
        for identifier in self.selected_job_ids():
            self.queue.cancel(identifier)

    def retry_selected(self):
        for identifier in self.selected_job_ids():
            self.queue.retry(identifier)
        self.notify("已将可重试任务放回队列；点击“开始队列”执行。")

    def open_job_output(self):
        selected = self.selected_job_ids()
        job = self.queue.find(selected[0]) if selected else None
        if job:
            self.open_folder(Path(job["output"]).parent if job.get("output") else Path(job["options"]["output_dir"]))

    def export_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出任务报告", f"{APP_ENGLISH_NAME}-report.json", "JSON (*.json)")
        if path:
            try:
                write_json(Path(path), {"application": APP_ENGLISH_NAME, "version": VERSION, "jobs": self.queue.jobs})
                self.notify("任务报告已导出；其中包含本地文件路径与处理参数。")
            except OSError as error:
                self.error(error)

    def open_folder(self, path):
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))
        except OSError as error:
            self.error(error)

    def save_preferences(self):
        try:
            write_json(STATE / "settings.json", portable_resources(self.preferences))
        except OSError as error:
            self.error(error)

    def preview_motion_settings(self, *args):
        if hasattr(self, "motion"):
            values = dict(self.preferences)
            for key, control in self.settings_controls.items():
                if key.startswith("motion_"):
                    values[key] = control.isChecked() if isinstance(control, QCheckBox) else control.value()
            self.motion.configure(values)

    def apply_settings(self):
        values = {}
        for key, control in self.settings_controls.items():
            values[key] = control.isChecked() if isinstance(control, QCheckBox) else control.text().strip() if isinstance(control, QLineEdit) else control.value()
        values = portable_resources(values)
        try:
            if not values["output_dir"]:
                raise ValueError("输出目录不能为空。")
            for name in ("ffmpeg", "ffprobe", "ffplay"):
                engine_path(name, values)
        except Exception as error:
            self.error(error)
            return
        self.preferences.update(values)
        for name in BUNDLED_PATHS:
            self.settings_controls[name].setText(values[name])
        self.motion.configure(self.preferences)
        self.inspector.output.setText(values["output_dir"])
        self.save_preferences()
        self.update_runtime_status()
        self.notify("设置已保存。已排队任务保持原参数；失败任务重试时更新引擎路径。")

    def update_runtime_status(self):
        try:
            names = [process.info["name"].lower() for process in psutil.process_iter(["name"]) if process.info["name"]]
            qq = any("qqmusic" in name for name in names)
            kuwo = "kwmusic.exe" in names
            key = resource_path(self.preferences.get("key_file") or "").is_file()
            text = f"QQ 音乐：{'运行中' if qq else '未运行'}     酷我：{'运行中' if kuwo else '未运行'}\n酷狗 key：{'已就绪' if key else '未找到'}  ·  客户端存在不代表版本一定兼容"
            self.decrypt_status.setText(text)
            ready = all((resource_path(self.preferences["ffmpeg_dir"]) / (name + ".exe")).is_file() for name in ("ffmpeg", "ffprobe", "ffplay"))
            self.settings_status.setText(("FFmpeg / FFprobe / FFplay 已就绪\n" if ready else "引擎缺失，请检查引擎目录\n") + text)
            self.engine_status.setText("本地引擎已就绪  /  不上传文件" if ready else "引擎缺失  /  请检查设置")
        except (psutil.Error, OSError, ValueError) as error:
            self.settings_status.setText(str(error))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.import_paths(paths)
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self.queue.active:
            answer = QMessageBox.question(self, "仍有任务正在运行", "退出会取消正在处理的任务，未执行任务保留在队列。是否退出？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.motion.close()
        self.queue.shutdown()
        self.queue_timer.stop()
        self.status_timer.stop()
        for player in self.players:
            if player.poll() is None:
                player.terminate()
        self.pool.waitForDone(40000)
        self.save_preferences()
        event.accept()


def run(files=None, screenshot=None):
    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName(APP_ENGLISH_NAME)
    application.setApplicationDisplayName(APP_TITLE)
    application.setApplicationVersion(VERSION)
    application.setWindowIcon(icon("brand"))
    application.setOrganizationName("MediaWorkbench")
    application.setStyle("Fusion")
    application.setFont(QFont("Microsoft YaHei UI", 9))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#101112"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e7e8ec"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#18191d"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e7e8ec"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#202127"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e7e8ec"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#5e6ad2"))
    application.setPalette(palette)
    application.setStyleSheet(STYLE)
    STATE.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(STATE / "application.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, f"{APP_NAME}已运行", f"已有一个{APP_NAME}或旧版媒体工坊窗口正在运行。请使用已打开的窗口。")
        return 0
    window = MainWindow()
    screen = application.primaryScreen().availableGeometry()
    window.resize(min(1460, screen.width() - 32), min(940, screen.height() - 48))
    window.show()
    if files:
        window.import_paths(files)
    if screenshot:
        def capture():
            destination = Path(screenshot)
            destination.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(destination))
            window.close()
        QTimer.singleShot(3500, capture)
    result = application.exec()
    lock.unlock()
    return result
