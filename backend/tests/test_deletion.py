import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from radiomind.api import create_app
from radiomind.config import Settings
from radiomind.storage import Store


def recording(app, frequency=145000000, session=None, part=1):
    ident = uuid4().hex
    row = {
        "id": ident,
        "session_id": session or ident,
        "frequency_hz": frequency,
        "part_number": part,
        "start_utc": "2026-10-15T00:00:00+00:00",
        "status": "ready",
        "playable": True,
        "duration_seconds": 1,
    }
    app.state.store.save_recording(row)
    app.state.engine.archive.path(ident).write_bytes(b"original")
    return row


def preview(client, **selection):
    response = client.post("/api/archive/delete-preview", json=selection)
    assert response.status_code == 200, response.text
    return response.json()


def test_delete_conversation_parts_copies_and_keep_channel_rules(tmp_path):
    app = create_app(Settings(), tmp_path, autostart=False)
    with TestClient(app) as client:
        first = recording(app)
        second = recording(app, session=first["id"], part=2)
        other = recording(app)
        cleaned = app.state.cleaner.path(first["id"])
        cleaned.write_bytes(b"cleaned")
        legacy = app.state.engine.archive.path(first["id"]).with_suffix(".clean-v1.wav")
        legacy.write_bytes(b"legacy")
        previous = app.state.engine.archive.path(first["id"]).with_suffix(".clean-v2.wav")
        previous.write_bytes(b"previous")
        text = tmp_path / "mock-text" / (first["id"] + ".json")
        text.parent.mkdir()
        text.write_text("{}")
        channel = app.state.store.channel(145000000)
        channel.update(manual=1, priority=1)
        app.state.store.save_channel(channel)
        plan = preview(client, session_id=first["id"])
        assert (plan["conversations"], plan["parts"]) == (1, 2)
        assert (
            client.post(
                "/api/archive/delete",
                json={"token": plan["token"]},
                headers={"Origin": "http://evil"},
            ).status_code
            == 403
        )
        response = client.post("/api/archive/delete", json={"token": plan["token"]})
        assert response.json() == {"deleted_sessions": [first["id"]], "pending_file_cleanup": 0}
        for row in (first, second):
            assert not app.state.engine.archive.path(row["id"]).exists()
        assert not cleaned.exists() and not text.exists()
        assert not legacy.exists()
        assert not previous.exists()
        assert app.state.engine.archive.path(other["id"]).read_bytes() == b"original"
        assert app.state.store.channel(145000000) == channel
        assert (
            client.get(f"/api/conversations/{first['id']}/audio?variant=cleaned").status_code == 404
        )
        assert client.post("/api/archive/delete", json={"token": plan["token"]}).status_code == 409


def test_frequency_delete_all_pages_stale_preview_and_active_capture(tmp_path):
    app = create_app(Settings(), tmp_path, autostart=False)
    with TestClient(app) as client:
        first = recording(app)
        for _ in range(501):
            row = {**first, "id": uuid4().hex}
            row["session_id"] = row["id"]
            app.state.store.save_recording(row)
        other = recording(app, 145006250)
        plan = preview(client, frequency_hz=145000000)
        assert plan["conversations"] == 502
        added = recording(app)
        assert client.post("/api/archive/delete", json={"token": plan["token"]}).status_code == 409
        assert app.state.store.recording(first["id"])
        app.state.engine.conversation = SimpleNamespace(
            done=False, frequency_hz=145000000, session_id=uuid4().hex
        )
        try:
            assert (
                client.post(
                    "/api/archive/delete-preview", json={"frequency_hz": 145000000}
                ).status_code
                == 409
            )
        finally:
            app.state.engine.conversation = None
        app.state.cleaner.states[added["id"]] = "processing"
        assert (
            client.post("/api/archive/delete-preview", json={"frequency_hz": 145000000}).status_code
            == 409
        )
        app.state.cleaner.states.clear()
        plan = preview(client, frequency_hz=145000000)
        assert plan["conversations"] == 503
        assert client.post("/api/archive/delete", json={"token": plan["token"]}).status_code == 200
        assert [r["id"] for r in app.state.store.recordings()] == [other["id"]]
        assert client.post("/api/archive/delete-preview", json={}).status_code == 422
        assert (
            client.post(
                "/api/archive/delete-preview", json={"session_id": "../../outside"}
            ).status_code
            == 409
        )


def test_delete_locked_file_retries_after_restart_without_playback(tmp_path, monkeypatch):
    app = create_app(Settings(), tmp_path, autostart=False)
    unlink = Path.unlink
    with TestClient(app) as client:
        row = recording(app)
        target = app.state.engine.archive.path(row["id"])

        def locked(path, *args, **kwargs):
            if path == target:
                raise PermissionError("Simulated Windows file in use")
            return unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", locked)
        plan = preview(client, session_id=row["id"])
        result = client.post("/api/archive/delete", json={"token": plan["token"]}).json()
        assert result["pending_file_cleanup"] == 1 and target.exists()
        assert client.get(f"/api/recordings/{row['id']}/audio").status_code == 404
    monkeypatch.setattr(Path, "unlink", unlink)
    with TestClient(create_app(Settings(), tmp_path, autostart=False)) as client:
        assert not target.exists()
        assert client.get("/api/conversations").json() == []


def test_failed_decoder_diagnostics_remain_bounded_when_metadata_is_full(tmp_path):
    store = Store(tmp_path / "mock.sqlite3", 0, "drop_new")
    try:
        store.db.executemany(
            "INSERT INTO digital_attempts(payload) VALUES(?)",
            [(json.dumps({"outcome": "not_decoded", "number": i}),) for i in range(2000)],
        )
        store.db.commit()
        store.save_digital_attempt({"outcome": "encryption_indicated", "number": 2000})
        assert store.db.execute("SELECT COUNT(*) FROM digital_attempts").fetchone()[0] == 2000
        assert store.digital_attempts(1)[0]["number"] == 2000
        assert store.count == 0
    finally:
        store.close()
