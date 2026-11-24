"""审查规则管理（版本化）：CRUD + 启停 + 向量化入库。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
from app.models.domain import AuditLog, Rule, User
from app.services import rag

router = APIRouter(prefix="/rule", tags=["规则管理"])


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


def _to_out(r: Rule) -> dict:
    return {
        "id": r.id, "code": r.code, "name": r.name, "group_name": r.group_name,
        "version": r.version, "status": r.status, "content": r.content,
        "vector_status": r.vector_status, "create_time": r.create_time,
    }


class RuleIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    group_name: str = ""
    content: str = Field(min_length=1)
    status: int = 1


class RuleUpdate(BaseModel):
    name: str | None = None
    group_name: str | None = None
    content: str | None = None
    status: int | None = None


def _vectorize(rule: Rule) -> None:
    """同步向量化（本地 ONNX 推理，毫秒~秒级）；失败仅标记状态不阻断保存。"""
    try:
        rag.index_rule(rule.id, rule.code, rule.name, rule.content, rule.version)
        rule.vector_status = "done"
    except Exception as exc:
        rule.vector_status = f"failed:{exc}"[:200]


@router.get("")
def list_rules(db: Session = Depends(get_db), user: User = Depends(require_perm("rule:manage"))):
    rules = db.scalars(select(Rule).order_by(Rule.id)).all()
    return ok([_to_out(r) for r in rules])


@router.post("")
def create_rule(body: RuleIn, db: Session = Depends(get_db),
                user: User = Depends(require_perm("rule:manage"))):
    if db.scalar(select(Rule).where(Rule.code == body.code)) is not None:
        raise HTTPException(400, f"规则编号 {body.code} 已存在")
    rule = Rule(code=body.code, name=body.name, group_name=body.group_name,
                content=body.content, status=body.status)
    db.add(rule)
    db.flush()
    _vectorize(rule)
    db.add(AuditLog(operator_id=user.id, action="rule:create", target=rule.code))
    db.commit()
    return ok(_to_out(rule))


@router.put("/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate, db: Session = Depends(get_db),
                user: User = Depends(require_perm("rule:manage"))):
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(404, "规则不存在")

    content_changed = body.content is not None and body.content != rule.content
    if body.name is not None:
        rule.name = body.name
    if body.group_name is not None:
        rule.group_name = body.group_name
    if body.status is not None:
        rule.status = body.status
    if content_changed:
        rule.content = body.content
        rule.version += 1  # 版本化：内容变更即升版，新向量进新 partition
        _vectorize(rule)
    elif body.name is not None:  # 名称变化影响向量文本，重嵌入同版本
        _vectorize(rule)

    db.add(AuditLog(operator_id=user.id, action="rule:update", target=rule.code,
                    detail=f"version={rule.version}, status={rule.status}"))
    db.commit()
    return ok(_to_out(rule))


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_perm("rule:manage"))):
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(404, "规则不存在")
    rag.delete_rule_vectors(rule.id)
    db.add(AuditLog(operator_id=user.id, action="rule:delete", target=rule.code))
    db.delete(rule)
    db.commit()
    return ok({"deleted": rule_id})
