"""LLM 模型注册表 - 多模型配置与路径管理"""

import os
from typing import Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
LLM_MODELS_DIR = os.path.join(PROJECT_ROOT, "llm-models")

# 模型配置：id -> 元数据
# builtin=True 表示内置基础版，随应用提供；其余为可选进阶模型，需用户下载
# filenames: GGUF 文件名列表（大模型可能分片，如 00001-of-00002 + 00002-of-00002）
# llama-cpp-python 支持自动加载分片，只需指向第一个文件
LLM_MODELS: Dict[str, dict] = {
    "qwen2.5-1.5b": {
        "name": "Qwen2.5-1.5B（内置基础版）",
        "filenames": ["qwen2.5-1.5b-instruct-q4_k_m.gguf"],
        "size": "~1.1 GB",
        "desc": "内置默认模型，响应快，适合日常语音对话",
        "n_ctx": 2048,
        "max_tokens": 256,
        "repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "builtin": True,
    },
    "qwen2.5-3b": {
        "name": "Qwen2.5-3B（进阶）",
        "filenames": ["qwen2.5-3b-instruct-q4_k_m.gguf"],
        "size": "~1.8 GB",
        "desc": "更聪明，速度与理解力兼顾",
        "n_ctx": 4096,
        "max_tokens": 384,
        "repo": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "builtin": False,
    },
    "qwen2.5-7b": {
        "name": "Qwen2.5-7B（智能）",
        "filenames": [
            "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
            "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf",
        ],
        "size": "~4.7 GB",
        "desc": "最聪明，复杂问题理解最好，建议有 NVIDIA 显卡",
        "n_ctx": 4096,
        "max_tokens": 512,
        "repo": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "builtin": False,
    },
}

DEFAULT_MODEL_ID = "qwen2.5-1.5b"
SETTINGS_KEY = "llm/model"


def get_model_path(model_id: str) -> str:
    """返回模型主文件路径（分片模型指向第一个文件，llama-cpp-python 会自动加载后续分片）"""
    info = LLM_MODELS.get(model_id, LLM_MODELS[DEFAULT_MODEL_ID])
    return os.path.join(LLM_MODELS_DIR, info["filenames"][0])


def get_model_filenames(model_id: str) -> List[str]:
    """返回模型所有文件名（含分片）"""
    info = LLM_MODELS.get(model_id, LLM_MODELS[DEFAULT_MODEL_ID])
    return info["filenames"]


def is_model_downloaded(model_id: str) -> bool:
    """检查模型所有文件（含分片）是否都已下载"""
    for fname in get_model_filenames(model_id):
        path = os.path.join(LLM_MODELS_DIR, fname)
        if not os.path.isfile(path) or os.path.getsize(path) < 1024 * 1024:
            return False
    return True


def get_download_urls(model_id: str) -> List[tuple]:
    """返回下载 URL 列表，每个元素为 (mirror_url, official_url) 对应一个文件"""
    info = LLM_MODELS[model_id]
    repo = info["repo"]
    urls = []
    for filename in info["filenames"]:
        mirror = f"https://hf-mirror.com/{repo}/resolve/main/{filename}"
        official = f"https://huggingface.co/{repo}/resolve/main/{filename}"
        urls.append((filename, mirror, official))
    return urls


def get_model_info(model_id: str) -> dict:
    return LLM_MODELS.get(model_id, LLM_MODELS[DEFAULT_MODEL_ID])


def list_available_models() -> list:
    """返回已下载的模型 id 列表"""
    return [mid for mid in LLM_MODELS if is_model_downloaded(mid)]


def is_builtin_model(model_id: str) -> bool:
    return LLM_MODELS.get(model_id, {}).get("builtin", False)


def get_optional_models() -> list:
    """返回可选进阶模型 id 列表"""
    return [mid for mid, info in LLM_MODELS.items() if not info.get("builtin")]
