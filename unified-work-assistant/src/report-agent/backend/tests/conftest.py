import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DB = Path(__file__).resolve().parents[1] / "test_work_assistant.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["LLM_PROVIDER"] = "mock"

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    TEST_DB.unlink(missing_ok=True)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def anyio_backend():
    return "asyncio"
