"""The parts of the Lab Deploy contract the app is responsible for: settings, logs, migrations and its own files."""

import json
import logging
import re
from pathlib import Path

import yaml
from conftest import ROOT, migrate
from sqlalchemy import inspect

from app import config, db
from app.logs import JsonFormatter, trace_context, trace_from


def test_platform_settings_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("TOPIC_EVENTS", "projects/lab-proj/topics/lab-notebook-events")
    monkeypatch.setenv("BUCKET_UPLOADS", "lab-proj-lab-notebook-uploads")
    monkeypatch.setenv("DATABASE_INSTANCE", "lab-proj:us-central1:lab-notebook")
    monkeypatch.setenv("MAX_UPLOAD_MB", "3")
    settings = config.load()
    assert settings.project == "lab-proj" and settings.bucket.endswith("-uploads")
    assert settings.max_upload_bytes == 3 * 1024 * 1024 and settings.database_name == "app"


def test_log_lines_are_json_with_severity_and_trace():
    record = logging.LogRecord("lab_notebook", logging.ERROR, __file__, 1, "upload failed for %s", ("#3",), None)
    record.path = "/experiments/3/attachments"
    token = trace_context.set(trace_from("abc123/456;o=1", "lab-proj"))
    try:
        entry = json.loads(JsonFormatter().format(record))
    finally:
        trace_context.reset(token)
    assert entry["severity"] == "ERROR" and entry["message"] == "upload failed for #3"
    assert entry["logging.googleapis.com/trace"] == "projects/lab-proj/traces/abc123"
    assert entry["path"] == "/experiments/3/attachments"
    assert trace_from(None, "p") is None and trace_from("abc/1", None) is None


def test_migrations_go_up_and_down_cleanly(env):
    tables = set(inspect(db.engine()).get_table_names())
    assert {"experiments", "attachments", "activity", "alembic_version"} <= tables
    migrate("0001", down=True)
    db.reset()
    assert "activity" not in inspect(db.engine()).get_table_names()
    migrate("base", down=True)
    migrate()
    db.reset()
    assert {"experiments", "attachments", "activity"} <= set(inspect(db.engine()).get_table_names())


def test_repository_follows_the_lab_deploy_contract():
    spec = yaml.safe_load((ROOT / "platform.yaml").read_text())
    assert spec["reviewed"] is True and spec["health_path"] == "/health"
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert re.search(rf"^EXPOSE {spec['port']}$", dockerfile, re.M)
    assert re.search(r"^USER \d+:\d+$", dockerfile, re.M) and 'CMD ["uvicorn"' in dockerfile
    assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$", dockerfile, re.M)
    for name in ("requirements.txt", "requirements.lock", "requirements-dev.txt", "README.md", "LICENSE", "SECURITY.md", ".dockerignore"):
        assert (ROOT / name).exists(), name
    pinned = [line for line in (ROOT / "requirements.txt").read_text().splitlines() if line and not line.startswith("#")]
    assert pinned and all(re.fullmatch(r"[A-Za-z0-9_.\-\[\]]+==[\w.]+", line) for line in pinned)
    assert "--hash=sha256:" in (ROOT / "requirements.lock").read_text()
    assert Path(ROOT / "app" / "templates").is_dir()
