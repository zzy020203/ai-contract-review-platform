"""初始化数据库：建表 + 预置角色与管理员账号 + 预置审查规则。用法：python -m app.db_init"""
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.domain import Role, Rule, User, UserRole  # noqa: F401 — 确保模型已注册

# 预置角色与权限码（技术设计文档第 5 节接口权限）
ROLES = [
    ("legal_staff", "法务专员", "contract:upload,review:start,review:view,review:export,dashboard:view"),
    ("legal_lead", "法务主管", "contract:upload,review:start,review:view,review:audit,review:export,rule:manage,knowledge:manage,knowledge:view,dashboard:view,audit:view"),
    ("admin", "系统管理员", "contract:upload,review:start,review:view,review:audit,review:export,rule:manage,knowledge:manage,knowledge:view,dashboard:view,audit:view,system:manage"),
]


def init() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        for code, name, perms in ROLES:
            role = db.query(Role).filter_by(code=code).first()
            if role is None:
                db.add(Role(code=code, name=name, permission_codes=perms))
            else:  # 权限码随版本升级同步（幂等）
                role.permission_codes = perms
        db.commit()

        if db.query(User).filter_by(username="admin").first() is None:
            admin = User(username="admin", password_hash=hash_password("admin123"), real_name="系统管理员")
            db.add(admin)
            db.flush()
            for role in db.query(Role).all():
                db.add(UserRole(user_id=admin.id, role_id=role.id))

        # 预置演示账号：法务专员 / 法务主管
        for uname, role_code, real_name in [("staff", "legal_staff", "法务专员"), ("lead", "legal_lead", "法务主管")]:
            if db.query(User).filter_by(username=uname).first() is None:
                u = User(username=uname, password_hash=hash_password("123456"), real_name=real_name)
                db.add(u)
                db.flush()
                role = db.query(Role).filter_by(code=role_code).first()
                db.add(UserRole(user_id=u.id, role_id=role.id))

        db.commit()
        print("数据库初始化完成：t_user/t_role 预置账号 admin/admin123、staff/123456、lead/123456")

        _seed_rules(db)
    finally:
        db.close()


# 预置审查规则（法务合规口径，向量化后供 RAG 检索注入提示词）
SEED_RULES = [
    ("R-001", "违约金比例审查", "违约责任",
     "违约金约定比例过高（如日千分之一以上，或累计上限超过合同总额30%）存在被法院/仲裁机构调减的风险；应审查违约金计算基数、比例与累计上限是否合理。"),
    ("R-002", "付款条款完整性", "价格与付款",
     "付款条款应明确付款节点、比例、付款条件（如发票开具、验收合格）及逾期付款责任；仅约定预付款或付款条件模糊的，存在回款风险。"),
    ("R-003", "知识产权归属", "知识产权",
     "委托开发/定制开发场景中，开发成果知识产权归属必须明确约定；未约定或约定不明时，依法归属于受托方（开发方），对委托方不利。"),
    ("R-004", "验收条款审查", "验收",
     "验收条款应明确验收标准、验收期限与异议方式；警惕『逾期未提出异议视为验收通过』类单方推定条款，应评估验收周期是否合理。"),
    ("R-005", "保密条款审查", "保密",
     "保密条款应明确保密信息范围、保密期限与违约责任；保密期限建议覆盖合同终止后2至5年，过短或无期限约定存在泄密风险。"),
    ("R-006", "争议解决条款", "争议解决",
     "争议解决方式应明确且唯一（诉讼或仲裁二选一），『或裁或诉』条款无效；管辖法院/仲裁机构的约定应评估对我方是否便利。"),
    ("R-007", "合同期限与解除", "期限与终止",
     "应明确合同期限、解除条件（约定解除情形）与解除后果（费用结算、资料返还、已交付成果处理）。"),
    ("R-008", "签约主体审查", "当事人信息",
     "应核对签约主体名称、统一社会信用代码与签约代表授权文件；主体信息缺失或与实际不一致存在合同效力风险。"),
]


def _seed_rules(db) -> None:
    """预置规则并尝试向量化（模型未就绪时保持 pending，可通过规则编辑接口触发重嵌入）。"""
    for code, name, group, content in SEED_RULES:
        if db.query(Rule).filter_by(code=code).first() is None:
            db.add(Rule(code=code, name=name, group_name=group, content=content))
    db.commit()

    try:
        from app.services import rag
        for rule in db.query(Rule).filter_by(vector_status="pending").all():
            rag.index_rule(rule.id, rule.code, rule.name, rule.content, rule.version)
            rule.vector_status = "done"
        db.commit()
        print("预置审查规则已向量化入库（Milvus collection=rule）")
    except Exception as exc:
        print(f"规则向量化跳过（可后续通过 /api/rule 编辑触发）：{exc}")


if __name__ == "__main__":
    init()
