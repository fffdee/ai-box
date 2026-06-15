"""大语言模型设置面板 - 手动放置模型文件"""

import os
from PyQt5.QtCore import QSettings, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QHBoxLayout, QGroupBox, QLabel,
    QComboBox, QPushButton, QMessageBox, QCheckBox,
)

from ai.llm_models import (
    LLM_MODELS, DEFAULT_MODEL_ID, SETTINGS_KEY, LLM_MODELS_DIR,
    get_model_path, is_model_downloaded, get_model_info, is_builtin_model,
    get_model_filenames,
)
from ai.tools import SETTINGS_ONLINE_SEARCH, SETTINGS_ONLINE_MUSIC
from ai.vlc_runtime import get_vlc_status_text

try:
    from llama_cpp import Llama
    HAS_LLAMA = True
except ImportError:
    HAS_LLAMA = False


class LlmSettingsPanel(QWidget):
    """LLM 模型选择：手动放置 GGUF 文件到 llm-models/ 目录"""

    settingsChanged = pyqtSignal()
    modelDownloaded = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("BanBox", "BGAICard")
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("大语言模型")
        group.setStyleSheet(self._group_style("#2e86c1"))
        grid = QGridLayout(group)

        grid.addWidget(QLabel("使用模型:"), 0, 0)
        self.model_combo = QComboBox()
        self._populate_combo()
        self.model_combo.setStyleSheet(
            "background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;"
        )
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        grid.addWidget(self.model_combo, 0, 1)

        self.model_status = QLabel("")
        self.model_status.setStyleSheet("font-size: 10px; color: #888;")
        self.model_status.setWordWrap(True)
        grid.addWidget(self.model_status, 1, 0, 1, 2)

        btn_row = QHBoxLayout()

        self.open_dir_btn = QPushButton("打开模型目录")
        self.open_dir_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; border-radius: 4px; padding: 8px; }"
            "QPushButton:hover { background-color: #2ecc71; }"
        )
        self.open_dir_btn.clicked.connect(self._open_model_dir)
        btn_row.addWidget(self.open_dir_btn)

        refresh_btn = QPushButton("刷新检测")
        refresh_btn.setStyleSheet(
            "QPushButton { background-color: #f39c12; color: white; border-radius: 4px; padding: 8px; }"
            "QPushButton:hover { background-color: #f1c40f; }"
        )
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addWidget(refresh_btn)

        save_btn = QPushButton("保存并应用")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #2e86c1; color: white; border-radius: 4px; padding: 8px; }"
            "QPushButton:hover { background-color: #3498db; }"
        )
        save_btn.clicked.connect(self._save_and_apply)
        btn_row.addWidget(save_btn)
        grid.addLayout(btn_row, 2, 0, 1, 2)

        hint = QLabel(
            "将 GGUF 模型文件放入 llm-models/ 目录即可自动识别。\n"
            "支持模型：\n"
            "  qwen2.5-1.5b-instruct-q4_k_m.gguf (1.1GB 基础版)\n"
            "  qwen2.5-3b-instruct-q4_k_m.gguf (1.8GB 进阶版)\n"
            "  qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf + 00002 (4.7GB 智能版)\n"
            "7B 模型建议有 NVIDIA 显卡；放入文件后点「刷新检测」。"
        )
        hint.setStyleSheet("font-size: 10px; color: #888;")
        grid.addWidget(hint, 3, 0, 1, 2)

        if not HAS_LLAMA:
            warn = QLabel("llama-cpp-python 未安装")
            warn.setStyleSheet("font-size: 10px; color: #e74c3c;")
            grid.addWidget(warn, 4, 0, 1, 2)

        layout.addWidget(group)

        # 联网能力
        online_group = QGroupBox("联网能力")
        online_group.setStyleSheet(self._group_style("#9b59b6"))
        online_layout = QVBoxLayout(online_group)

        self.online_search_cb = QCheckBox("联网搜索（天气、新闻等实时信息）")
        self.online_search_cb.setStyleSheet("font-size: 12px; color: #E0E0E0;")
        self.online_search_cb.toggled.connect(self._on_online_toggled)
        online_layout.addWidget(self.online_search_cb)

        self.online_music_cb = QCheckBox("在线音乐（语音点播，使用内置 VLC 播放）")
        self.online_music_cb.setStyleSheet("font-size: 12px; color: #E0E0E0;")
        self.online_music_cb.toggled.connect(self._on_online_toggled)
        online_layout.addWidget(self.online_music_cb)

        self.vlc_status_lbl = QLabel(get_vlc_status_text())
        self.vlc_status_lbl.setStyleSheet("font-size: 10px; color: #2ecc71;")
        online_layout.addWidget(self.vlc_status_lbl)

        online_hint = QLabel(
            "对 AI 说「播放周杰伦晴天」「今天天气怎么样」即可触发。\n"
            "音乐通过内置 VLC 本地播放（需 yt-dlp 解析音源，已随依赖安装）。"
        )
        online_hint.setStyleSheet("font-size: 10px; color: #888;")
        online_layout.addWidget(online_hint)

        layout.addWidget(online_group)

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

    def _model_label(self, model_id, info):
        if is_model_downloaded(model_id):
            tag = "已就绪"
        else:
            tag = "未放入"
        return f"{info['name']} [{tag}] - {info['desc']} ({info['size']})"

    def _populate_combo(self):
        current = self.model_combo.currentData() if self.model_combo.count() else None
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model_id, info in LLM_MODELS.items():
            self.model_combo.addItem(self._model_label(model_id, info), model_id)
        if current:
            idx = self.model_combo.findData(current)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
        self.model_combo.blockSignals(False)

    def _on_model_changed(self):
        self._update_status()

    def _on_online_toggled(self, _checked):
        self._settings.setValue(SETTINGS_ONLINE_SEARCH, self.online_search_cb.isChecked())
        self._settings.setValue(SETTINGS_ONLINE_MUSIC, self.online_music_cb.isChecked())

    def _update_status(self):
        model_id = self.model_combo.currentData()
        if not model_id:
            return
        info = get_model_info(model_id)

        if is_model_downloaded(model_id):
            total_size = 0
            filenames = get_model_filenames(model_id)
            for fname in filenames:
                fpath = os.path.join(LLM_MODELS_DIR, fname)
                if os.path.isfile(fpath):
                    total_size += os.path.getsize(fpath)
            size_gb = total_size / (1024 ** 3)
            file_info = filenames[0] if len(filenames) == 1 else f"{len(filenames)} 个分片文件"
            self.model_status.setText(
                f"已就绪: {file_info} ({size_gb:.2f} GB)\n"
                f"上下文 {info['n_ctx']} tokens，最大生成 {info['max_tokens']} tokens"
            )
            self.model_status.setStyleSheet("font-size: 10px; color: #2ecc71;")
        else:
            # 显示需要的文件列表
            needed = []
            for fname in get_model_filenames(model_id):
                fpath = os.path.join(LLM_MODELS_DIR, fname)
                if os.path.isfile(fpath) and os.path.getsize(fpath) > 1024 * 1024:
                    size_gb = os.path.getsize(fpath) / (1024**3)
                    needed.append(f"{fname} ({size_gb:.2f} GB) ✅")
                else:
                    needed.append(f"{fname} ❌")

            self.model_status.setText(
                f"需要放入以下文件到 llm-models/ 目录:\n" + "\n".join(needed)
            )
            self.model_status.setStyleSheet("font-size: 10px; color: #e67e22;")

    def _open_model_dir(self):
        """打开模型文件目录"""
        os.makedirs(LLM_MODELS_DIR, exist_ok=True)
        # Windows 下用资源管理器打开
        os.startfile(LLM_MODELS_DIR)

    def _refresh(self):
        """刷新模型检测"""
        self._populate_combo()
        self._update_status()

    def _load_settings(self):
        model_id = self._settings.value(SETTINGS_KEY, DEFAULT_MODEL_ID)
        if not is_model_downloaded(model_id):
            model_id = DEFAULT_MODEL_ID
        idx = self.model_combo.findData(model_id)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.online_search_cb.setChecked(
            self._settings.value(SETTINGS_ONLINE_SEARCH, True, type=bool)
        )
        self.online_music_cb.setChecked(
            self._settings.value(SETTINGS_ONLINE_MUSIC, True, type=bool)
        )
        self._update_status()

    def _save_and_apply(self):
        model_id = self.model_combo.currentData()
        if not is_model_downloaded(model_id):
            QMessageBox.warning(
                self, "模型未就绪",
                "所选模型文件未放入 llm-models/ 目录。\n"
                "请将 GGUF 文件放入后点「刷新检测」。\n"
                "将暂时使用内置基础版。"
            )
            model_id = DEFAULT_MODEL_ID
            idx = self.model_combo.findData(model_id)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)

        self._settings.setValue(SETTINGS_KEY, model_id)
        self._settings.setValue(SETTINGS_ONLINE_SEARCH, self.online_search_cb.isChecked())
        self._settings.setValue(SETTINGS_ONLINE_MUSIC, self.online_music_cb.isChecked())
        # 切换模型时卸载已加载实例
        try:
            from ai.llm_engine import LLMThread
            LLMThread.unload_model()
        except Exception:
            pass
        self.settingsChanged.emit()
        self._update_status()

    def get_model_id(self) -> str:
        model_id = self.model_combo.currentData() or DEFAULT_MODEL_ID
        if is_model_downloaded(model_id):
            return model_id
        return DEFAULT_MODEL_ID if is_model_downloaded(DEFAULT_MODEL_ID) else model_id

    def refresh_model_list(self):
        self._populate_combo()
        self._update_status()
