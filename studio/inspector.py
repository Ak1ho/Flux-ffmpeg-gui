from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from studio.catalog import FORMATS, KINDS, OPERATIONS, OP_HINTS
from studio.controls import AnimatedComboBox
from studio.engine import output_kind, validate_options
from studio.paths import STATE, read_json, write_json
from studio.widgets import Field, button, combo, divider, label, spin


class Inspector(QWidget):
    enqueue = Signal(bool)
    preference_changed = Signal()

    def __init__(self, preferences: dict):
        super().__init__()
        self.setObjectName("inspector")
        self.setMinimumWidth(302)
        self.setMaximumWidth(358)
        self.preferences = preferences
        self.kind = "video"
        self.controls = {}
        self.fields = {}
        self.presets = read_json(STATE / "presets.json", {})
        if not isinstance(self.presets, dict):
            self.presets = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 22, 20, 16)
        header_layout.addWidget(label("处理设置"))
        header_layout.addStretch()
        header_layout.addWidget(label("批量应用", "badge"))
        outer.addWidget(header)
        outer.addWidget(divider())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.form = QVBoxLayout(body)
        self.form.setContentsMargins(20, 18, 20, 20)
        self.form.setSpacing(14)
        self.category = combo([(KINDS[key], key) for key in OPERATIONS])
        self.form.addWidget(Field("媒体类型", self.category))
        self.operation = AnimatedComboBox()
        self.form.addWidget(Field("处理操作", self.operation))
        self.hint = label("", "hint", True)
        self.form.addWidget(self.hint)
        self.form.addWidget(divider())
        self.preset = AnimatedComboBox()
        preset_row = QWidget()
        preset_layout = QHBoxLayout(preset_row)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.addWidget(self.preset, 1)
        preset_layout.addWidget(button("保存", self.save_preset, ghost=True))
        self.form.addWidget(Field("参数预设", preset_row))
        self.add_field("format", "输出格式", AnimatedComboBox())
        self.add_field("encoder", "视频编码器", combo([("自动 · 软件编码", "auto"), ("H.264 · x264", "libx264"), ("H.265 · x265", "libx265"), ("NVIDIA · H.264", "h264_nvenc"), ("Intel · H.264", "h264_qsv"), ("AMD · H.264", "h264_amf")]))
        self.add_field("quality", "视频质量 CRF / CQ · 越小越清晰", spin(0, 51, 23))
        self.add_field("image_quality", "图片质量 · 越大越清晰", spin(1, 100, 85))
        self.add_field("bitrate", "音频码率", combo([(f"{rate} kbps", rate) for rate in (64, 96, 128, 192, 256, 320)]))
        self.controls["bitrate"].setCurrentIndex(3)
        self.add_field("sample_rate", "采样率", combo([("与源文件一致 / 编码器自动", 0)] + [(f"{rate} Hz", rate) for rate in (16000, 22050, 24000, 44100, 48000, 96000)]))
        self.add_field("channels", "声道", combo([("保留源声道", 0), ("单声道", 1), ("立体声", 2)]))
        self.add_field("start", "开始位置（秒）", spin(0, 360000, 0, 2))
        self.add_field("end", "结束位置（秒）· 0 为结尾", spin(0, 360000, 0, 2))
        self.add_field("width", "宽度（像素）· 0 为自动", spin(0, 16384, 1280))
        self.add_field("height", "高度（像素）· 0 为自动", spin(0, 16384, 0))
        self.add_field("crop_x", "裁剪起点 X", spin(0, 16384, 0))
        self.add_field("crop_y", "裁剪起点 Y", spin(0, 16384, 0))
        self.add_field("fps", "输出帧率 · 0 保留原帧率", spin(0, 240, 0))
        self.add_field("rotation", "旋转方向", combo([("顺时针 90°", "90"), ("180°", "180"), ("逆时针 90°", "270"), ("水平翻转", "hflip"), ("垂直翻转", "vflip")]))
        self.add_field("speed", "播放速度", spin(0.25, 4, 1, 2, " ×"))
        self.add_field("loudness", "目标响度（LUFS）", spin(-36, -5, -16, 1))
        self.add_field("gain", "增益（dB）", spin(-60, 24, 0, 1))
        self.add_field("fade_in", "淡入时长（秒）", spin(0, 600, 1, 2))
        self.add_field("fade_out", "淡出时长（秒）", spin(0, 600, 1, 2))
        self.add_field("noise_floor", "噪声底（dB）", spin(-80, -20, -25, 1))
        self.asset = QLineEdit()
        self.asset.setPlaceholderText("选择水印图片或字幕文件")
        asset_row = QWidget()
        asset_layout = QHBoxLayout(asset_row)
        asset_layout.setContentsMargins(0, 0, 0, 0)
        asset_layout.addWidget(self.asset, 1)
        asset_layout.addWidget(button("…", self.choose_asset))
        self.controls["asset"] = self.asset
        self.fields["asset"] = Field("水印图片 / 字幕文件", asset_row)
        self.form.addWidget(self.fields["asset"])
        self.consent = QCheckBox("我有权处理这些音频，仅用于授权用途")
        self.consent.setChecked(bool(preferences.get("decrypt_consent")))
        self.consent.setToolTip("解密调用原项目引擎，不绕过登录、购买或订阅条件。")
        self.consent.stateChanged.connect(self.save_consent)
        self.form.addWidget(self.consent)
        self.strip_metadata = QCheckBox("移除元数据")
        self.form.addWidget(self.strip_metadata)
        self.form.addWidget(divider())
        self.output = QLineEdit(preferences["output_dir"])
        self.output.setToolTip("所有输出写入此目录；默认自动重命名，不覆盖源文件。")
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.output, 1)
        output_layout.addWidget(button("…", self.choose_output))
        self.form.addWidget(Field("输出目录", output_row))
        self.collision = combo([("自动重命名（推荐）", "rename"), ("跳过同名文件", "skip"), ("覆盖已有输出（不覆盖源文件）", "overwrite")])
        self.collision.setCurrentIndex(max(0, self.collision.findData(preferences.get("collision"))))
        self.form.addWidget(Field("同名文件处理", self.collision))
        self.form.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        outer.addWidget(divider())
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(20, 16, 20, 18)
        self.selection_text = label("选择素材后即可开始", "muted")
        footer_layout.addWidget(self.selection_text)
        self.start_button = button("开始处理", lambda: self.enqueue.emit(True), "play", True)
        self.start_button.setMinimumHeight(28)
        footer_layout.addWidget(self.start_button)
        self.queue_button = button("仅加入队列", lambda: self.enqueue.emit(False), "plus", ghost=True)
        footer_layout.addWidget(self.queue_button)
        outer.addWidget(footer)
        self.category.currentIndexChanged.connect(lambda: self.set_kind(self.category.currentData()))
        self.operation.currentIndexChanged.connect(self.update_fields)
        self.controls["format"].currentIndexChanged.connect(self.update_codec_fields)
        self.preset.activated.connect(self.load_preset)
        self.set_kind("video")

    def add_field(self, name, title, control):
        self.controls[name] = control
        self.fields[name] = Field(title, control)
        self.form.addWidget(self.fields[name])

    def set_kind(self, kind):
        if kind not in OPERATIONS:
            return
        old_operation = self.operation.currentData()
        self.kind = kind
        self.category.blockSignals(True)
        self.category.setCurrentIndex(self.category.findData(kind))
        self.category.blockSignals(False)
        self.operation.blockSignals(True)
        self.operation.clear()
        for value, title in OPERATIONS[kind]:
            self.operation.addItem(title, value)
        self.operation.setCurrentIndex(max(0, self.operation.findData(old_operation)))
        self.operation.blockSignals(False)
        self.update_fields()

    def update_fields(self):
        operation = self.operation.currentData() or "convert"
        self.hint.setText(OP_HINTS.get(operation, ""))
        target_control = self.controls["format"]
        previous = target_control.currentData()
        target_control.blockSignals(True)
        target_control.clear()
        formats = FORMATS["decrypt" if self.kind == "decrypt" else output_kind(self.kind, operation)]
        if operation == "gif":
            formats = ["gif"]
        if operation == "snapshot":
            formats = ["png", "jpg", "webp"]
        for value in formats:
            target_control.addItem("保留解密后的原始格式" if value == "original" else value.upper(), value)
        target_control.setCurrentIndex(max(0, target_control.findData(previous)))
        target_control.blockSignals(False)
        common = {"format"}
        if self.kind == "video" and operation not in {"extract", "gif", "snapshot", "remux"}:
            common |= {"encoder", "quality", "bitrate", "fps"}
        if self.kind == "audio" or operation == "extract":
            common |= {"bitrate", "sample_rate", "channels"}
        if self.kind == "image" or operation == "snapshot":
            common |= {"image_quality"}
        extras = {
            "trim": {"start", "end"}, "resize": {"width", "height"}, "crop": {"width", "height", "crop_x", "crop_y"}, "rotate": {"rotation"}, "speed": {"speed"}, "normalize": {"loudness"}, "volume": {"gain"}, "fade": {"fade_in", "fade_out"}, "denoise": {"noise_floor"}, "watermark": {"asset"}, "subtitle": {"asset"}, "gif": {"start", "end", "width", "fps"}, "snapshot": {"start"},
        }
        visible = common | extras.get(operation, set())
        for name, field in self.fields.items():
            field.setVisible(name in visible)
        self.consent.setVisible(self.kind == "decrypt")
        self.strip_metadata.setVisible(operation != "remux")
        self.update_codec_fields()
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItem("自定义参数", "")
        if self.kind == "video" and operation in {"convert", "compress", "resize"}:
            self.preset.addItem("通用 MP4 · 质量优先", "builtin:quality")
            self.preset.addItem("通用 MP4 · 较小体积", "builtin:small")
        for name, preset in self.presets.items():
            if preset.get("kind") == self.kind and preset.get("operation") == operation:
                self.preset.addItem(name, name)
        self.preset.blockSignals(False)

    def update_codec_fields(self):
        target = self.controls["format"].currentData()
        if self.kind == "decrypt":
            for name in ("bitrate", "sample_rate", "channels"):
                self.fields[name].setVisible(target != "original")
            self.strip_metadata.setVisible(target != "original")
        if self.kind in {"audio", "decrypt"} or self.operation.currentData() == "extract":
            self.fields["bitrate"].setVisible(target in {"mp3", "m4a", "aac", "opus"})
        if self.kind == "image" or self.operation.currentData() == "snapshot":
            self.fields["image_quality"].setVisible(target in {"jpg", "webp", "avif"})

    def options(self) -> dict:
        values = dict(self.preferences)
        values.update({"output_dir": self.output.text().strip(), "collision": self.collision.currentData(), "strip_metadata": self.strip_metadata.isChecked(), "decrypt_consent": self.consent.isChecked()})
        for name, control in self.controls.items():
            if name != "format" and self.fields[name].isHidden():
                continue
            values[name] = control.currentData() if isinstance(control, QComboBox) else control.text() if isinstance(control, QLineEdit) else control.value()
        if not values["output_dir"]:
            raise ValueError("请选择输出目录。")
        validate_options(self.kind, self.operation.currentData(), values)
        return values

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output.text())
        if path:
            self.output.setText(path)
            self.preferences["output_dir"] = path
            self.preference_changed.emit()

    def choose_asset(self):
        filters = "字幕 (*.srt *.ass *.ssa)" if self.operation.currentData() == "subtitle" else "水印图片 (*.png *.jpg *.jpeg *.webp *.bmp)"
        path, _ = QFileDialog.getOpenFileName(self, "选择附件", "", filters)
        if path:
            self.asset.setText(path)

    def save_consent(self):
        self.preferences["decrypt_consent"] = self.consent.isChecked()
        self.preference_changed.emit()

    def save_preset(self):
        name, accepted = QInputDialog.getText(self, "保存参数预设", "预设名称")
        if not accepted or not name.strip():
            return
        values = {}
        for key, control in self.controls.items():
            if key == "asset":
                continue
            values[key] = control.currentData() if isinstance(control, QComboBox) else control.value()
        self.presets[name.strip()] = {"kind": self.kind, "operation": self.operation.currentData(), "values": values}
        write_json(STATE / "presets.json", self.presets)
        self.update_fields()
        self.preset.setCurrentIndex(self.preset.findData(name.strip()))

    def load_preset(self):
        name = self.preset.currentData()
        if not name:
            return
        if name.startswith("builtin:"):
            values = {"format": "mp4", "encoder": "auto", "quality": 20 if name == "builtin:quality" else 29, "bitrate": 192 if name == "builtin:quality" else 128}
        else:
            values = self.presets.get(name, {}).get("values", {})
        for key, value in values.items():
            control = self.controls.get(key)
            if isinstance(control, QComboBox):
                index = control.findData(value)
                if index >= 0:
                    control.setCurrentIndex(index)
            elif control and hasattr(control, "setValue"):
                control.setValue(value)

    def set_count(self, count: int):
        self.selection_text.setText(f"将处理 {count} 个素材 · 原文件保留" if count else "选择素材后即可开始")
        self.start_button.setEnabled(count > 0)
        self.queue_button.setEnabled(count > 0)
