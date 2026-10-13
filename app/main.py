"""Lab Notebook: pages for people and a JSON API for programs, on one FastAPI service."""

import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import __version__, config, db
from app.auth import current_user, require_api_key
from app.events import MemoryEvents, PubSubEvents
from app.logs import configure, trace_context, trace_from
from app.models import STATUSES, Activity, Attachment, Experiment
from app.storage import BucketStorage, MemoryStorage

HERE = Path(__file__).parent
log = logging.getLogger("lab_notebook")
templates = Jinja2Templates(directory=HERE / "templates")


class Backends:
    """Settings and cloud clients, created on first use so start-up stays fast; reset() re-reads the environment."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.settings = config.load()
        self._storage = self._events = None
        configure(self.settings.log_level)

    @property
    def storage(self):
        with self.lock:
            if self._storage is None:
                self._storage = BucketStorage(self.settings.bucket) if self.settings.bucket else MemoryStorage()
            return self._storage

    @property
    def events(self):
        with self.lock:
            if self._events is None:
                configured = self.settings.topic and self.settings.subscription
                self._events = PubSubEvents(self.settings.topic, self.settings.subscription) if configured else MemoryEvents()
            return self._events


backends = Backends()
app = FastAPI(title="Lab Notebook", version=__version__)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.middleware("http")
async def observe(request: Request, call_next):
    """One log line per request, with its trace; a same-origin rule for form posts; every exception handled."""
    started = time.perf_counter()
    trace_context.set(trace_from(request.headers.get("x-cloud-trace-context"), backends.settings.project))
    path = request.url.path
    if request.method == "POST" and not path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"error": "Cross-site form posts are refused"}, status_code=403)
    try:
        response = await call_next(request)
    except Exception:
        log.exception("Unhandled error", extra={"method": request.method, "path": path})
        response = JSONResponse({"error": "Internal error; the details are in the service log"}, status_code=500)
    if path != "/health" and not path.startswith("/static/"):
        log.info("%s %s %s", request.method, path, response.status_code, extra={
            "method": request.method, "path": path, "status": response.status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1), "user": current_user(request)})
    return response


def page(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
    context = {"title": backends.settings.title, "user": current_user(request), "version": __version__, **context}
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def counts(session: Session) -> dict:
    return {
        "experiments": session.scalar(select(func.count(Experiment.id))),
        "attachments": session.scalar(select(func.count(Attachment.id))),
        "activity": session.scalar(select(func.count(Activity.id))),
    }


def load_experiment(session: Session, experiment_id: int) -> Experiment:
    experiment = session.scalar(select(Experiment).where(Experiment.id == experiment_id).options(selectinload(Experiment.attachments)))
    if experiment is None:
        raise HTTPException(404, "No such experiment")
    return experiment


def as_dict(experiment: Experiment, attachments: bool = False) -> dict:
    data = {"id": experiment.id, "title": experiment.title, "description": experiment.description,
            "status": experiment.status, "owner": experiment.owner, "tags": tag_list(experiment.tags),
            "created_at": experiment.created_at.isoformat()}
    if attachments:
        data["attachments"] = [{"id": a.id, "filename": a.filename, "content_type": a.content_type, "size": a.size,
                                "uploaded_by": a.uploaded_by} for a in experiment.attachments]
    return data


def tag_list(tags: str) -> list[str]:
    return [tag for tag in tags.split(",") if tag]


def clean_tags(raw: str | list[str]) -> str:
    items = raw if isinstance(raw, list) else raw.split(",")
    tags = sorted({re.sub(r"[^a-z0-9-]", "", item.strip().lower())[:30] for item in items} - {""})
    return ",".join(tags)[:200]


def create(title: str, description: str, owner: str, tags: str | list[str] = "") -> Experiment:
    title, description = title.strip(), description.strip()
    if not title or len(title) > 200:
        raise HTTPException(422, "A title of 1 to 200 characters is required")
    with db.session() as session:
        experiment = Experiment(title=title, description=description, owner=owner, tags=clean_tags(tags))
        session.add(experiment)
        session.commit()
    backends.events.publish("experiment.created", f"#{experiment.id} {title}", owner)
    return experiment


def remove(experiment_id: int, actor: str) -> None:
    with db.session() as session:
        experiment = load_experiment(session, experiment_id)
        for attachment in experiment.attachments:
            backends.storage.delete(attachment.object_name)
        session.delete(experiment)
        session.commit()
    backends.events.publish("experiment.deleted", f"#{experiment_id}", actor)


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name or "file").strip("._") or "file"
    return cleaned[-100:]


# ---- health

@app.get("/health")
def health():
    """Readiness without side effects: no database, bucket or topic call that could fail or cost."""
    if os.environ.get("K_SERVICE"):  # SCENARIO: a bug that only shows on Cloud Run (K_SERVICE is set there)
        return JSONResponse({"status": "broken"}, status_code=503)
    return {"status": "ok", "version": __version__}


# ---- pages for people

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with db.session() as session:
        stats = counts(session)
        recent = session.scalars(select(Experiment).order_by(Experiment.id.desc()).limit(5)).all()
    return page(request, "index.html", stats=stats, recent=recent)


@app.get("/experiments", response_class=HTMLResponse)
def experiments(request: Request, q: str = "", status: str = "", tag: str = ""):
    query = select(Experiment).order_by(Experiment.id.desc()).limit(100)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Experiment.title.ilike(like), Experiment.description.ilike(like)))
    if status in STATUSES:
        query = query.where(Experiment.status == status)
    with db.session() as session:
        found = session.scalars(query).all()
    if tag:
        found = [e for e in found if tag in tag_list(e.tags)]
    return page(request, "experiments.html", experiments=found, q=q, status=status, statuses=STATUSES, tag=tag)


@app.get("/experiments/new", response_class=HTMLResponse)
def new_experiment(request: Request):
    return page(request, "new.html")


@app.post("/experiments")
def create_from_form(request: Request, title: Annotated[str, Form()], description: Annotated[str, Form()] = "",
                     tags: Annotated[str, Form()] = ""):
    experiment = create(title, description, current_user(request), tags)
    return RedirectResponse(f"/experiments/{experiment.id}", status_code=303)


@app.get("/experiments/{experiment_id}", response_class=HTMLResponse)
def experiment_page(request: Request, experiment_id: int):
    with db.session() as session:
        experiment = load_experiment(session, experiment_id)
    return page(request, "experiment.html", experiment=experiment, statuses=STATUSES,
                can_delete=current_user(request) == experiment.owner,
                max_mb=backends.settings.max_upload_bytes // (1024 * 1024))


@app.post("/experiments/{experiment_id}/status")
def change_status(request: Request, experiment_id: int, status: Annotated[str, Form()]):
    if status not in STATUSES:
        raise HTTPException(422, f"Status must be one of {', '.join(STATUSES)}")
    with db.session() as session:
        experiment = load_experiment(session, experiment_id)
        experiment.status = status
        session.commit()
    backends.events.publish("experiment.status", f"#{experiment_id} is {status}", current_user(request))
    return RedirectResponse(f"/experiments/{experiment_id}", status_code=303)


@app.post("/experiments/{experiment_id}/attachments")
def upload(request: Request, experiment_id: int, file: Annotated[UploadFile, File()]):
    limit = backends.settings.max_upload_bytes
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Files up to {limit // (1024 * 1024)} MB are accepted")
    if not data:
        raise HTTPException(422, "The file is empty")
    filename = safe_filename(file.filename)
    content_type = (file.content_type or "application/octet-stream")[:100]
    user = current_user(request)
    with db.session() as session:
        load_experiment(session, experiment_id)
        name = f"experiments/{experiment_id}/{uuid.uuid4().hex}-{filename}"
        backends.storage.put(name, data, content_type)
        session.add(Attachment(experiment_id=experiment_id, filename=filename, content_type=content_type,
                               size=len(data), object_name=name, uploaded_by=user))
        session.commit()
    backends.events.publish("attachment.uploaded", f"{filename} on #{experiment_id} ({len(data)} bytes)", user)
    return RedirectResponse(f"/experiments/{experiment_id}", status_code=303)


@app.post("/experiments/{experiment_id}/delete")
def delete_from_form(request: Request, experiment_id: int):
    user = current_user(request)
    with db.session() as session:
        if load_experiment(session, experiment_id).owner != user:
            raise HTTPException(403, "Only the experiment's owner may delete it")
    remove(experiment_id, user)
    return RedirectResponse("/experiments", status_code=303)


@app.get("/attachments/{attachment_id}")
def download(attachment_id: int):
    with db.session() as session:
        attachment = session.get(Attachment, attachment_id)
        if attachment is None:
            raise HTTPException(404, "No such attachment")
    data = backends.storage.get(attachment.object_name)
    return Response(data, media_type=attachment.content_type,
                    headers={"Content-Disposition": f'attachment; filename="{attachment.filename}"'})


@app.get("/activity", response_class=HTMLResponse)
def activity(request: Request):
    received = backends.events.pull()
    stored = []
    with db.session() as session:
        for event, ack_id in received:
            if session.scalar(select(Activity.id).where(Activity.message_id == event["id"])) is None:
                session.add(Activity(message_id=event["id"], kind=str(event.get("kind", "unknown"))[:40],
                                     detail=str(event.get("detail", ""))[:2000], actor=str(event.get("actor", ""))[:320]))
            stored.append(ack_id)
        try:
            session.commit()
        except IntegrityError:  # another request stored the same message a moment earlier
            session.rollback()
        items = session.scalars(select(Activity).order_by(Activity.id.desc()).limit(50)).all()
    backends.events.ack(stored)
    return page(request, "activity.html", items=items, received=len(received))


@app.get("/whoami", response_class=HTMLResponse)
def whoami(request: Request):
    return page(request, "whoami.html", info=identity(request))


def identity(request: Request) -> dict:
    s = backends.settings
    if request.headers.get("x-goog-authenticated-user-email"):
        how = "Google sign-in through the Identity-Aware Proxy"
    elif request.headers.get("authorization"):
        how = "a Google identity token checked by Cloud Run"
    else:
        how = "nobody vouched for this caller (local run)"
    return {"user": current_user(request), "how": how, "version": __version__,
            "database": "Cloud SQL (IAM sign-in)" if s.database_instance else ("DATABASE_URL" if s.database_url else "none"),
            "storage": f"bucket {s.bucket}" if s.bucket else "in memory", "events": "Pub/Sub" if s.topic else "in memory",
            "api_key_configured": bool(s.api_key)}


# ---- JSON API for programs

class ExperimentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=10000)
    tags: list[str] = Field(default_factory=list, max_length=10)


@app.get("/api/stats")
def api_stats():
    with db.session() as session:
        return counts(session)


@app.get("/api/whoami")
def api_whoami(request: Request):
    return identity(request)


@app.get("/api/experiments")
def api_list(limit: int = 50):
    with db.session() as session:
        found = session.scalars(select(Experiment).order_by(Experiment.id.desc()).limit(min(max(limit, 1), 200))).all()
        return {"experiments": [as_dict(e) for e in found]}


@app.post("/api/experiments", status_code=201)
def api_create(request: Request, body: ExperimentIn):
    require_api_key(request, backends.settings.api_key)
    return as_dict(create(body.title, body.description, current_user(request), body.tags))


@app.get("/api/experiments/{experiment_id}")
def api_get(experiment_id: int):
    with db.session() as session:
        return as_dict(load_experiment(session, experiment_id), attachments=True)


@app.delete("/api/experiments/{experiment_id}", status_code=204)
def api_delete(request: Request, experiment_id: int):
    require_api_key(request, backends.settings.api_key)
    remove(experiment_id, current_user(request))
    return Response(status_code=204)
