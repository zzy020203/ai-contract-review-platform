"""审查任务编排：启动 / 状态 / SSE 进度 / 报告 / 人工复核闭环。"""
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.database import get_db
from app.core.deps import get_current_user, require_perm
from app.models.domain import (AuditLog, Clause, ReviewReport, ReviewTask,
                               RevisionVersion, RiskItem, Suggestion, User)
from app.schemas.review import TaskOut
from app.services import events

router = APIRouter(prefix="/review", tags=["任务编排"])


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


def _to_out(t: ReviewTask) -> dict:
    return TaskOut(
        id=t.id, contract_id=t.contract_id,
        contract_name=t.contract.name if t.contract else "",
        thread_id=t.thread_id, status=t.status,
        current_node=t.current_node, error_msg=t.error_msg,
        create_time=t.create_time, finish_time=t.finish_time,
    ).model_dump()


@router.post("/{task_id}/start")
def start(task_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("review:start"))):
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    if task.status not in ("pending", "failed"):
        raise HTTPException(400, f"任务状态为 {task.status}，不可重复启动")

    from app.worker import run_review_workflow
    run_review_workflow.delay(task_id)

    task.status = "queued"
    db.add(AuditLog(operator_id=user.id, action="review:start", target=f"task:{task_id}"))
    db.commit()
    return ok({"task_id": task_id, "status": "queued"})


@router.get("/list")
def list_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tasks = db.scalars(select(ReviewTask).order_by(ReviewTask.id.desc())).all()
    return ok([_to_out(t) for t in tasks])


