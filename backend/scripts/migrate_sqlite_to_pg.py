"""SQLite → PostgreSQL 一次性数据迁移。

用法（在 backend 目录执行）：
    ..\\.venv\\Scripts\\python.exe scripts\\migrate_sqlite_to_pg.py
    ..\\.venv\\Scripts\\python.exe scripts\\migrate_sqlite_to_pg.py --force   # 清空目标表后重迁

源库：storage/contract.db（固定）
目标库：.env 中的 DATABASE_URL（必须是 PostgreSQL）
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.models import domain  # noqa: E402,F401 — 注册全部模型

SQLITE_PATH = settings.STORAGE_DIR / "contract.db"


def main(force: bool) -> None:
    if not settings.DATABASE_URL.startswith("postgresql"):
        raise SystemExit("目标 DATABASE_URL 不是 PostgreSQL，请先在 .env 中配置")
    if not SQLITE_PATH.exists():
        raise SystemExit(f"源 SQLite 不存在：{SQLITE_PATH}")

    src = create_engine(f"sqlite:///{SQLITE_PATH}")
    dst = create_engine(settings.DATABASE_URL)
    Base.metadata.create_all(dst)
    tables = Base.metadata.sorted_tables  # 按外键依赖排序

    with dst.begin() as conn:
        existing = sum(conn.scalar(select(func.count()).select_from(t)) or 0 for t in tables)
        if existing and not force:
            raise SystemExit(f"目标库已有 {existing} 行数据；如确认覆盖，请加 --force")
        if force:
            for t in reversed(tables):
                conn.execute(t.delete())
            print("已清空目标库表")

        with src.connect() as sconn:
            for t in tables:
                rows = [dict(r) for r in sconn.execute(select(t)).mappings()]
                if rows:
                    conn.execute(t.insert(), rows)
                    print(f"{t.name}: {len(rows)} 行")

        # 重置自增序列，避免后续插入与已迁移主键冲突
        for t in tables:
            if "id" not in t.c:
                continue
            seq = conn.execute(
                text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": t.name}
            ).scalar()
            if seq:
                conn.exec_driver_sql(
                    f"SELECT setval('{seq}', "
                    f'COALESCE((SELECT MAX(id) FROM "{t.name}"), 0) + 1, false)'
                )

    src.dispose()
    dst.dispose()
    print("迁移完成：业务数据已写入 PostgreSQL")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 数据迁移")
    parser.add_argument("--force", action="store_true", help="清空目标库后重新迁移")
    main(parser.parse_args().force)
