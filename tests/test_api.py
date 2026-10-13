import base64
import json

KEY = {"X-API-Key": "test-key"}


def bearer(email: str) -> dict:
    claims = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return {"Authorization": f"Bearer header.{claims}.signature"}


def test_api_writes_need_the_key(client):
    assert client.post("/api/experiments", json={"title": "x"}).status_code == 401
    assert client.post("/api/experiments", json={"title": "x"}, headers={"X-API-Key": "wrong"}).status_code == 401
    created = client.post("/api/experiments", json={"title": "Assay", "description": "plate 2"}, headers=KEY)
    assert created.status_code == 201 and created.json()["title"] == "Assay"


def test_api_reads_and_deletes(client, env):
    robot = bearer("robot@p.iam.gserviceaccount.com")
    experiment = client.post("/api/experiments", json={"title": "Assay"}, headers={**KEY, **robot}).json()
    assert experiment["owner"] == "robot@p.iam.gserviceaccount.com"
    assert client.get("/api/experiments").json()["experiments"][0]["id"] == experiment["id"]
    assert client.get(f"/api/experiments/{experiment['id']}").json()["attachments"] == []
    assert client.get("/api/stats").json() == {"experiments": 1, "attachments": 0, "activity": 0}
    assert client.delete(f"/api/experiments/{experiment['id']}").status_code == 401
    assert client.delete(f"/api/experiments/{experiment['id']}", headers=KEY).status_code == 204
    assert client.get(f"/api/experiments/{experiment['id']}").status_code == 404
    assert [e["kind"] for e in env.events.queue] == ["experiment.created", "experiment.deleted"]


def test_api_validates_input(client):
    assert client.post("/api/experiments", json={"title": ""}, headers=KEY).status_code == 422
    assert client.post("/api/experiments", json={"title": "x" * 201}, headers=KEY).status_code == 422


def test_api_refuses_writes_when_no_key_is_configured(client, env, monkeypatch):
    monkeypatch.delenv("API_KEY")
    env.reset()
    assert client.post("/api/experiments", json={"title": "x"}, headers=KEY).status_code == 503


def test_whoami_reports_identity_and_backends_without_secrets(client):
    info = client.get("/api/whoami", headers=bearer("me@example.edu")).json()
    assert info["user"] == "me@example.edu" and "identity token" in info["how"]
    assert info["storage"] == "in memory" and info["api_key_configured"] is True
    assert "test-key" not in json.dumps(info)
    assert client.get("/api/whoami").json()["user"] == "anonymous"


def test_api_tags(client):
    created = client.post("/api/experiments", json={"title": "Tagged", "tags": ["Gel", "gel", "blot"]}, headers=KEY).json()
    assert created["tags"] == ["blot", "gel"]
