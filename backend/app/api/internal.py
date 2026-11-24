"""内部接口：仅供 Celery Worker 调用（共享令牌鉴权，不对外暴露）。

milvus-lite 为单进程独占锁，后端 API 已持有向量库连接，Worker 通过此接口检索，
避免两个进程同时打开 storage/milvus_lite.db 导致 DataDirLockedError。
"""
from fastapi import APIRouter, Header, HTTPException, Query

from app.core.config import settings
from app.services import rag

router = APIRouter(prefix="/internal", tags=["内部"])


@router.get("/rag/search-rules")
def search_rules(
    q: str = Query(..., min_length=1),
    top_k: int = Query(2, ge=1, le=10),
    x_internal_token: str = Header(""),
):
    if x_internal_token != settings.INTERNAL_TOKEN:
        raise HTTPException(403, "内部令牌无效")
    return {"code": 0, "message": "ok", "data": rag.search_rules(q, top_k=top_k)}
