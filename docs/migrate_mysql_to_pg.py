"""MySQL(cms_demo) → PostgreSQL(contract_review) 迁移脚本

用法：
    cd E:\\software\\project\\DocuMind\\DocuMind_API
    .venv\\Scripts\\python.exe ../../docs/migrate_mysql_to_pg.py [--force]

--force：清空 PG 现有表后重建再迁移（默认：PG 有数据则跳过）

迁移对象：DocuMind RBAC 全套 13 张表（t_ 前缀）
    主表：t_dept t_role t_permission t_menu t_post t_employee t_invitation
    关联表：t_role_dept t_role_menu t_role_permission t_employee_role
           t_employee_dept t_employee_post

策略：
  1. SQLAlchemy 分别连 MySQL + PG
  2. PG 侧 create_all 建表（直接复用 DocuMind 的 models.Base.metadata）
  3. 按外键依赖顺序从 MySQL SELECT → PG bulk_insert_mappings
  4. 重置 PG 的序列（setval 让新 ID 从 max(id)+1 开始）
  5. 逐表校验行数一致
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 把 DocuMind_API 加到 sys.path 并 chdir，才能 import models + config
BACKEND_DIR = Path(r"E:\software\project\DocuMind\DocuMind_API")
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(str(BACKEND_DIR))

from sqlalchemy import BigInteger, create_engine, text
from sqlalchemy.orm import Session

# ===== 数据库连接 =====
MYSQL_URL = "mysql+pymysql://root:123456@127.0.0.1:3306/cms_demo?charset=utf8mb4"
PG_URL = "postgresql+psycopg2://postgres:123456@127.0.0.1:5432/contract_review"

# ===== 外键依赖顺序（先主后从）=====
# relations 必须在主表之后，否则外键 FK 约束会报错
TABLE_ORDER = [
    "t_dept",
    "t_role",
    "t_permission",
    "t_menu",
    "t_post",
    "t_employee",
    "t_invitation",
    # relations —— 必须最后
    "t_role_dept",
    "t_role_menu",
    "t_role_permission",
    "t_employee_role",
    "t_employee_dept",
    "t_employee_post",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="清空 PG 现有表后重建")
    args = parser.parse_args()

    print("=" * 60)
    print("MySQL(cms_demo) → PostgreSQL(contract_review) 迁移")
    print("=" * 60)

    # —— import 模型并触发 metadata 加载 ——
    print("\n[1/6] 加载 DocuMind models...")
    import models  # noqa: F401 （models/__init__.py 会 import 所有表）
    import models.invitation  # noqa: F401 （Invitation 在 __init__.py 的 __all__ 里但没实际 import）
    from models.base import Base

    mysql_engine = create_engine(MYSQL_URL, echo=False)
    pg_engine = create_engine(PG_URL, echo=False)

    # —— 确认 MySQL 可连 & 拿到表名 ——
    print("[2/6] 探测 MySQL 源库...")
    with Session(mysql_engine) as mses:
        mysql_tables = [t for t in TABLE_ORDER]
        for t in mysql_tables:
            cnt = mses.execute(text(f'SELECT COUNT(*) FROM `{t}`')).scalar()
            print(f"    MySQL.{t}: {cnt} rows")

    # —— PG 侧建表 ——
    print("\n[3/6] PG 建表...")
    if args.force:
        print("    --force: 先 DROP 所有 t_ 表")
        with pg_engine.begin() as conn:
            # CASCADE 会连带外键引用一起删
            for t in reversed(TABLE_ORDER):
                conn.execute(text(f'DROP TABLE IF EXISTS "{t}" CASCADE'))
            conn.commit()
    Base.metadata.create_all(pg_engine)
    print(f"    create_all 完成，{len(Base.metadata.tables)} 张表")

    # —— 迁移数据 ——
    print("\n[4/6] 复制数据...")
    migrated_total = 0
    with Session(mysql_engine) as mses, Session(pg_engine) as pses:
        # 先关 FK 约束，避免导入顺序问题
        pses.execute(text("SET session_replication_role = 'replica'"))
        pses.flush()

        for table_name in TABLE_ORDER:
            table = Base.metadata.tables[table_name]

            # 读 MySQL 全量（小表，直接全读）
            rows = mses.execute(table.select()).mappings().all()
            if not rows:
                print(f"    {table_name}: 0 rows, skip")
                continue

            # 构造 dict 列表，bulk_insert_mappings 可以按列名批量插
            mappings = [dict(r) for r in rows]

            pses.execute(table.insert(), mappings)
            pses.flush()
            print(f"    {table_name}: +{len(mappings)} rows")
            migrated_total += len(mappings)

        pses.execute(text("SET session_replication_role = 'origin'"))
        pses.commit()

    print(f"    合计迁移: {migrated_total} rows")

    # —— 重置 PG 自增序列 ——
    print("\n[5/6] 重置 PG 自增序列...")
    with pg_engine.begin() as conn:
        for table_name in TABLE_ORDER:
            # PostgreSQL 用 SERIAL / GENERATED AS IDENTITY 会自动有 tablename_id_seq
            # 用 setval 把当前值推到 max(id)，这样下一条 INSERT 就会是 max+1
            conn.execute(text(f"""
                SELECT setval(
                    pg_get_serial_sequence('"{table_name}"', 'id'),
                    COALESCE((SELECT MAX("id") FROM "{table_name}"), 1)
                )
            """))
            # 也处理 invitation 里的 is_delete typo（不动它，原样迁过去）
    print("    序列重置完成")

    # —— 逐表校验 ——
    print("\n[6/6] 数据校验...")
    ok = True
    with Session(mysql_engine) as mses, Session(pg_engine) as pses:
        for table_name in TABLE_ORDER:
            my = mses.execute(text(f'SELECT COUNT(*) FROM `{table_name}`')).scalar()
            pg = pses.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
            status = "OK" if my == pg else "MISMATCH"
            if my != pg:
                ok = False
            print(f"    {table_name}: MySQL={my}  PG={pg}  [{status}]")

    mysql_engine.dispose()
    pg_engine.dispose()

    print("\n" + "=" * 60)
    if ok:
        print("✅ 迁移成功，数据一致")
    else:
        print("❌ 迁移后数据不一致，请检查 MISMATCH 的表")
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
