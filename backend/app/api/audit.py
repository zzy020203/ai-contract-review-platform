"""审计日志查询：关键操作留痕的统一检索入口（技术设计文档 3.4.1 / 7）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
from app.models.domain import AuditLog, User

router = APIRouter(prefix="/audit", tags=["审计"])


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


def _parse_dt(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, f"日期格式错误：{value}（应为 YYYY-MM-DD 或 ISO 时间）") from exc
    if end_of_day and len(value) == 10:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


@router.get("/logs")
def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = None,
    operator: str | None = None,
    keyword: str | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_perm("audit:view")),
):
    """分页查询审计日志（按动作/操作人/关键字/时间范围筛选）。"""
    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if operator:
        conditions.append(or_(User.username.like(f"%{operator}%"), User.real_name.like(f"%{operator}%")))
    if keyword:
        conditions.append(or_(AuditLog.target.like(f"%{keyword}%"), AuditLog.detail.like(f"%{keyword}%")))
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end, end_of_day=True)
    if start_dt:
        conditions.append(AuditLog.create_time >= start_dt)
    if end_dt:
        conditions.append(AuditLog.create_time <= end_dt)

    base = select(AuditLog.id).outerjoin(User, AuditLog.operator_id == User.id).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    rows = db.execute(
        select(AuditLog, User.username, User.real_name)
        .outerjoin(User, AuditLog.operator_id == User.id)
        .where(*conditions)
        .order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [
        {
            "id": log.id,
            "operator_id": log.operator_id,
            "operator": username or ("系统" if log.operator_id is None else f"用户{log.operator_id}"),
            "real_name": real_name or "",
            "action": log.action,
            "target": log.target,
            "detail": log.detail,
            "create_time": log.create_time,
        }
        for log, username, real_name in rows
    ]

    # 审计日志被查看本身也是关键操作，留痕
    db.add(AuditLog(operator_id=user.id, action="audit:query",
                    detail=f"page={page}, action={action or '-'}, operator={operator or '-'}"))
    db.commit()
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/actions")
def list_actions(db: Session = Depends(get_db), user: User = Depends(require_perm("audit:view"))):
    """全部审计动作枚举（前端筛选下拉）。"""
    actions = db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)).all()
    return ok(list(actions))
