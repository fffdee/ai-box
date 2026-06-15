"""BanBox 调音台 - 入口"""

import os
import ssl
import sys

# HuggingFace 国内镜像（加速模型下载）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 抑制 Windows 符号链接警告
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# 禁用 SSL 验证（解决代理/防火墙导致的 SSL 错误）
ssl._create_default_https_context = ssl._create_unverified_context

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from main_window import MainWindow


def main():
    # 高 DPI 支持 (必须在 QApplication 之前设置)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # 全局字体
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
