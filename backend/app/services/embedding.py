"""BGE 中文向量模型接入（fastembed ONNX 本地推理，私有化离线可用）。

首次使用自动从 hf-mirror 下载模型（约 100MB），之后本地缓存离线运行。
"""
import os

# 国内环境 huggingface.co 不可达，默认走镜像（进程内任何位置 import 都生效）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from fastembed import TextEmbedding  # noqa: E402

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DIM = 512

_model: TextEmbedding | None = None


def get_model() -> TextEmbedding:
    """进程级单例，避免重复加载 ONNX 模型。"""
    global _model
    if _model is None:
        _model = TextEmbedding(MODEL_NAME)
    return _model


def encode(texts: list[str]) -> list[list[float]]:
    """文本批量向量化，返回 512 维向量列表。"""
    if not texts:
        return []
    return [list(map(float, v)) for v in get_model().embed(texts)]
