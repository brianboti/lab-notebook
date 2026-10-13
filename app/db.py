"""One database engine per process, created on first use: start-up stays fast and the health check never touches it.

On Cloud Run the app reaches its private Cloud SQL instance through the Cloud SQL Python connector and signs in with its
own identity (IAM database authentication): there is no password anywhere. Locally and in tests, DATABASE_URL points
at SQLite or any other database SQLAlchemy understands.
"""

import threading

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app import config

_lock = threading.Lock()
_engine: Engine | None = None
_sessions: sessionmaker | None = None
_connector = None  # the Cloud SQL connector holds an HTTP session; close it with the engine


def make_engine(settings: config.Settings) -> Engine:
    if settings.database_url:
        if settings.database_url.startswith("sqlite"):
            return create_engine(settings.database_url, connect_args={"check_same_thread": False})
        return create_engine(settings.database_url, pool_pre_ping=True)
    if settings.database_instance:
        from google.cloud.sql.connector import Connector, IPTypes

        global _connector
        # Lazy refresh: Cloud Run gives CPU only during requests, so background certificate refreshes would stall.
        connector = _connector = Connector(
            ip_type=IPTypes.PRIVATE if settings.database_ip_type == "private" else IPTypes.PUBLIC,
            enable_iam_auth=True,
            refresh_strategy="lazy",
        )

        def connect():
            return connector.connect(
                settings.database_instance, "pg8000", user=settings.database_user, db=settings.database_name
            )

        # Two instances at most, seven connections each: well inside a db-f1-micro's limit.
        return create_engine(
            "postgresql+pg8000://", creator=connect, pool_size=5, max_overflow=2, pool_timeout=30,
            pool_recycle=1800, pool_pre_ping=True,
        )
    raise RuntimeError("No database configured: set DATABASE_URL locally, or declare needs.database: postgres")


def engine() -> Engine:
    global _engine, _sessions
    with _lock:
        if _engine is None:
            _engine = make_engine(config.load())
            _sessions = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session() -> Session:
    engine()
    return _sessions()


def reset() -> None:
    """Close the engine and the connector, so the next use reads the environment again (tests, the end of a migration)."""
    global _engine, _sessions, _connector
    with _lock:
        if _engine is not None:
            _engine.dispose()
        if _connector is not None:
            _connector.close()
        _engine = _sessions = _connector = None
