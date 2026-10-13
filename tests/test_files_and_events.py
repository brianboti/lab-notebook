from conftest import IAP


def new_experiment(client) -> str:
    return client.post("/experiments", data={"title": "Imaging"}, headers=IAP, follow_redirects=False).headers["location"]


def test_upload_stores_the_file_and_download_returns_it(client, env):
    location = new_experiment(client)
    response = client.post(f"{location}/attachments", files={"file": ("scan 01.png", b"\x89PNG data", "image/png")},
                           headers=IAP, follow_redirects=False)
    assert response.status_code == 303
    page = client.get(location, headers=IAP).text
    assert "scan_01.png" in page
    (name, (data, kind)), = env.storage.objects.items()
    assert data == b"\x89PNG data" and kind == "image/png" and name.endswith("-scan_01.png")
    download = client.get("/attachments/1")
    assert download.content == b"\x89PNG data" and download.headers["content-type"] == "image/png"
    assert 'filename="scan_01.png"' in download.headers["content-disposition"]
    assert env.events.queue[-1]["kind"] == "attachment.uploaded"


def test_upload_limits(client):
    location = new_experiment(client)
    too_big = b"x" * (1024 * 1024 + 1)
    assert client.post(f"{location}/attachments", files={"file": ("big.bin", too_big)}).status_code == 413
    assert client.post(f"{location}/attachments", files={"file": ("empty.txt", b"")}).status_code == 422
    assert client.post("/experiments/999/attachments", files={"file": ("a.txt", b"a")}).status_code == 404


def test_unsafe_filenames_are_cleaned(client, env):
    location = new_experiment(client)
    client.post(f"{location}/attachments", files={"file": ('../../etc/"passwd"', b"a")})
    (name,) = env.storage.objects
    assert "/" not in name.split("/", 2)[2] and '"' not in name


def test_activity_reads_the_queue_once_and_keeps_history(client, env):
    new_experiment(client)
    first = client.get("/activity").text
    assert "1 new event read" in first and "experiment.created" in first
    assert env.events.queue == [] and env.events.pending == {}  # acknowledged after storing
    again = client.get("/activity").text
    assert "0 new events read" in again and again.count("experiment.created") == 1


def test_redelivered_message_is_stored_once(client, env):
    env.events.publish("experiment.created", "#1 x", "alice@example.edu")
    duplicate = dict(env.events.queue[0])
    env.events.queue.append(duplicate)
    assert client.get("/activity").text.count("#1 x") == 1


def test_deleting_an_experiment_removes_its_files(client, env):
    location = new_experiment(client)
    client.post(f"{location}/attachments", files={"file": ("a.txt", b"a")})
    assert env.storage.objects
    client.post(f"{location}/delete", headers=IAP)
    assert env.storage.objects == {}
