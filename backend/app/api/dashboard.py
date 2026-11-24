"""数据看板：审查量 / 风险分布 / 平均耗时 / 复核处置统计。"""
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
from app.models.domain import ReviewTask, RevisionVersion, RiskItem, User

router = APIRouter(prefix="/dashboard", tags=["数据看板"])

STATUS_CN = {
    "pending": "待启动", "queued": "排队中", "parsing": "解析中", "extracting": "条款提取中",
    "reviewing": "风险识别中", "pending_audit": "待复核", "reporting": "报告生成中",
    "done": "已完成", "failed": "失败",
}
HANDLE_CN = {"pending": "待处置", "accepted": "已采纳", "rejected": "已拒绝", "edited": "已编辑"}
LEVEL_CN = {"high": "高", "medium": "中", "low": "低"}


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


@router.get("/overview")
def overview(days: int = Query(14, ge=1, le=90), db: Session = Depends(get_db),
             user: User = Depends(require_perm("dashboard:view"))):
    """看板聚合数据（趋势/风险/处置/耗时），days 控制趋势区间。"""
    tasks = db.scalars(select(ReviewTask).order_by(ReviewTask.id)).all()
    risk_rows = db.execute(select(RiskItem.level, RiskItem.risk_type, RiskItem.handle_status)).all()
    revision_count = db.scalar(select(func.count(RevisionVersion.id))) or 0

    # ---------- 概要 ----------
    durations = [
        (t.finish_time - t.start_time).total_seconds() / 60
        for t in tasks if t.start_time and t.finish_time
    ]
    status_counts = Counter(t.status for t in tasks)
    level_counts = Counter(r.level for r in risk_rows)
    handle_counts = Counter(r.handle_status for r in risk_rows)

    handled = handle_counts["accepted"] + handle_counts["rejected"] + handle_counts["edited"]
    accepted = handle_counts["accepted"] + handle_counts["edited"]
    summary = {
        "total_tasks": len(tasks),
        "done_tasks": status_counts["done"],
        "pending_audit": status_counts["pending_audit"],
        "failed_tasks": status_counts["failed"],
        "running_tasks": sum(status_counts[s] for s in ("queued", "parsing", "extracting", "reviewing", "reporting")),
        "total_risks": len(risk_rows),
        "high_risks": level_counts["high"],
        "medium_risks": level_counts["medium"],
        "low_risks": level_counts["low"],
        "avg_duration_minutes": round(sum(durations) / len(durations), 1) if durations else 0,
        "accept_rate": round(accepted / handled, 3) if handled else 0,
        "revision_count": revision_count,
    }

    # ---------- 趋势（按天） ----------
    today = datetime.now().date()
    start_date = today - timedelta(days=days - 1)
    trend = {
        (start_date + timedelta(days=i)).isoformat(): {"created": 0, "completed": 0, "dur": []}
        for i in range(days)
    }
    for t in tasks:
        if t.create_time and t.create_time.date() >= start_date:
            bucket = trend.get(t.create_time.date().isoformat())
            if bucket:
                bucket["created"] += 1
        if t.finish_time and t.finish_time.date() >= start_date:
            bucket = trend.get(t.finish_time.date().isoformat())
            if bucket:
                bucket["completed"] += 1
                if t.start_time:
                    bucket["dur"].append((t.finish_time - t.start_time).total_seconds() / 60)

    trend_out = [
        {
            "date": d,
            "created": v["created"],
            "completed": v["completed"],
            "avg_minutes": round(sum(v["dur"]) / len(v["dur"]), 1) if v["dur"] else 0,
        }
        for d, v in trend.items()
    ]

    # ---------- 风险分布 ----------
    risk_levels = [
        {"name": LEVEL_CN[lv], "key": lv, "value": level_counts[lv]} for lv in ("high", "medium", "low")
    ]
    type_counts = Counter(r.risk_type or "未分类" for r in risk_rows)
    risk_types = [{"name": k, "value": v} for k, v in type_counts.most_common(10)]

    return ok({
        "period_days": days,
        "summary": summary,
        "trend": trend_out,
        "risk_levels": risk_levels,
        "risk_types": risk_types,
        "status_distribution": [
            {"name": STATUS_CN.get(k, k), "value": v} for k, v in status_counts.items()
        ],
        "handle_distribution": [
            {"name": HANDLE_CN.get(k, k), "value": handle_counts[k]}
            for k in ("pending", "accepted", "rejected", "edited")
        ],
    })
