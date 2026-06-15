"""BanBox 调音台主窗口"""

import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QComboBox, QStatusBar,
    QTabWidget, QScrollArea, QSplitter, QFrame, QMenuBar,
    QAction, QMessageBox, QToolBar, QSizePolicy, QApplication,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon

from serial_comm import BanBoxSerial
from widgets import (
    ChannelStrip, VUMeter, FxPanel, EqPanel, SystemPanel,
)
from waveform import WaveformDisplay, SpectrumDisplay, AudioCaptureThread, HAS_SOUNDDEVICE, find_bg_audio_device_index
from speech_to_text import SttSettingsPanel, HAS_VOSK, HAS_FASTER_WHISPER
from ai_assistant import AIAssistantPanel


class MainWindow(QMainWindow):
    """BanBox 调音台主窗口"""

    def __init__(self):
        super().__init__()
        self.device = BanBoxSerial(self)
        self._vu_timer = QTimer(self)
        self._vu_timer.timeout.connect(self._decay_vu)
        self._vu_timer.start(50)

        # 音频采集
        self._audio_capture = None
        self._audio_active = False

        # 语音识别
        self._speech_thread = None

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setWindowTitle("BanBox 调音台 - DSP 音效器控制")
        self.setMinimumSize(1280, 800)
        self.setStyleSheet(self._main_style())

        self._setup_menu()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # 顶部：连接栏
        main_layout.addWidget(self._create_connection_bar())

        # 中间：分割器
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter, 1)

        # 左侧：通道条 + VU表
        left_panel = self._create_mixer_panel()
        splitter.addWidget(left_panel)

        # 中间：音效 + EQ + 系统设置
        center_panel = self._create_center_panel()
        splitter.addWidget(center_panel)

        # 右侧：波形显示
        right_panel = self._create_waveform_panel()
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 3)

        # 状态栏
        self.statusBar().showMessage("未连接")
        self.statusBar().setStyleSheet("color: #aaa;")

    def _main_style(self):
        return """
            QMainWindow { background-color: #0d1117; }
            QWidget { background-color: #0d1117; color: #E0E0E0; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; }
            QLabel { color: #E0E0E0; }
            QGroupBox { color: #E0E0E0; }
            QComboBox { background-color: #1a1a2e; color: #E0E0E0; border: 1px solid #333; border-radius: 4px; padding: 4px 8px; min-width: 120px; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background-color: #1a1a2e; color: #E0E0E0; selection-background-color: #2e86c1; }
            QPushButton { background-color: #2d2d44; color: #E0E0E0; border: 1px solid #444; border-radius: 4px; padding: 6px 16px; }
            QPushButton:hover { background-color: #3d3d54; border-color: #666; }
            QPushButton:pressed { background-color: #1a1a2e; }
            QStatusBar { background-color: #0d1117; border-top: 1px solid #222; }
            QMenuBar { background-color: #16213e; color: #E0E0E0; }
            QMenuBar::item:selected { background-color: #2e86c1; }
            QMenu { background-color: #16213e; color: #E0E0E0; border: 1px solid #333; }
            QMenu::item:selected { background-color: #2e86c1; }
            QTabWidget::pane { border: 1px solid #2d3a5e; background-color: #0d1117; }
            QTabBar::tab { background-color: #16213e; color: #aaa; padding: 6px 16px; border: 1px solid #2d3a5e; border-bottom: none; border-radius: 4px 4px 0 0; }
            QTabBar::tab:selected { background-color: #0d1117; color: #E0E0E0; border-bottom: 2px solid #2e86c1; }
            QScrollArea { border: none; }
            QRadioButton { color: #E0E0E0; }
            QCheckBox { color: #E0E0E0; }
        """

    def _setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        save_action = QAction("保存参数", self)
        save_action.triggered.connect(self._save_params)
        file_menu.addAction(save_action)
        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        device_menu = menubar.addMenu("设备")
        sys_info_action = QAction("系统信息", self)
        sys_info_action.triggered.connect(self._show_sys_info)
        device_menu.addAction(sys_info_action)

        help_menu = menubar.addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_connection_bar(self):
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: #16213e; border: 1px solid #2d3a5e; border-radius: 6px; }"
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 6, 10, 6)

        layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self._refresh_ports()
        layout.addWidget(self.port_combo)

        refresh_btn = QPushButton("刷新")
        refresh_btn.setFixedWidth(60)
        refresh_btn.clicked.connect(self._refresh_ports)
        layout.addWidget(refresh_btn)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; font-weight: bold; border-radius: 4px; padding: 6px 20px; }"
            "QPushButton:hover { background-color: #2ecc71; }"
        )
        self.connect_btn.clicked.connect(self._toggle_connection)
        layout.addWidget(self.connect_btn)

        layout.addStretch()

        self.conn_status = QLabel("● 未连接")
        self.conn_status.setStyleSheet("color: #e74c3c; font-weight: bold;")
        layout.addWidget(self.conn_status)

        self.battery_lbl = QLabel("")
        self.battery_lbl.setStyleSheet("color: #aaa;")
        layout.addWidget(self.battery_lbl)

        return frame

    def _create_mixer_panel(self):
        """创建调音台混音面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("混音器")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #4a90d9; padding: 4px;")
        layout.addWidget(title)

        strips_layout = QHBoxLayout()
        strips_layout.setSpacing(4)

        channels = [
            ("g1", "吉他1", "#e74c3c"),
            ("g2", "吉他2", "#e67e22"),
            ("m1", "MIC1", "#2ecc71"),
            ("m2", "MIC2", "#3498db"),
        ]

        self.channel_strips = {}
        for ch_id, ch_name, color in channels:
            strip = ChannelStrip(ch_id, ch_name, color)
            strip.volumeChanged.connect(self._on_volume_changed)
            strip.muteChanged.connect(self._on_mute_changed)
            self.channel_strips[ch_id] = strip
            strips_layout.addWidget(strip)

        # VU 表
        vu_container = QVBoxLayout()
        vu_lbl = QLabel("VU")
        vu_lbl.setAlignment(Qt.AlignCenter)
        vu_lbl.setStyleSheet("font-weight: bold; font-size: 11px; color: #aaa;")
        vu_container.addWidget(vu_lbl)

        self.vu_meter = VUMeter()
        vu_container.addWidget(self.vu_meter)
        vu_container.addStretch()
        strips_layout.addLayout(vu_container)

        # 主输出通道
        master_strip = ChannelStrip("o", "主输出", "#9b59b6")
        master_strip.fader.setValue(80)
        master_strip.volumeChanged.connect(self._on_volume_changed)
        master_strip.muteChanged.connect(self._on_mute_changed)
        self.channel_strips["o"] = master_strip
        strips_layout.addWidget(master_strip)

        layout.addLayout(strips_layout)

        # 保存按钮
        save_btn = QPushButton("保存音频设置")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #2e86c1; color: white; border-radius: 4px; padding: 6px; }"
            "QPushButton:hover { background-color: #3498db; }"
        )
        save_btn.clicked.connect(lambda: self.device.save_audio())
        layout.addWidget(save_btn)

        return panel

    def _create_center_panel(self):
        """创建中间面板：音效 / 均衡调节 / 系统设置 / AI助手"""
        tabs = QTabWidget()

        # 音效标签页
        self.fx_panel = FxPanel()
        fx_scroll = QScrollArea()
        fx_scroll.setWidgetResizable(True)
        fx_scroll.setWidget(self.fx_panel)
        tabs.addTab(fx_scroll, "音效")

        # 均衡调节标签页
        self.eq_panel = EqPanel()
        tabs.addTab(self.eq_panel, "均衡调节")

        # 系统设置标签页
        self.system_panel = SystemPanel()
        sys_scroll = QScrollArea()
        sys_scroll.setWidgetResizable(True)
        sys_scroll.setWidget(self.system_panel)
        tabs.addTab(sys_scroll, "系统设置")

        # AI 助手标签页
        self.ai_panel = AIAssistantPanel()
        self.ai_panel.set_device(self.device)
        tabs.addTab(self.ai_panel, "AI助手")

        return tabs

    def _create_waveform_panel(self):
        """创建右侧面板：波形监视器"""
        wave_panel = QWidget()
        wave_layout = QVBoxLayout(wave_panel)
        wave_layout.setContentsMargins(0, 0, 0, 0)
        wave_layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("波形监视器")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #00ff88; padding: 4px;")
        header.addWidget(title)
        header.addStretch()

        # 波形开关
        self.waveform_btn = QPushButton("启动波形")
        self.waveform_btn.setCheckable(True)
        self.waveform_btn.setStyleSheet(
            "QPushButton { background-color: #2d2d44; color: #aaa; border-radius: 4px; padding: 4px 12px; }"
            "QPushButton:checked { background-color: #00ff88; color: #000; }"
        )
        self.waveform_btn.clicked.connect(self._toggle_waveform)
        header.addWidget(self.waveform_btn)

        # 音源选择
        header.addWidget(QLabel("音源:"))
        self.source_combo = QComboBox()
        self._populate_audio_devices()
        self.source_combo.setFixedWidth(180)
        header.addWidget(self.source_combo)

        # 刷新设备按钮
        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.setToolTip("刷新音频设备")
        self.refresh_btn.setFixedWidth(32)
        self.refresh_btn.setStyleSheet(
            "QPushButton { background-color: #2d2d44; color: #aaa; border-radius: 4px; padding: 4px; }"
            "QPushButton:hover { background-color: #3d3d5c; }"
        )
        self.refresh_btn.clicked.connect(self._populate_audio_devices)
        header.addWidget(self.refresh_btn)

        wave_layout.addLayout(header)

        # 设备状态
        self.audio_status_lbl = QLabel("")
        self.audio_status_lbl.setStyleSheet("font-size: 10px; color: #888;")
        wave_layout.addWidget(self.audio_status_lbl)

        # 波形显示
        self.waveform_display = WaveformDisplay()
        wave_layout.addWidget(self.waveform_display, 3)

        # 频谱显示
        self.spectrum_display = SpectrumDisplay()
        wave_layout.addWidget(self.spectrum_display, 2)

        return wave_panel

    def _populate_audio_devices(self):
        """填充音频设备列表"""
        self.source_combo.clear()
        # 自动检测 BG Audio Card
        bg_idx = find_bg_audio_device_index()
        if bg_idx is not None:
            self.source_combo.addItem("BG Audio Card (USB)", bg_idx)
        else:
            self.source_combo.addItem("BG Audio Card (未找到)", "bg_card")
        if HAS_SOUNDDEVICE:
            try:
                import sounddevice as sd
                for i, dev in enumerate(sd.query_devices()):
                    if dev['max_input_channels'] > 0 and i != bg_idx:
                        self.source_combo.addItem(dev['name'], i)
            except Exception:
                pass

    # ---- 信号连接 ----

    def _connect_signals(self):
        self.device.connection_changed.connect(self._on_connection_changed)
        self.device.response_received.connect(self._on_response)
        self.device.error_occurred.connect(self._on_error)

        # FX 面板
        self.fx_panel.drcThresholdChanged.connect(self._on_drc_threshold)
        self.fx_panel.drcRatioChanged.connect(self._on_drc_ratio)
        self.fx_panel.drcAttackChanged.connect(self._on_drc_attack)
        self.fx_panel.drcReleaseChanged.connect(self._on_drc_release)
        self.fx_panel.reverbRoomSizeChanged.connect(self._on_reverb_room)
        self.fx_panel.reverbDampingChanged.connect(self._on_reverb_damp)
        self.fx_panel.reverbWetChanged.connect(self._on_reverb_wet)
        self.fx_panel.saveClicked.connect(self._on_fx_save)

        # EQ 面板
        self.eq_panel.bandChanged.connect(self._on_eq_band_changed)
        self.eq_panel.nodeChanged.connect(self._on_eq_node_changed)
        self.eq_panel.saveClicked.connect(self._on_eq_save)

        # 系统设置面板
        self.system_panel.lpChanged.connect(self.device.lp_set)
        self.system_panel.lpTimeoutChanged.connect(self.device.lp_timeout)
        self.system_panel.modeMainClicked.connect(self.device.set_mode_main)
        self.system_panel.modeSecondaryClicked.connect(self.device.set_mode_secondary)
        self.system_panel.saveClicked.connect(lambda: self.device.param_save())
        self.system_panel.rebootClicked.connect(self._reboot_device)

    # ---- 连接管理 ----

    def _refresh_ports(self):
        self.port_combo.clear()
        ports = BanBoxSerial.list_ports()
        for port_name, desc in ports:
            self.port_combo.addItem(f"{port_name} - {desc}", port_name)

    def _toggle_connection(self):
        if self.device.is_connected():
            self.device.disconnect()
        else:
            idx = self.port_combo.currentIndex()
            if idx < 0:
                QMessageBox.warning(self, "提示", "请先选择串口")
                return
            port_name = self.port_combo.itemData(idx)
            if not self.device.connect(port_name):
                QMessageBox.warning(self, "连接失败", "无法连接到设备")

    def _on_connection_changed(self, connected):
        if connected:
            self.connect_btn.setText("断开")
            self.connect_btn.setStyleSheet(
                "QPushButton { background-color: #e74c3c; color: white; font-weight: bold; border-radius: 4px; padding: 6px 20px; }"
                "QPushButton:hover { background-color: #c0392b; }"
            )
            self.conn_status.setText("● 已连接")
            self.conn_status.setStyleSheet("color: #2ecc71; font-weight: bold;")
            self.statusBar().showMessage("已连接")
        else:
            self.connect_btn.setText("连接")
            self.connect_btn.setStyleSheet(
                "QPushButton { background-color: #27ae60; color: white; font-weight: bold; border-radius: 4px; padding: 6px 20px; }"
                "QPushButton:hover { background-color: #2ecc71; }"
            )
            self.conn_status.setText("● 未连接")
            self.conn_status.setStyleSheet("color: #e74c3c; font-weight: bold;")
            self.statusBar().showMessage("未连接")

    # ---- 混音器控制 ----

    def _on_volume_changed(self, channel, value):
        self.device.set_volume(channel, value)

    def _on_mute_changed(self, channel, muted):
        # 所有通道静音都发送命令：静音时发0，解除静音时恢复当前音量
        if muted:
            self.device.set_volume(channel, 0)
        else:
            strip = self.channel_strips.get(channel)
            if strip:
                self.device.set_volume(channel, strip.fader.value())

    def _decay_vu(self):
        self.vu_meter.decay_peak()

    # ---- FX 音效控制 ----

    def _on_drc_threshold(self, val):
        # val 范围 -60 ~ 0 dB, 传给设备需要 x100
        self.device.drc_set_threshold(val)

    def _on_drc_ratio(self, val):
        # val 范围 10 ~ 200, 实际比率 = val / 10
        self.device.drc_set_ratio(val / 10.0)

    def _on_drc_attack(self, val):
        self.device.drc_set_attack(val)

    def _on_drc_release(self, val):
        self.device.drc_set_release(val)

    def _on_reverb_room(self, val):
        self.device.reverb_set_room_size(val)

    def _on_reverb_damp(self, val):
        self.device.reverb_set_damping(val)

    def _on_reverb_wet(self, val):
        self.device.reverb_set_wet(val)

    def _on_fx_save(self):
        self.device.chain_save()
        self.statusBar().showMessage("音效设置已保存", 2000)

    # ---- EQ 控制 ----

    def _on_eq_band_changed(self, node_id, band_data):
        """EQ 频段参数变化"""
        idx = None
        for i, bc in enumerate(self.eq_panel.band_controls):
            if bc.get_band_data() == band_data:
                idx = i
                break
        if idx is None:
            return

        # 发送 fx 命令
        gain_x10 = int(band_data["gain"] * 10)
        self.device.fx_set_eq_band(node_id, idx, gain_x10)

        # 如果类型/频率/Q 变了也发送
        self.device.fx_set_eq_band_type(node_id, idx, band_data["type"])
        self.device.fx_set_eq_band_f0(node_id, idx, band_data["f0"])
        self.device.fx_set_eq_band_q(node_id, idx, int(band_data["Q"] * 100))
        self.device.fx_set_eq_band_enable(node_id, idx, 1 if band_data["enable"] else 0)

    def _on_eq_node_changed(self, node_id):
        """EQ 节点切换"""
        self.device.fx_query(node_id)

    def _on_eq_save(self):
        self.device.chain_save()
        self.statusBar().showMessage("EQ 设置已保存", 2000)

    # ---- 波形显示 ----

    def _toggle_waveform(self, checked):
        if checked:
            self.waveform_btn.setText("停止波形")
            self._start_audio_capture()
        else:
            self.waveform_btn.setText("启动波形")
            self._stop_audio_capture()

    def _start_audio_capture(self):
        """启动音频采集 - 仅从 USB 声卡读取麦克风输入"""
        self._audio_active = True

        if not HAS_SOUNDDEVICE:
            self.audio_status_lbl.setText("未安装 sounddevice，无法采集音频")
            self.audio_status_lbl.setStyleSheet("font-size: 10px; color: #e74c3c;")
            self.waveform_btn.setChecked(False)
            self.waveform_btn.setText("启动波形")
            self._audio_active = False
            return

        # 获取选定的音频输入设备
        selected = self.source_combo.currentData()
        device_index = None

        if isinstance(selected, int):
            # 已经是设备索引（BG Audio Card 或手动选择）
            device_index = selected
        elif selected == "bg_card":
            # 未找到设备时尝试重新检测
            device_index = find_bg_audio_device_index()
            if device_index is None:
                self.audio_status_lbl.setText("未找到 BG Audio Card (USB VID:1234 PID:1234)，请确认设备已连接")
                self.audio_status_lbl.setStyleSheet("font-size: 10px; color: #e74c3c;")
                self.waveform_btn.setChecked(False)
                self.waveform_btn.setText("启动波形")
                self._audio_active = False
                return
        else:
            self.audio_status_lbl.setText("未选择音频设备")
            self.audio_status_lbl.setStyleSheet("font-size: 10px; color: #e74c3c;")
            self.waveform_btn.setChecked(False)
            self.waveform_btn.setText("启动波形")
            self._audio_active = False
            return

        # 启动采集线程
        self._audio_capture = AudioCaptureThread(self)
        self._audio_capture._device_index = device_index
        self._audio_capture.data_ready.connect(self._on_audio_data)
        self._audio_capture.start()
        self.audio_status_lbl.setText(f"正在采集 USB 麦克风输入 (设备 #{device_index})")
        self.audio_status_lbl.setStyleSheet("font-size: 10px; color: #2ecc71;")

    def _stop_audio_capture(self):
        """停止音频采集"""
        self._audio_active = False
        if self._audio_capture is not None:
            self._audio_capture.stop()
            self._audio_capture = None
        self.audio_status_lbl.setText("")
        # 清空波形
        self.waveform_display.update_data(np.zeros(1024), np.zeros(1024))

    def _on_audio_data(self, left, right):
        """处理真实音频数据（仅来自 USB 麦克风输入）"""
        if not self._audio_active:
            return

        self.waveform_display.update_data(left, right)

        # 频谱
        fft = np.fft.rfft(left)
        freqs = np.fft.rfftfreq(len(left), 1 / 48000)
        mags = 20 * np.log10(np.abs(fft) + 1e-10)
        self.spectrum_display.update_data(freqs[1:], mags[1:])

        # VU 表
        l_level = min(1.0, np.max(np.abs(left)) * 2)
        r_level = min(1.0, np.max(np.abs(right)) * 2)
        self.vu_meter.set_levels(l_level, r_level)

    # ---- 响应处理 ----

    def _on_response(self, line):
        self.statusBar().showMessage(line, 3000)
        if "%" in line and "bat" in line.lower():
            self.battery_lbl.setText(f"🔋 {line.strip()}")

    def _on_error(self, msg):
        self.statusBar().showMessage(f"错误: {msg}")
        QMessageBox.warning(self, "错误", msg)

    # ---- 菜单动作 ----

    def _save_params(self):
        self.device.param_save()
        self.statusBar().showMessage("参数已保存", 2000)

    def _show_sys_info(self):
        def on_info(lines):
            text = "\n".join(lines) if lines else "无响应"
            QMessageBox.information(self, "系统信息", text)
        self.device.sys_info(on_info)

    def _reboot_device(self):
        reply = QMessageBox.question(
            self, "确认", "确定要重启设备吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.device.send_command("sys -b", wait_response=False)

    def _show_about(self):
        QMessageBox.about(
            self, "关于",
            "BanBox 调音台 v1.0\n\n"
            "DSP 音效器控制上位机\n"
            "基于 USB CDC Shell 协议\n\n"
            "支持通道音量、DRC/混响音效、5节点10频段EQ调节\n"
            "系统设置（低功耗/设备模式）\n"
            "实时波形与频谱显示（BG Audio Card）"
        )

    def closeEvent(self, event):
        self._stop_audio_capture()
        self.ai_panel.cleanup()
        self._vu_timer.stop()
        self.device.disconnect()
        event.accept()
