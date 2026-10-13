"""Logs as event streams: one JSON object per line on stdout, which Cloud Logging turns into structured entries.

Each line carries `severity` and `message`; lines written during a request also carry the request's trace, so Cloud
Logging nests them under that request. Secrets, tokens and file contents are never logged.
"""

import contextvars
import datetime
import json
import logging
import sys

trace_context: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace", default=None)
FIELDS = ("method", "path", "status", "latency_ms", "user")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": datetime.datetime.fromtimestamp(record.created, datetime.UTC).isoformat(),
        }
        trace = trace_context.get()
        if trace:
            entry["logging.googleapis.com/trace"] = trace
        for name in FIELDS:
            if hasattr(record, name):
                entry[name] = getattr(record, name)
        if record.exc_info:
            entry["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def trace_from(header: str | None, project: str | None) -> str | None:
    """`X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=1` becomes `projects/PROJECT/traces/TRACE_ID`."""
    if not header or not project:
        return None
    trace_id = header.split("/", 1)[0]
    return f"projects/{project}/traces/{trace_id}" if trace_id else None


def configure(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level if level in ("DEBUG", "INFO", "WARNING", "ERROR") else "INFO")
    for name in ("uvicorn", "uvicorn.error"):  # the server's own lines go out as JSON too
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True  # the app writes its own request line
