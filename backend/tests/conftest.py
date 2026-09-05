import os
import sys
from pathlib import Path

os.environ["PREFETCH_SENSEVOICE"] = "0"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, get_db
from app.main import app
from app.services.lexicon import set_lexicon_path, set_lexicon_root
from app.services.domain import set_domain_path
from app.services.pipeline import set_pipeline
from app.services.seed import seed_defaults


class IdlePipeline:
    def run_job(self, job_id: str) -> None:
        return None

    def resummarize_job(self, job_id: str) -> None:
        return None

    def proofread_job(self, job_id: str) -> None:
        return None

    def retranscribe_job(self, job_id: str, continue_after: bool = True) -> None:
        return None


@pytest.fixture(autouse=True)
def isolated_lexicon(tmp_path):
    set_lexicon_path(None)
    set_lexicon_root(tmp_path)
    set_domain_path(tmp_path / "domain_pack.json")
    yield
    set_lexicon_path(None)
    set_lexicon_root(None)
    set_domain_path(None)


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    session = TestingSession()
    seed_defaults(session)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    def override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    set_pipeline(IdlePipeline())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    set_pipeline(None)
