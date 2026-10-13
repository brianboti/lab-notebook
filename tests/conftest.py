from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ("BUCKET_UPLOADS", "TOPIC_EVENTS", "SUBSCRIPTION_EVENTS", "DATABASE_INSTANCE", "DATABASE_USER", "GOOGLE_CLOUD_PROJECT")


def migrate(revision: str = "head", down: bool = False) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    (command.downgrade if down else command.upgrade)(config, revision)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fresh SQLite database migrated to head, in-memory storage and events, and a known API key."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'notebook.db'}")
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    for name in CLOUD:
        monkeypatch.delenv(name, raising=False)
    from app import db
    from app.main import backends

    db.reset()
    backends.reset()
    migrate()
    yield backends
    db.reset()


@pytest.fixture
def client(env):
    with TestClient(env_app()) as client:
        yield client


def env_app():
    from app.main import app

    return app


IAP = {"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@example.edu"}
