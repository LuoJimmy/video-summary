from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# (索引名, 索引表达式, 依赖的列)：任务列表、知识库、定时汇总反查都按这些字段过滤/排序
# 列顺序要和真实 SQL 的 ORDER BY 对齐，否则 SQLite 会退回「扫描 + 临时排序」
JOB_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("idx_jobs_status", "status", ("status",)),
    (
        "idx_jobs_stamp",
        "coalesce(source_created_at, created_at), created_at, id",
        ("source_created_at", "created_at", "id"),
    ),
    ("idx_jobs_created_at", "created_at, id", ("created_at", "id")),
    ("idx_jobs_updated_at", "updated_at", ("updated_at",)),
    ("idx_jobs_domain_updated_at", "domain_id, updated_at", ("domain_id", "updated_at")),
    ("idx_jobs_schedule_log_id", "schedule_log_id", ("schedule_log_id",)),
)


def _squash(sql: str) -> str:
    return " ".join((sql or "").split()).lower()


def create_job_indexes(conn) -> None:
    """补建 / 校正 jobs 的查询索引；老库还没补上列时跳过依赖缺失列的索引。"""
    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)")).fetchall()}
    if not columns:
        return
    current = {
        row[0]: row[1]
        for row in conn.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_jobs_%'")
        ).fetchall()
    }
    for name, expression, needed in JOB_INDEXES:
        if not set(needed) <= columns:
            continue
        statement = f"CREATE INDEX IF NOT EXISTS {name} ON jobs ({expression})"
        existing = current.get(name)
        if existing and _squash(existing) != _squash(statement):
            # 索引定义升级过（例如补了排序列）就重建，否则 IF NOT EXISTS 会跳过旧定义
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
            existing = None
        if not existing:
            conn.execute(text(statement))


def migrate_job_columns() -> None:
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(jobs)")).fetchall()
        names = {row[1] for row in rows}
        if "timing_json" not in names:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN timing_json TEXT DEFAULT ''"))
        if "started_at" not in names:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN started_at DATETIME"))
        if "source_created_at" not in names:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN source_created_at DATETIME"))
        if "domain_id" not in names:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN domain_id VARCHAR(32) DEFAULT ''"))
        if "author" not in names:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN author VARCHAR(120) DEFAULT ''"))
        if "summarize_document" not in names:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN summarize_document BOOLEAN DEFAULT 0"))
        if "schedule_log_id" not in names:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN schedule_log_id VARCHAR(32) DEFAULT ''"))
        log_names = {row[1] for row in conn.execute(text("PRAGMA table_info(schedule_logs)")).fetchall()}
        if log_names and "digest_job_id" not in log_names:
            conn.execute(text("ALTER TABLE schedule_logs ADD COLUMN digest_job_id VARCHAR(32) DEFAULT ''"))
        if log_names and "rule_id" not in log_names:
            conn.execute(text("ALTER TABLE schedule_logs ADD COLUMN rule_id VARCHAR(32) DEFAULT ''"))
        if log_names and "rule_name" not in log_names:
            conn.execute(text("ALTER TABLE schedule_logs ADD COLUMN rule_name VARCHAR(120) DEFAULT ''"))
        rule_names = {row[1] for row in conn.execute(text("PRAGMA table_info(schedule_rules)")).fetchall()}
        if rule_names and "cron" not in rule_names:
            conn.execute(text("ALTER TABLE schedule_rules ADD COLUMN cron VARCHAR(120) DEFAULT ''"))
        create_job_indexes(conn)
