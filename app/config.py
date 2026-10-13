"""Settings come only from the environment: platform.yaml `env`, Secret Manager secrets, and the variables the platform
sets for declared needs (BUCKET_UPLOADS, TOPIC_EVENTS, SUBSCRIPTION_EVENTS, DATABASE_*). Nothing is read from files."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    title: str
    log_level: str
    database_url: str | None
    database_instance: str | None
    database_name: str
    database_user: str | None
    database_ip_type: str
    bucket: str | None
    topic: str | None
    subscription: str | None
    api_key: str | None
    max_upload_bytes: int

    @property
    def project(self) -> str | None:
        """The Google Cloud project, for log trace links: explicit, or read from the platform's own variables."""
        if os.environ.get("GOOGLE_CLOUD_PROJECT"):
            return os.environ["GOOGLE_CLOUD_PROJECT"]
        if self.topic and self.topic.startswith("projects/"):
            return self.topic.split("/")[1]
        if self.database_instance and ":" in self.database_instance:
            return self.database_instance.split(":")[0]
        return None


def load() -> Settings:
    env = os.environ
    return Settings(
        title=env.get("APP_TITLE", "Lab Notebook"),
        log_level=env.get("LOG_LEVEL", "info").upper(),
        database_url=env.get("DATABASE_URL") or None,
        database_instance=env.get("DATABASE_INSTANCE") or None,
        database_name=env.get("DATABASE_NAME", "app"),
        database_user=env.get("DATABASE_USER") or None,
        database_ip_type=env.get("DATABASE_IP_TYPE", "private"),
        bucket=env.get("BUCKET_UPLOADS") or None,
        topic=env.get("TOPIC_EVENTS") or None,
        subscription=env.get("SUBSCRIPTION_EVENTS") or None,
        api_key=env.get("API_KEY") or None,
        max_upload_bytes=int(env.get("MAX_UPLOAD_MB", "10")) * 1024 * 1024,
    )
