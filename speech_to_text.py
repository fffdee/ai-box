"""语音转文字模块 - 设置面板 + 统一 STT 引擎"""

import os
from PyQt5.QtCore import Qt, QSettings, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QComboBox, QLineEdit, QCheckBox,
    QGroupBox, QGridLayout, QSpinBox,
)

from ai.stt_engine import SpeechRecognizerThread, HAS_SOUNDDEVICE, HAS_VOSK, HAS_FASTER_WHISPER

# Vosk 模型路径（供下载脚本等引用）
VOSK_MODEL_PATH = os.path.join(os.path.dirname(__file__), "vosk-model", "vosk-model-small-cn-0.22")

# Whisper 可用模型
WHISPER_MODELS = {
    "tiny":      {"name": "Tiny (39M)",    "desc": "最快，精度低",   "size": "~75MB"},
    "base":      {"name": "Base (74M)",    "desc": "较快，精度一般", "size": "~145MB"},
    "small":     {"name": "Small (244M)",  "desc": "中等速度和精度", "size": "~488MB"},
    "medium":    {"name": "Medium (769M)", "desc": "较慢，精度高",   "size": "~1.5GB"},
    "large-v3":  {"name": "Large V3",      "desc": "最慢，精度最高", "size": "~3GB"},
}

# 语言列表
LANGUAGES = {
    "auto":  "自动检测",
    "zh":    "中文",
    "en":    "英文",
    "ja":    "日文",
    "ko":    "韩文",
    "de":    "德文",
    "fr":    "法文",
    "es":    "西班牙文",
}

# 识别引擎
ENGINES = {
    "vosk":   "Vosk（轻量，仅中文）",
    "whisper": "Whisper（支持中英混合，需 Python 3.8+）",
}


