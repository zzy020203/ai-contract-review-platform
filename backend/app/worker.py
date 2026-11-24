"""Celery 应用与审查任务执行器（含人工复核断点续跑）。"""
from contextlib import contextmanager
from datetime import datetime

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "contract_review",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.conf.update(task_track_started=True, worker_pool="solo")

_checkpoint_ready = False


@contextmanager
def _open_checkpointer():
    """按 DATABASE_URL 选择 checkpoint 存储：PostgreSQL → PostgresSaver，其余 → SqliteSaver。"""
    global _checkpoint_ready
    if settings.DATABASE_URL.startswith("postgresql"):
        from langgraph.checkpoint.postgres import PostgresSaver

        # SQLAlchemy 的 +psycopg2 方言后缀需去掉，libpq 只认 postgresql://
        conninfo = settings.DATABASE_URL.split("://", 1)[1]
        with PostgresSaver.from_conn_string(f"postgresql://{conninfo}") as saver:
            if not _checkpoint_ready:
                saver.setup()  # 幂等建表
                _checkpoint_ready = True
            yield saver
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver

        with SqliteSaver.from_conn_string(str(settings.STORAGE_DIR / "checkpoints.db")) as saver:
            yield saver


def _config(task) -> dict:
    return {"configurable": {"thread_id": task.thread_id}}


def _persist_results(db, task, contract, result: dict) -> None:
    """条款 / 风险 / 建议落库（幂等：按任务先删后插）。

    risk 行序与 state 中 risks + compliance_issues 合并序一致，
    suggestion.item_index 即该合并序下标（与 workflow.suggest 约定）。
    """
    from app.models.domain import Clause, RiskItem, Suggestion

    # 条款（重跑先清空）
    db.query(Clause).filter(Clause.contract_id == contract.id).delete()
    clause_id_map: dict[str, int] = {}
    for c in result.get("clauses", []):
        row = Clause(
            contract_id=contract.id, clause_no=c["clause_no"],
            title=c.get("title", ""), clause_type=c.get("clause_type", ""),
            content=c["content"], confidence=c.get("confidence", 1.0),
        )
        db.add(row)
        db.flush()
        clause_id_map[c["clause_no"]] = row.id

    # 风险项（先清旧建议再清旧风险，避免悬挂引用）
    old_risk_ids = [r[0] for r in db.query(RiskItem.id).filter(RiskItem.task_id == task.id).all()]
    if old_risk_ids:
        db.query(Suggestion).filter(Suggestion.risk_id.in_(old_risk_ids)).delete(synchronize_session=False)
    db.query(RiskItem).filter(RiskItem.task_id == task.id).delete()

    risk_rows: list[RiskItem] = []
    for it in result.get("risks", []) + result.get("compliance_issues", []):
        row = RiskItem(
            task_id=task.id,
            clause_id=clause_id_map.get(it.get("clause_no") or ""),
            level=it["level"], risk_type=it["risk_type"],
            description=it["description"], evidence=it.get("evidence", ""),
            confidence=it.get("confidence", 1.0),
        )
        db.add(row)
        db.flush()
        risk_rows.append(row)

    # 建议
    for s in result.get("suggestions", []):
        idx = s.get("item_index", -1)
        if 0 <= idx < len(risk_rows):
            db.add(Suggestion(
                risk_id=risk_rows[idx].id, suggest_text=s["suggest_text"],
                reason=s.get("reason", ""), reference=s.get("reference", ""),
            ))


def _persist_report(db, task, result: dict) -> None:
    from app.models.domain import ReviewReport
    db.add(ReviewReport(task_id=task.id, report_path=result.get("report_path", "")))


@celery_app.task(name="run_review_workflow")
def run_review_workflow(task_id: int) -> None:
    """执行 LangGraph 审查工作流并回写业务库（Worker 进程内运行）。

    高风险任务在 human_review 前挂起（interrupt），本函数检测到中断后
    落库中间结果并置任务为 pending_audit，等待 /feedback 触发 resume_review_workflow。
    """
    from app.agents.workflow import build_graph
    from app.core.database import SessionLocal
    from app.models.domain import Contract, ReviewTask
    from app.services import events

    db = SessionLocal()
    try:
        task = db.get(ReviewTask, task_id)
        contract = db.get(Contract, task.contract_id)

        task.status = "reviewing"
        task.start_time = datetime.now()
        db.commit()

        with _open_checkpointer() as saver:
            graph = build_graph(checkpointer=saver)
            result = graph.invoke(
                {
                    "task_id": task.id,
                    "contract_id": contract.id,
                    "file_path": contract.file_path,
                    "file_type": contract.file_type,
                },
                config=_config(task),
            )
            suspended = bool(graph.get_state(_config(task)).next)

        _persist_results(db, task, contract, result)

        if suspended:  # 高风险挂起，等待人工复核
            task.status = "pending_audit"
            task.current_node = "human_review"
            db.commit()
            events.publish(task_id, {
                "node": "workflow", "status": "pending_audit",
                "message": "存在高风险项，任务已挂起，等待人工复核",
            })
            return

        _persist_report(db, task, result)
        task.status = "done"
        task.current_node = "report"
        task.finish_time = datetime.now()
        db.commit()
        events.publish(task_id, {"node": "workflow", "status": "done", "message": "审查完成"})
    except Exception as exc:
        task = db.get(ReviewTask, task_id)
        task.status = "failed"
        task.error_msg = str(exc)
        task.finish_time = datetime.now()
        from app.models.domain import AuditLog
        db.add(AuditLog(operator_id=None, action="workflow:failed",
                        target=f"task:{task_id}", detail=str(exc)[:500]))
        db.commit()
        events.publish(task_id, {"node": "workflow", "status": "failed", "message": str(exc)})
        raise
    finally:
        db.close()


@celery_app.task(name="resume_review_workflow")
def resume_review_workflow(task_id: int, feedback: dict) -> None:
    """人工复核提交后续跑：update_state 写入处置结果，从 checkpoint 恢复至报告生成。"""
    from app.agents.workflow import build_graph
    from app.core.database import SessionLocal
    from app.models.domain import Contract, ReviewTask
    from app.services import events

    db = SessionLocal()
    try:
        task = db.get(ReviewTask, task_id)
        contract = db.get(Contract, task.contract_id)

        with _open_checkpointer() as saver:
            graph = build_graph(checkpointer=saver)
            graph.update_state(_config(task), {"human_feedback": feedback})
            result = graph.invoke(None, config=_config(task))

        _persist_report(db, task, result)
        task.status = "done"
        task.current_node = "report"
        task.finish_time = datetime.now()
        db.commit()
        events.publish(task_id, {"node": "workflow", "status": "done", "message": "复核完成，报告已生成"})
    except Exception as exc:
        task = db.get(ReviewTask, task_id)
        task.status = "failed"
        task.error_msg = f"复核续跑失败：{exc}"
        task.finish_time = datetime.now()
        from app.models.domain import AuditLog
        db.add(AuditLog(operator_id=None, action="workflow:failed",
                        target=f"task:{task_id}", detail=str(exc)[:500]))
        db.commit()
        events.publish(task_id, {"node": "workflow", "status": "failed", "message": str(exc)})
        raise
    finally:
        db.close()
