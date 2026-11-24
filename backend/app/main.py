"""FastAPI 应用入口。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (audit, auth, contract, dashboard, health, internal,
                     knowledge, monitor, review, rule)
from app.core.config import settings

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

# 开发期允许 Vite 前端跨域；生产由 Nginx 统一入口后不再需要
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(contract.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(rule.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(internal.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(monitor.router, prefix="/api")