class SpeechToTextPanel(QWidget):
    """语音转文字面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        title = QLabel("语音转文字")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #9b59b6; padding: 4px;")
        layout.addWidget(title)

        ctrl = QHBoxLayout()
        self.start_btn = QPushButton("开始识别")
        self.start_btn.setCheckable(True)
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #2d2d44; color: #aaa; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:checked { background-color: #9b59b6; color: white; }"
        )
        ctrl.addWidget(self.start_btn)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.setFixedWidth(50)
        self.clear_btn.setStyleSheet(
            "QPushButton { background-color: #2d2d44; color: #aaa; border-radius: 4px; padding: 4px 8px; }"
            "QPushButton:hover { background-color: #3d3d54; }"
        )
        ctrl.addWidget(self.clear_btn)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self.status_lbl = QLabel("就绪")
        self.status_lbl.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(self.status_lbl)

        self.partial_lbl = QLabel("")
        self.partial_lbl.setStyleSheet("font-size: 12px; color: #f39c12; font-style: italic;")
        self.partial_lbl.setWordWrap(True)
        layout.addWidget(self.partial_lbl)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setStyleSheet(
            "QTextEdit { background-color: #1a1a2e; color: #E0E0E0; border: 1px solid #333; "
            "border-radius: 4px; font-size: 14px; padding: 8px; }"
        )
        self.result_text.setPlaceholderText("识别结果将显示在这里...")
        layout.addWidget(self.result_text, 1)

        # 引擎状态提示
        engines = []
        if HAS_VOSK:
            engines.append("Vosk")
        if HAS_FASTER_WHISPER:
            engines.append("Whisper")
        engine_info = "可用引擎: " + (", ".join(engines) if engines else "无")
        hint = QLabel(f"{engine_info} | 音源: BG Audio Card")
        hint.setStyleSheet("font-size: 9px; color: #555;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

    def append_text(self, text):
        cursor = self.result_text.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(text + "\n")
        self.result_text.setTextCursor(cursor)
        self.result_text.ensureCursorVisible()
        self.partial_lbl.setText("")

    def set_partial(self, text):
        self.partial_lbl.setText(text)

    def set_status(self, text):
        self.status_lbl.setText(text)
        if "监听" in text:
            self.status_lbl.setStyleSheet("font-size: 10px; color: #2ecc71;")
        elif "识别" in text or "加载" in text:
            self.status_lbl.setStyleSheet("font-size: 10px; color: #f39c12;")
        elif "停止" in text or "错误" in text:
            self.status_lbl.setStyleSheet("font-size: 10px; color: #e74c3c;")
        else:
            self.status_lbl.setStyleSheet("font-size: 10px; color: #888;")

    def clear_text(self):
        self.result_text.clear()
        self.partial_lbl.setText("")


class SttSettingsPanel(QWidget):
    """语音识别设置面板（嵌入系统设置）"""

    settingsChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("BanBox", "BGAICard")
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # 识别引擎
        engine_group = QGroupBox("识别引擎")
        engine_group.setStyleSheet(self._group_style("#9b59b6"))
        engine_layout = QGridLayout(engine_group)

        engine_layout.addWidget(QLabel("引擎:"), 0, 0)
        self.engine_combo = QComboBox()
        for key, name in ENGINES.items():
            available = (key == "vosk" and HAS_VOSK) or (key == "whisper" and HAS_FASTER_WHISPER)
            suffix = "" if available else " (未安装)"
            self.engine_combo.addItem(name + suffix, key)
            if not available:
                idx = self.engine_combo.count() - 1
                self.engine_combo.model().item(idx).setEnabled(False)
        self.engine_combo.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333;")
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        engine_layout.addWidget(self.engine_combo, 0, 1)

        # 引擎状态
        self.engine_status = QLabel("")
        self.engine_status.setStyleSheet("font-size: 10px; color: #888;")
        self._update_engine_status()
        engine_layout.addWidget(self.engine_status, 1, 0, 1, 2)

        layout.addWidget(engine_group)

        # Whisper 模型选择
        self.whisper_group = QGroupBox("Whisper 模型")
        self.whisper_group.setStyleSheet(self._group_style("#3498db"))
        whisper_layout = QGridLayout(self.whisper_group)

        whisper_layout.addWidget(QLabel("模型:"), 0, 0)
        self.model_combo = QComboBox()
        for key, info in WHISPER_MODELS.items():
            self.model_combo.addItem(f"{info['name']} - {info['desc']} ({info['size']})", key)
        self.model_combo.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333;")
        whisper_layout.addWidget(self.model_combo, 0, 1)

        whisper_layout.addWidget(QLabel("识别语言:"), 1, 0)
        self.lang_combo = QComboBox()
        for code, name in LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        self.lang_combo.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333;")
        whisper_layout.addWidget(self.lang_combo, 1, 1)

        whisper_hint = QLabel("首次使用模型时需下载\n推荐 small 模型，兼顾速度和精度\n需要 Python 3.8+ 环境")
        whisper_hint.setStyleSheet("font-size: 10px; color: #888;")
        whisper_layout.addWidget(whisper_hint, 2, 0, 1, 2)

        layout.addWidget(self.whisper_group)

        # 唤醒词设置
        wake_group = QGroupBox("唤醒词")
        wake_group.setStyleSheet(self._group_style("#e67e22"))
        wake_layout = QGridLayout(wake_group)

        self.wake_enabled = QCheckBox("启用唤醒词")
        self.wake_enabled.setStyleSheet("font-size: 12px; color: #E0E0E0;")
        wake_layout.addWidget(self.wake_enabled, 0, 0, 1, 2)

        wake_layout.addWidget(QLabel("唤醒词:"), 1, 0)
        self.wake_word_edit = QLineEdit()
        self.wake_word_edit.setPlaceholderText("例如: 小班、hey banbox")
        self.wake_word_edit.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        wake_layout.addWidget(self.wake_word_edit, 1, 1)

        wake_layout.addWidget(QLabel("唤醒回复:"), 2, 0)
        self.wake_reply_edit = QLineEdit()
        self.wake_reply_edit.setPlaceholderText("例如: 我在，请说")
        self.wake_reply_edit.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        wake_layout.addWidget(self.wake_reply_edit, 2, 1)

        wake_layout.addWidget(QLabel("对话超时(秒):"), 3, 0)
        self.wake_timeout_spin = QSpinBox()
        self.wake_timeout_spin.setRange(5, 120)
        self.wake_timeout_spin.setValue(30)
        self.wake_timeout_spin.setSuffix(" 秒")
        self.wake_timeout_spin.setToolTip("AI回复后等待语音输入的超时时间，超时后需重新唤醒")
        self.wake_timeout_spin.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        wake_layout.addWidget(self.wake_timeout_spin, 3, 1)

        wake_hint = QLabel("唤醒后会播放回复并等待对话\n超时后需重新说唤醒词\n留空唤醒词则显示所有识别结果")
        wake_hint.setStyleSheet("font-size: 10px; color: #888;")
        wake_layout.addWidget(wake_hint, 4, 0, 1, 2)

        layout.addWidget(wake_group)

        # 保存按钮
        save_btn = QPushButton("保存语音设置")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #9b59b6; color: white; border-radius: 4px; padding: 8px; }"
            "QPushButton:hover { background-color: #8e44ad; }"
        )
        save_btn.clicked.connect(self._save_and_apply)
        layout.addWidget(save_btn)

        layout.addStretch()

        # 初始显示状态
        self._on_engine_changed()

    def _group_style(self, color):
        return f"""
            QGroupBox {{
                background-color: #16213e; border: 1px solid {color};
                border-radius: 6px; margin-top: 12px; padding-top: 18px;
                font-weight: bold; color: {color}; font-size: 13px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 0 5px;
            }}
        """

    def _update_engine_status(self):
        parts = []
        if HAS_VOSK:
            parts.append("Vosk: 已安装")
        else:
            parts.append("Vosk: 未安装 (pip install vosk)")
        if HAS_FASTER_WHISPER:
            parts.append("Whisper: 已安装")
        else:
            parts.append("Whisper: 未安装 (需 Python 3.8+)")
        self.engine_status.setText("\n".join(parts))

    def _on_engine_changed(self, _index=None):
        engine = self.engine_combo.currentData()
        # Whisper 模型选择只在 whisper 引擎时显示
        self.whisper_group.setVisible(engine == "whisper")

    def _load_settings(self):
        default_engine = "vosk" if HAS_VOSK else ("whisper" if HAS_FASTER_WHISPER else "vosk")
        engine = self._settings.value("stt/engine", default_engine)
        model = self._settings.value("stt/whisper_model", "small")
        lang = self._settings.value("stt/language", "auto")
        wake_enabled = self._settings.value("stt/wake_enabled", False, type=bool)
        wake_word = self._settings.value("stt/wake_word", "小班")
        wake_reply = self._settings.value("stt/wake_reply", "我在，请说")
        wake_timeout = self._settings.value("stt/wake_timeout", 30, type=int)

        idx = self.engine_combo.findData(engine)
        if idx >= 0 and self.engine_combo.model().item(idx).isEnabled():
            self.engine_combo.setCurrentIndex(idx)
        idx = self.model_combo.findData(model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        idx = self.lang_combo.findData(lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.wake_enabled.setChecked(wake_enabled)
        self.wake_word_edit.setText(wake_word)
        self.wake_reply_edit.setText(wake_reply)
        self.wake_timeout_spin.setValue(wake_timeout)

    def _save_and_apply(self):
        self._settings.setValue("stt/engine", self.engine_combo.currentData())
        self._settings.setValue("stt/whisper_model", self.model_combo.currentData())
        self._settings.setValue("stt/language", self.lang_combo.currentData())
        self._settings.setValue("stt/wake_enabled", self.wake_enabled.isChecked())
        self._settings.setValue("stt/wake_word", self.wake_word_edit.text())
        self._settings.setValue("stt/wake_reply", self.wake_reply_edit.text())
        self._settings.setValue("stt/wake_timeout", self.wake_timeout_spin.value())
        self.settingsChanged.emit()

    def get_engine(self):
        return self.engine_combo.currentData()

    def get_whisper_model_name(self):
        return self.model_combo.currentData()

    def get_language(self):
        return self.lang_combo.currentData()

    def get_wake_word(self):
        return self.wake_word_edit.text().strip()

    def is_wake_word_enabled(self):
        return self.wake_enabled.isChecked()
