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
