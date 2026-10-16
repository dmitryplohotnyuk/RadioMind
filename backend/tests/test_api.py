import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from radiomind.api import create_app
from radiomind.config import Settings, Window
from radiomind.storage import Store


def wait_frame(client: TestClient) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get("/api/spectrum")
        if response.status_code == 200:
            return response.json()
        time.sleep(0.02)
    raise AssertionError("No spectrum produced")


def test_open_local_http_control_and_mock_iq(tmp_path: Path) -> None:
    app = create_app(Settings(), tmp_path)
    with TestClient(app) as client:
        for endpoint in ("/api/status", "/api/events", "/api/observations", "/api/recordings"):
            assert client.get(endpoint).status_code == 200
        assert 'id="token"' not in client.get("/").text
        for asset in ("/messages.js", "/i18n.js", "/live-audio.js", "/app.js"):
            response = client.get(asset)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/javascript")
        assert (
            client.post(
                "/api/control", json={"action": "watch"}, headers={"Origin": "http://evil.invalid"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/control", json={"action": "watch"}, headers={"Origin": "http://testserver"}
            ).status_code
            == 200
        )
        client.post("/api/control", json={"action": "sweep"})
        assert client.get("/", headers={"host": "evil.invalid"}).status_code == 400
        assert client.get("/").status_code == 200
        assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
        assert client.get("/health").json() == {"status": "alive"}
        frame = wait_frame(client)
        assert frame["source"] == "mock" and len(frame["psd_dbfs_hz"]) > 100
        assert frame["continuous_capture"] is False
        assert client.get("/api/events?limit=99999").status_code == 422
        assert client.post("/api/control", json={"action": "tx"}).status_code == 422
        assert client.get("/../../.env").status_code == 404
        assert client.post("/api/control", json={"action": "stop"}).status_code == 200
        assert client.get("/api/spectrum").status_code == 503
        status = client.get("/api/status").json()
        assert not status["running"] and not status["record_audio"]
        assert client.get("/api/observations").json()
        client.post("/api/control", json={"action": "start"})
        assert wait_frame(client)["sequence"] > frame["sequence"]
    assert not list(tmp_path.rglob("*.wav")) and not list(tmp_path.rglob("*.iq"))


def test_websocket_open_stream_and_origin(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(), tmp_path)) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"Origin": "http://evil.invalid"}):
                pass
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["source"] == "mock"


def test_sweep_events_are_persisted_for_both_windows(tmp_path: Path) -> None:
    settings = Settings(
        frame_period_ms=100,
        windows=[
            Window(name="VHF", start_hz=140_000_000, end_hz=148_000_000, dwell_ms=500),
            Window(name="UHF", start_hz=420_000_000, end_hz=428_000_000, dwell_ms=500),
        ],
    )
    with TestClient(create_app(settings, tmp_path)) as client:
        deadline = time.monotonic() + 5
        found = set()
        while time.monotonic() < deadline:
            events = client.get("/api/events").json()
            found = {event["window"] for event in events}
            if found == {"VHF", "UHF"}:
                break
            time.sleep(0.05)
        assert found == {"VHF", "UHF"}
        assert all(e["recording_path"] is None and e["signal_class"] == "unknown" for e in events)


def test_store_quota_stops_without_deleting(tmp_path: Path) -> None:
    store = Store(tmp_path / "test.sqlite3", max_rows=2)
    store.append("event", "2026-10-14T00:00:00Z", {"frequency_hz": 145_000_000})
    store.append("event", "2026-10-14T00:00:01Z", {"frequency_hz": 145_100_000})
    with pytest.raises(RuntimeError, match="quota"):
        store.append("event", "2026-10-14T00:00:02Z", {})
    assert len(store.recent("event")) == 2
    store.close()


def test_full_diagnostic_store_can_keep_rx_archive_and_controls_running(tmp_path):
    store = Store(tmp_path / "mock.sqlite3", 100)
    for i in range(100):
        store.append("observation", str(i), {"original": i})
    before = store.db.execute("SELECT * FROM metadata").fetchall()
    store.close()
    settings = Settings(max_metadata_rows=100, metadata_full_policy="drop_new")
    with TestClient(create_app(settings, tmp_path)) as client:
        wait_frame(client)
        deadline = time.monotonic() + 5
        while True:
            status = client.get("/api/status").json()
            if status["metadata"]["skipped_since_start"] or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        assert status["running"] and status["error"] is None
        assert status["metadata"]["full"]
        assert sum(status["metadata"]["skipped_since_start"].values()) > 0
        store = client.app.state.store
        store.save_recording({"id": "saved-at-full-quota", "frequency_hz": 145000000})
        assert store.recording("saved-at-full-quota") is not None
        assert (
            client.post(
                "/api/channels", json={"frequency_hz": 145000000, "action": "priority"}
            ).status_code
            == 200
        )
        assert store.channel(145000000)["priority"]
        assert store.metadata_skipped["audit"] == 1
        assert store.db.execute("SELECT * FROM metadata").fetchall() == before
        assert client.post("/api/control", json={"action": "stop"}).status_code == 200


def test_transcription_removed_and_existing_texts_preserved(tmp_path):
    archive = tmp_path / "mock-text"
    archive.mkdir()
    original = archive / "existing.json"
    original.write_bytes(b'{"segments":[]}')
    with TestClient(create_app(Settings(), tmp_path, autostart=False)) as client:
        assert "asr" not in client.get("/api/status").json()
        assert 'id="transcript-panel"' not in client.get("/").text
        assert "openTranscript" not in client.get("/app.js").text
        path = "/api/conversations/" + "a" * 32 + "/transcript"
        assert client.get(path).status_code == 404
        assert client.post(path).status_code == 404
        assert original.read_bytes() == b'{"segments":[]}'
    assert original.read_bytes() == b'{"segments":[]}'


def test_negative_digital_review_rejects_preset_without_excluding_frequency(tmp_path):
    app = create_app(Settings(), tmp_path, autostart=False)
    with TestClient(app) as client:
        store = app.state.store
        for ident in ["first", "second"]:
            store.save_recording({"id": ident, "frequency_hz": 421325000, "protocol": "DMR"})
        store.remember_digital(421325000, "DMR")
        store.remember_digital(154400000, "DMR")
        assert store.digital_mode(421325000) == "DMR"
        for ident in ["first", "second"]:
            assert (
                client.post(f"/api/recordings/{ident}/review", json={"label": "noise"}).status_code
                == 200
            )
        store.remember_digital(421325000, "DMR")
        assert store.digital_mode(421325000) == "auto"
        assert store.digital_mode(154400000) == "DMR"
        assert not store.channel(421325000)["manual"]
        assert len(store.recordings()) == 2
        client.post("/api/recordings/second/review", json={"label": "unreviewed"})
        store.remember_digital(421325000, "DMR")
        assert store.digital_mode(421325000) == "auto"  # First rejection still applies.
        client.post("/api/recordings/second/review", json={"label": "speech"})
        store.remember_digital(421325000, "DMR")
        assert store.digital_mode(421325000) == "DMR"
        client.post("/api/recordings/second/review", json={"label": "unreviewed"})
        assert store.digital_mode(421325000) == "auto"
        client.post("/api/recordings/first/review", json={"label": "unreviewed"})
        store.remember_digital(421325000, "DMR")
        assert store.digital_mode(421325000) == "DMR"
