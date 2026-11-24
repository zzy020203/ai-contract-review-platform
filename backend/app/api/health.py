"""健康检查：数据库 / Redis 组件探测，供 Nginx 与容器 healthcheck 使用。"""
import redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db

router = APIRouter(tags=["运维"])


def _check_redis() -> bool:
    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        return bool(client.ping())
    except Exception:
        return False


@router.get("/healthz", summary="健康检查")
def healthz(db: Session = Depends(get_db)):
    components = {"database": "up", "redis": "down"}
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        components["database"] = "down"
    components["redis"] = "up" if _check_redis() else "down"

    # 数据库为关键依赖；Redis 不可用仅降级（进度推送/异步队列受影响，主流程可降级运行）
    status = "down" if components["database"] == "down" else (
        "up" if components["redis"] == "up" else "degraded"
    )
    return {"code": 0, "message": "ok", "data": {"status": status, "components": components}}
