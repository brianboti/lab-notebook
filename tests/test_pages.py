from conftest import IAP


def test_health_answers_without_a_database(monkeypatch):
    from fastapi.testclient import TestClient

    from app import db
    from app.main import app, backends

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_INSTANCE", raising=False)
    db.reset()
    backends.reset()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200 and response.json()["status"] == "ok"
    assert db._engine is None  # the health check never created an engine


def test_every_page_renders(client):
    for path in ("/", "/experiments", "/experiments/new", "/activity", "/whoami"):
        response = client.get(path, headers=IAP)
        assert response.status_code == 200, path
        assert "Lab Notebook" in response.text and "alice@example.edu" in response.text


def test_static_files_are_served(client):
    assert "refresh-stats" in client.get("/static/app.js").text
    assert client.get("/static/app.css").headers["content-type"].startswith("text/css")


def test_form_creates_an_experiment_owned_by_the_signed_in_person(client, env):
    response = client.post("/experiments", data={"title": "Retina scans", "description": "Batch 4"}, headers=IAP,
                           follow_redirects=False)
    assert response.status_code == 303
    detail = client.get(response.headers["location"], headers=IAP)
    assert "Retina scans" in detail.text and "Batch 4" in detail.text and "Delete experiment" in detail.text
    assert env.events.queue[-1]["kind"] == "experiment.created" and env.events.queue[-1]["actor"] == "alice@example.edu"


def test_cross_site_form_posts_are_refused(client):
    response = client.post("/experiments", data={"title": "x"}, headers={**IAP, "Origin": "https://evil.example"})
    assert response.status_code == 403


def test_status_change_is_saved_and_announced(client, env):
    location = client.post("/experiments", data={"title": "Gel"}, headers=IAP, follow_redirects=False).headers["location"]
    client.post(f"{location}/status", data={"status": "running"}, headers=IAP)
    assert "badge running" in client.get(location, headers=IAP).text
    assert env.events.queue[-1]["kind"] == "experiment.status"
    assert client.post(f"{location}/status", data={"status": "lost"}, headers=IAP).status_code == 422


def test_search_and_filter(client):
    client.post("/experiments", data={"title": "Retina scans"}, headers=IAP)
    client.post("/experiments", data={"title": "Western blot", "description": "retina tissue"}, headers=IAP)
    found = client.get("/experiments", params={"q": "retina"}).text
    assert "Retina scans" in found and "Western blot" in found
    assert "Western blot" not in client.get("/experiments", params={"q": "scans"}).text
    assert "Nothing found" in client.get("/experiments", params={"status": "done"}).text


def test_only_the_owner_may_delete(client):
    location = client.post("/experiments", data={"title": "Mine"}, headers=IAP, follow_redirects=False).headers["location"]
    bob = {"X-Goog-Authenticated-User-Email": "accounts.google.com:bob@example.edu"}
    assert "Delete experiment" not in client.get(location, headers=bob).text
    assert client.post(f"{location}/delete", headers=bob).status_code == 403
    assert client.post(f"{location}/delete", headers=IAP, follow_redirects=False).status_code == 303
    assert client.get(location).status_code == 404


def test_unknown_experiment_is_404(client):
    assert client.get("/experiments/999").status_code == 404
