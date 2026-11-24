"""应用配置：全部通过环境变量覆盖，本地默认 SQLite 零依赖启动。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]  # 项目根目录（backend/app/core/config.py 上溯 4 层）


class Settings(BaseSettings):
    # env_file 用绝对路径，保证 uvicorn / celery 以任意工作目录启动都能加载
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "企业智能合同审查平台"
    DEBUG: bool = True

    # 数据库：本地默认 SQLite；Docker 环境切换为 postgresql+psycopg2://...
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'storage' / 'contract.db'}"

    # Redis（Celery broker / SSE 事件通道），本地未启用可为空
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 720

    # 文件存储
    STORAGE_DIR: Path = BASE_DIR / "storage"
    UPLOAD_MAX_MB: int = 50

    # 模型服务（OpenAI 兼容协议，阶段 2 使用）
    LLM_BASE_URL: str = "http://localhost:8001/v1"
    LLM_API_KEY: str = "sk-local"
    LLM_MODEL: str = "deepseek-chat"

    # 向量检索（阶段 2 使用）：为空走 milvus-lite 本地文件，生产填 Milvus 服务地址
    MILVUS_URI: str = ""
    EMBEDDING_BASE_URL: str = "http://localhost:8002/v1"
    EMBEDDING_MODEL: str = "bge-large-zh"

    # 内部服务调用：Celery Worker 经此后端接口做 RAG 检索
    # （milvus-lite 为单进程独占锁，Worker 与后端不能同时直接打开向量库）
    INTERNAL_API_BASE: str = "http://127.0.0.1:8000"
    INTERNAL_TOKEN: str = "contract-internal-token"


settings = Settings()
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
