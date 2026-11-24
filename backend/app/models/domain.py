"""核心业务数据模型（对应技术设计文档第 4 节）。"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------- RBAC ----------

class User(Base):
    __tablename__ = "t_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    real_name: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[int] = mapped_column(Integer, default=1)  # 1 启用 0 禁用
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    roles: Mapped[list["Role"]] = relationship(secondary="t_user_role", back_populates="users")


class Role(Base):
    __tablename__ = "t_role"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)  # legal_staff / legal_lead / admin
    name: Mapped[str] = mapped_column(String(64))
    permission_codes: Mapped[str] = mapped_column(Text, default="")  # 逗号分隔权限码

    users: Mapped[list[User]] = relationship(secondary="t_user_role", back_populates="roles")


class UserRole(Base):
    __tablename__ = "t_user_role"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("t_user.id"))
    role_id: Mapped[int] = mapped_column(ForeignKey("t_role.id"))


# ---------- 合同与审查任务 ----------

class Contract(Base):
    __tablename__ = "t_contract"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    file_type: Mapped[str] = mapped_column(String(16))  # pdf / docx / txt
    status: Mapped[int] = mapped_column(Integer, default=1)  # 1 正常 0 软删除
    uploader_id: Mapped[int] = mapped_column(ForeignKey("t_user.id"))
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ReviewTask(Base):
    __tablename__ = "t_review_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("t_contract.id"))
    thread_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # LangGraph checkpoint 关联
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending / parsing / extracting / reviewing / pending_audit / reporting / done / failed
    current_node: Mapped[str] = mapped_column(String(64), default="")
    error_msg: Mapped[str] = mapped_column(Text, default="")
    creator_id: Mapped[int] = mapped_column(ForeignKey("t_user.id"))
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    contract: Mapped[Contract] = relationship()


class Clause(Base):
    __tablename__ = "t_clause"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("t_contract.id"), index=True)
    clause_no: Mapped[str] = mapped_column(String(32))
    clause_type: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class RiskItem(Base):
    __tablename__ = "t_risk_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("t_review_task.id"), index=True)
    clause_id: Mapped[int | None] = mapped_column(ForeignKey("t_clause.id"), nullable=True)
    level: Mapped[str] = mapped_column(String(16))  # high / medium / low
    risk_type: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text, default="")  # 依据来源（规则编号/模板出处）
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    handle_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/accepted/rejected/edited


class Suggestion(Base):
    __tablename__ = "t_suggestion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    risk_id: Mapped[int] = mapped_column(ForeignKey("t_risk_item.id"), index=True)
    suggest_text: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default="")
    reference: Mapped[str] = mapped_column(Text, default="")


class RevisionVersion(Base):
    """修订版本（append-only，历史版本只增不改）。"""

    __tablename__ = "t_revision_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clause_id: Mapped[int] = mapped_column(ForeignKey("t_clause.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    before_text: Mapped[str] = mapped_column(Text)
    after_text: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(16))  # accept / reject / edit
    operator_id: Mapped[int] = mapped_column(ForeignKey("t_user.id"))
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ReviewReport(Base):
    __tablename__ = "t_review_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("t_review_task.id"), index=True)
    template_ver: Mapped[str] = mapped_column(String(32), default="v1")
    report_path: Mapped[str] = mapped_column(String(512), default="")
    export_count: Mapped[int] = mapped_column(Integer, default=0)
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------- 规则与知识库 ----------

class Rule(Base):
    __tablename__ = "t_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    group_name: Mapped[str] = mapped_column(String(64), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[int] = mapped_column(Integer, default=1)  # 1 启用 0 停用
    content: Mapped[str] = mapped_column(Text)
    vector_status: Mapped[str] = mapped_column(String(16), default="pending")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class KnowledgeDoc(Base):
    __tablename__ = "t_knowledge_doc"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lib_type: Mapped[str] = mapped_column(String(32))  # rule / history / template
    title: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    vector_status: Mapped[str] = mapped_column(String(16), default="pending")
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("t_user.id"), nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AuditLog(Base):
    __tablename__ = "t_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("t_user.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