@router.get("/{task_id}/status")
def status(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return ok(_to_out(task))


@router.get("/{task_id}/events")
def sse_events(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """SSE 订阅审查进度（Redis pub/sub 转发）。"""
    if db.get(ReviewTask, task_id) is None:
        raise HTTPException(404, "任务不存在")

    def stream():
        pubsub = events.subscribe(task_id)
        try:
            # 先推送一次当前状态，避免错过早期事件
            yield {"event": "progress", "data": json.dumps({"node": "connected", "status": "ok"}, ensure_ascii=False)}
            while True:
                msg = pubsub.get_message(timeout=15)
                if msg and msg["type"] == "message":
                    yield {"event": "progress", "data": msg["data"]}
                else:
                    yield {"event": "ping", "data": ""}
        finally:
            pubsub.close()

    return EventSourceResponse(stream())


@router.get("/{task_id}/report")
def report(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rpt = db.scalar(select(ReviewReport).where(ReviewReport.task_id == task_id).order_by(ReviewReport.id.desc()))
    if rpt is None or not rpt.report_path:
        raise HTTPException(404, "报告尚未生成")
    return FileResponse(rpt.report_path, filename=f"report_task_{task_id}.txt")


@router.get("/{task_id}/report/export")
def export_report(task_id: int, format: str = Query("docx", pattern="^(docx|txt)$"),
                  db: Session = Depends(get_db), user: User = Depends(require_perm("review:export"))):
    """导出审查报告（Word / 纯文本），并记录导出次数与审计。"""
    rpt = db.scalar(select(ReviewReport).where(ReviewReport.task_id == task_id).order_by(ReviewReport.id.desc()))
    if rpt is None or not rpt.report_path:
        raise HTTPException(404, "报告尚未生成")
    src = Path(rpt.report_path)
    if not src.exists():
        raise HTTPException(404, "报告文件不存在")

    if format == "docx":
        out = src.with_suffix(".docx")
        if not out.exists():
            _txt_to_docx(src, out)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        out = src
        media = "text/plain; charset=utf-8"

    rpt.export_count = (rpt.export_count or 0) + 1
    db.add(AuditLog(operator_id=user.id, action="report:export",
                    target=f"task:{task_id}", detail=f"format={format}"))
    db.commit()
    return FileResponse(out, filename=f"合同审查报告_task{task_id}.{format}", media_type=media)


def _txt_to_docx(src: Path, out: Path) -> None:
    """将纯文本报告转为 Word 文档（标题/正文分级）。"""
    from docx import Document

    doc = Document()
    lines = src.read_text(encoding="utf-8").splitlines()
    for line in lines:
        text = line.strip()
        if not text or set(text) == {"="} or set(text) == {"-"}:
            continue
        if text == "企业智能合同审查报告":
            doc.add_heading(text, level=1)
        elif text in ("一、风险明细", "二、条款清单"):
            doc.add_heading(text, level=2)
        else:
            doc.add_paragraph(text)
    doc.save(str(out))


# ---------- 人工复核 ----------

@router.get("/queue")
def review_queue(db: Session = Depends(get_db), user: User = Depends(require_perm("review:audit"))):
    """人工复核队列：pending_audit 任务 + 风险统计。"""
    tasks = db.scalars(
        select(ReviewTask).where(ReviewTask.status == "pending_audit")
        .order_by(ReviewTask.id.desc())
    ).all()
    out = []
    for t in tasks:
        risks = db.scalars(select(RiskItem).where(RiskItem.task_id == t.id)).all()
        out.append({
            **_to_out(t),
            "risk_total": len(risks),
            "high_count": sum(1 for r in risks if r.level == "high"),
            "medium_count": sum(1 for r in risks if r.level == "medium"),
        })
    return ok(out)


@router.get("/{task_id}/detail")
def task_detail(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """审查详情：条款树 + 风险清单 + 建议（复核工作台数据源）。"""
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")

    clauses = db.scalars(
        select(Clause).where(Clause.contract_id == task.contract_id).order_by(Clause.id)
    ).all()
    risks = db.scalars(select(RiskItem).where(RiskItem.task_id == task_id).order_by(RiskItem.id)).all()
    suggestions = {
        s.risk_id: s for s in db.scalars(
            select(Suggestion).join(RiskItem, Suggestion.risk_id == RiskItem.id)
            .where(RiskItem.task_id == task_id)
        ).all()
    }

    return ok({
        "task": _to_out(task),
        "clauses": [
            {"id": c.id, "clause_no": c.clause_no, "title": c.title,
             "clause_type": c.clause_type, "content": c.content, "confidence": c.confidence}
            for c in clauses
        ],
        "risks": [
            {
                "id": r.id, "clause_id": r.clause_id, "level": r.level,
                "risk_type": r.risk_type, "description": r.description,
                "evidence": r.evidence, "confidence": r.confidence,
                "handle_status": r.handle_status,
                "suggestion": (
                    {"id": s.id, "suggest_text": s.suggest_text,
                     "reason": s.reason, "reference": s.reference}
                    if (s := suggestions.get(r.id)) else None
                ),
            }
            for r in risks
        ],
    })


class FeedbackAction(BaseModel):
    suggestion_id: int | None = None
    risk_id: int | None = None
    action: str  # accept / reject / edit
    edited_text: str | None = None
    comment: str | None = None


class FeedbackIn(BaseModel):
    actions: list[FeedbackAction]


@router.post("/{task_id}/feedback")
def feedback(task_id: int, body: FeedbackIn, db: Session = Depends(get_db),
             user: User = Depends(require_perm("review:audit"))):
    """提交复核处置（接受/拒绝/编辑），写修订版本（append-only）并触发工作流续跑。"""
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    if task.status != "pending_audit":
        raise HTTPException(400, f"任务状态为 {task.status}，不在待复核状态")

    done_actions = []
    for a in body.actions:
        if a.action not in ("accept", "reject", "edit"):
            raise HTTPException(400, f"非法处置动作：{a.action}")
        if a.action == "edit" and not (a.edited_text or "").strip():
            raise HTTPException(400, "edit 动作必须提供 edited_text")

        risk = db.get(RiskItem, a.risk_id) if a.risk_id else None
        suggestion = db.get(Suggestion, a.suggestion_id) if a.suggestion_id else None
        if risk is None and suggestion is not None:
            risk = db.get(RiskItem, suggestion.risk_id)
        if risk is None or risk.task_id != task_id:
            raise HTTPException(400, f"风险项不存在或不属于本任务：risk_id={a.risk_id}")

        risk.handle_status = {"accept": "accepted", "reject": "rejected", "edit": "edited"}[a.action]

        # 修订版本 append-only：接受→建议文本；编辑→编辑文本；拒绝→维持原文
        if risk.clause_id is not None:
            clause = db.get(Clause, risk.clause_id)
            before = clause.content
            after = before
            if a.action == "accept" and suggestion is not None:
                after = suggestion.suggest_text
            elif a.action == "edit":
                after = a.edited_text.strip()
            next_ver = (db.query(RevisionVersion)
                        .filter(RevisionVersion.clause_id == risk.clause_id)
                        .count()) + 1
            db.add(RevisionVersion(
                clause_id=risk.clause_id, version=next_ver,
                before_text=before, after_text=after,
                action=a.action, operator_id=user.id,
            ))
            if a.action in ("accept", "edit"):  # AI 建议经人工确认后生效
                clause.content = after

        done_actions.append({
            "risk_id": risk.id, "suggestion_id": a.suggestion_id,
            "action": a.action, "comment": a.comment,
        })

    db.add(AuditLog(operator_id=user.id, action="review:feedback",
                    target=f"task:{task_id}", detail=json.dumps(done_actions, ensure_ascii=False)))
    task.status = "reporting"
    db.commit()

    from app.worker import resume_review_workflow
    resume_review_workflow.delay(task_id, {
        "actions": done_actions,
        "operator": user.username,
        "time": datetime.now().isoformat(timespec="seconds"),
    })
    return ok({"task_id": task_id, "status": "reporting", "handled": len(done_actions)})
