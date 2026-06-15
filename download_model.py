"""下载语音识别模型 - Vosk / Whisper"""
import os
import ssl
import zipfile
import requests


# ============ Vosk 模型 ============

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip"
MODEL_DIR = os.path.join(os.path.dirname(__file__), "vosk-model")
ZIP_PATH = os.path.join(os.path.dirname(__file__), "vosk-model-small-cn.zip")


def download_vosk_model():
    model_path = os.path.join(MODEL_DIR, "vosk-model-small-cn-0.22")
    if os.path.exists(model_path) and os.path.exists(os.path.join(model_path, "am", "final.mdl")):
        print(f"Vosk 模型已存在: {model_path}")
        return model_path

    if not os.path.exists(ZIP_PATH):
        print(f"下载 Vosk 模型: {MODEL_URL}")
        print("文件约 42MB，请耐心等待...")
        r = requests.get(MODEL_URL, stream=True)
        total = int(r.headers.get('content-length', 0))
        downloaded = 0
        with open(ZIP_PATH, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r下载进度: {pct}% ({downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB)", end="", flush=True)
        print("\n下载完成")
    else:
        print(f"ZIP 已存在: {ZIP_PATH}")

    print("解压模型...")
    os.makedirs(MODEL_DIR, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, 'r') as z:
        z.extractall(MODEL_DIR)
    print("解压完成")
    os.remove(ZIP_PATH)
    print("已清理 ZIP 文件")
    return model_path


# ============ Whisper 模型 ============

WHISPER_MODELS = {
    "tiny":      "Systran/faster-whisper-tiny",
    "base":      "Systran/faster-whisper-base",
    "small":     "Systran/faster-whisper-small",
    "medium":    "Systran/faster-whisper-medium",
    "large-v3":  "Systran/faster-whisper-large-v3",
}

WHISPER_CACHE_DIR = os.path.join(os.path.dirname(__file__), "whisper-models")


def download_whisper_model(model_name="base"):
    """下载 faster-whisper 模型（使用国内镜像 + 禁用 SSL 验证）"""
    if model_name not in WHISPER_MODELS:
        print(f"未知模型: {model_name}，可选: {list(WHISPER_MODELS.keys())}")
        return False

    repo_id = WHISPER_MODELS[model_name]
    print(f"下载 Whisper 模型: {model_name} ({repo_id})")

    # 设置国内镜像 + 禁用符号链接警告
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    # 禁用 SSL 验证（解决代理/防火墙导致的 SSL 错误）
    ssl._create_default_https_context = ssl._create_unverified_context

    try:
        from faster_whisper import WhisperModel
        print("正在下载模型文件，请耐心等待...")
        model = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            download_root=WHISPER_CACHE_DIR,
        )
        print(f"Whisper 模型 {model_name} 下载/加载成功！")
        return True
    except Exception as e:
        print(f"下载失败: {e}")
        print("\n备选方案：手动下载模型文件")
        print(f"1. 访问 https://hf-mirror.com/{repo_id}")
        print(f"2. 下载所有文件到 {os.path.join(WHISPER_CACHE_DIR, 'models--' + repo_id.replace('/', '--'))}")
        return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "whisper":
        model = sys.argv[2] if len(sys.argv) > 2 else "base"
        download_whisper_model(model)
    else:
        download_vosk_model()
