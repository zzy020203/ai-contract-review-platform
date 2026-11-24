"""系统监控：组件健康、任务队列与失败率、Prometheus 指标输出。"""
from datetime import datetime, timedelta

import redis
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import require_perm
from app.models.domain import Contract, ReviewTask, RiskItem, User

router = APIRouter(prefix="/monitor", tags=["系统监控"])

STATUS_KEYS = ("pending", "queued", "parsing", "extracting", "reviewing",
               "pending_audit", "reporting", "done", "failed")


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


def _check_redis() -> tuple[bool, int]:
    """Redis 连通性 + Celery 默认队列长度。"""
    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return True, int(client.llen("celery"))
    except Exception:
        return False, 0


def _check_celery() -> int:
    """在线 Celery worker 数（ping 超时 1 秒）。"""
    try:
        from app.worker import celery_app
        replies = celery_app.control.ping(timeout=1.0) or []
        return len(replies)
    except Exception:
        return 0


def _check_milvus() -> bool:
    try:
        from app.services import rag
        rag.get_client().list_collections()
        return True
    except Exception:
        return False


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(require_perm("system:manage"))):
    """监控总览：服务健康、队列积压、任务状态与 24h 失败率。"""
    services = {"database": "up", "redis": "down", "celery": "down", "milvus": "down",
                "llm": "configured" if (settings.LLM_BASE_URL and settings.LLM_API_KEY) else "unconfigured"}

    try:
        db.execute(text("SELECT 1"))
    except Exception:
        services["database"] = "down"

    redis_up, queue_length = _check_redis()
    services["redis"] = "up" if redis_up else "down"
    workers = _check_celery()
    services["celery"] = "up" if workers else "down"
    services["milvus"] = "up" if _check_milvus() else "down"

    status_counts = dict(
        db.execute(select(ReviewTask.status, func.count(ReviewTask.id))
                   .group_by(ReviewTask.status)).all()
    )
    since = datetime.now() - timedelta(hours=24)
    done_24h = db.scalar(
        select(func.count(ReviewTask.id))
        .where(ReviewTask.status == "done", ReviewTask.finish_time >= since)
    ) or 0
    failed_24h = db.scalar(
        select(func.count(ReviewTask.id))
        .where(ReviewTask.status == "failed", ReviewTask.finish_time >= since)
    ) or 0
    denominator = done_24h + failed_24h
    failure_rate = round(failed_24h / denominator, 3) if denominator else 0

    failures = db.execute(
        select(ReviewTask.id, ReviewTask.error_msg, ReviewTask.finish_time, Contract.name)
        .join(Contract, ReviewTask.contract_id == Contract.id)
        .where(ReviewTask.status == "failed")
        .order_by(ReviewTask.id.desc()).limit(10)
    ).all()

    return ok({
        "services": services,
        "workers": workers,
        "queue_length": queue_length,
        "tasks": {
            "status_counts": status_counts,
            "running": sum(status_counts.get(s, 0) for s in ("queued", "parsing", "extracting", "reviewing", "reporting")),
            "pending_audit": status_counts.get("pending_audit", 0),
            "done_24h": done_24h,
            "failed_24h": failed_24h,
            "failure_rate": failure_rate,
        },
        "recent_failures": [
            {"task_id": tid, "contract_name": name, "error_msg": err, "finish_time": fin}
            for tid, err, fin, name in failures
        ],
        "checked_at": datetime.now(),
    })


@router.get("/prometheus", response_class=PlainTextResponse)
def prometheus_metrics(db: Session = Depends(get_db)):
    """Prometheus 文本格式指标（内网采集，无需 JWT）。"""
    status_counts = dict(
        db.execute(select(ReviewTask.status, func.count(ReviewTask.id))
                   .group_by(ReviewTask.status)).all()
    )
    level_counts = dict(
        db.execute(select(RiskItem.level, func.count(RiskItem.id))
                   .group_by(RiskItem.level)).all()
    )
    redis_up, queue_length = _check_redis()
    workers = _check_celery()

    lines = [
        "# HELP contract_review_tasks_total 审查任务数（按状态）",
        "# TYPE contract_review_tasks_total gauge",
    ]
    for key in STATUS_KEYS:
        lines.append(f'contract_review_tasks_total{{status="{key}"}} {status_counts.get(key, 0)}')
    lines += [
        "# HELP contract_review_risks_total 风险项数（按等级）",
        "# TYPE contract_review_risks_total gauge",
    ]
    for lv in ("high", "medium", "low"):
        lines.append(f'contract_review_risks_total{{level="{lv}"}} {level_counts.get(lv, 0)}')
    lines += [
        "# HELP contract_review_celery_queue_length Celery 默认队列积压数",
        "# TYPE contract_review_celery_queue_length gauge",
        f"contract_review_celery_queue_length {queue_length}",
        "# HELP contract_review_celery_workers 在线 Celery worker 数",
        "# TYPE contract_review_celery_workers gauge",
        f"contract_review_celery_workers {workers}",
        "# HELP contract_review_service_up 组件存活（1=up）",
        "# TYPE contract_review_service_up gauge",
        f'contract_review_service_up{{service="redis"}} {1 if redis_up else 0}',
        f'contract_review_service_up{{service="celery"}} {1 if workers else 0}',
    ]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
