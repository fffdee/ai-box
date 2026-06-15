"""下载 Whisper 模型 - 绕过代理"""
import os
import ssl
import requests
import json

ssl._create_default_https_context = ssl._create_unverified_context

MIRROR = "https://hf-mirror.com"
REPO = "Systran/faster-whisper-base"
SAVE_DIR = os.path.join(os.path.dirname(__file__), "whisper-models", "models--Systran--faster-whisper-base")

# 不走代理
NO_PROXY = {"http": None, "https": None}


def download_file(url, save_path, desc=""):
    """下载文件，带进度显示"""
    try:
        r = requests.get(url, timeout=120, verify=False, stream=True, proxies=NO_PROXY)
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    mb_down = downloaded // 1024 // 1024
                    mb_total = total // 1024 // 1024
                    print(f"\r  {desc} {pct}% ({mb_down}MB / {mb_total}MB)", end="", flush=True)
        print()
        return True
    except Exception as e:
        print(f"\n  下载失败: {e}")
        return False


def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    blobs_dir = os.path.join(SAVE_DIR, "blobs")
    os.makedirs(blobs_dir, exist_ok=True)

    # 获取文件列表
    print(f"获取模型文件列表: {MIRROR}/{REPO}")
    try:
        r = requests.get(f"{MIRROR}/api/models/{REPO}", timeout=15, verify=False, proxies=NO_PROXY)
        data = r.json()
        siblings = data.get("siblings", [])
    except Exception as e:
        print(f"获取失败: {e}")
        return

    print(f"共 {len(siblings)} 个文件:")
    for s in siblings:
        size_mb = s.get("size", 0) // 1024 // 1024
        print(f"  {s['rfilename']} ({size_mb}MB)")

    # 下载所有文件
    for s in siblings:
        fname = s["rfilename"]
        save_path = os.path.join(blobs_dir, fname.replace("/", "_"))
        if os.path.exists(save_path):
            existing_size = os.path.getsize(save_path)
            expected_size = s.get("size", 0)
            if existing_size == expected_size or expected_size == 0:
                print(f"  已存在: {fname}")
                continue
            else:
                print(f"  文件不完整，重新下载: {fname}")
                os.remove(save_path)

        url = f"{MIRROR}/{REPO}/resolve/main/{fname}"
        size_mb = s.get("size", 0) // 1024 // 1024
        print(f"  下载: {fname} ({size_mb}MB)")
        if not download_file(url, save_path, fname):
            print(f"  尝试官方源...")
            official_url = f"https://huggingface.co/{REPO}/resolve/main/{fname}"
            if not download_file(official_url, save_path, fname):
                print(f"  官方源也失败，跳过")

    # 构建 HuggingFace cache 格式的 snapshots 目录
    print("\n构建缓存目录结构...")
    snapshots_dir = os.path.join(SAVE_DIR, "snapshots")
    # 读取 commit hash
    refs_dir = os.path.join(SAVE_DIR, "refs")
    os.makedirs(refs_dir, exist_ok=True)
    commit_hash = "main"
    ref_file = os.path.join(refs_dir, "main")
    if not os.path.exists(ref_file):
        with open(ref_file, "w") as f:
            f.write(commit_hash)

    snap_dir = os.path.join(snapshots_dir, commit_hash)
    os.makedirs(snap_dir, exist_ok=True)

    # 创建符号链接或复制小文件到 snapshots
    for s in siblings:
        fname = s["rfilename"]
        blob_path = os.path.join(blobs_dir, fname.replace("/", "_"))
        snap_path = os.path.join(snap_dir, fname)
        if os.path.exists(blob_path) and not os.path.exists(snap_path):
            snap_subdir = os.path.dirname(snap_path)
            os.makedirs(snap_subdir, exist_ok=True)
            # Windows 可能不支持符号链接，直接复制
            import shutil
            shutil.copy2(blob_path, snap_path)

    print("\n下载完成！")
    print(f"模型路径: {SAVE_DIR}")
    print("现在可以用 faster-whisper 加载模型了")


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
