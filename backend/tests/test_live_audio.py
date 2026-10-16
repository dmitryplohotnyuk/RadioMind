import wave
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_scan_archive import audio_settings

from radiomind.api import create_app
from radiomind.conversation import Conversation
from radiomind.live_audio import LiveAudio
from radiomind.recording import Archive
from radiomind.storage import Store


def test_monitor_is_bounded_skips_stale_and_does_not_retain_without_listener(monkeypatch):
    bus = LiveAudio()
    bus.publish("a", b"\x01\x00" * 16000)
    assert not bus.frames
    bus.clients = 1
    monkeypatch.setattr("radiomind.live_audio.time.monotonic", lambda: 10)
    for _ in range(300):
        bus.publish("a", b"\x01\x00" * 320)
    assert len(bus.frames) == 200
    assert sum(len(f[2]) for f in bus.after(0)) == 128000
    assert bus.after(0)[0][0] == 101
    monkeypatch.setattr("radiomind.live_audio.time.monotonic", lambda: 11)
    assert bus.after(0) == []
    bus.publish("b", b"\x02\x00" * 320)
    assert len(bus.frames) == 1 and bus.session == "b"


@pytest.mark.parametrize("pre_roll_ms", [200, 1600, 3000])
def test_monitor_matches_recorded_pcm_and_verify_stays_silent(tmp_path, pre_roll_ms):
    settings = audio_settings()
    settings.audio.pre_roll_ms = pre_roll_ms
    settings.audio.verify_ms = 4000
    store = Store(tmp_path / "test.sqlite3", 10000)
    try:
        archive = Archive(settings, store)
        archive.live_audio.clients = 1
        conv = Conversation(settings, archive, settings.windows[0], 145000000, 20)
        frame = np.sin(np.arange(320) * 0.2) * 0.1
        conv.consume([(frame, False)] * (pre_roll_ms // 20 + 2))
        assert not archive.live_audio.frames and conv.writer is None
        conv.consume([(frame, True)] * 5)
        pcm = b"".join(f[2] for f in archive.live_audio.frames)
        conv.finish("test")
        with wave.open(str(archive.path(conv.session_id))) as wav:
            assert wav.readframes(wav.getnframes()) == pcm
        assert conv.recorded_samples == len(pcm) // 2
        # The first full pre-roll frame and all subsequent frames survive the
        # single publication burst. Enabling monitoring never changes the WAV.
        assert len(pcm) == (pre_roll_ms // 20 + 4) * 640
        archive.live_audio.clients = 0
        other = Conversation(settings, archive, settings.windows[0], 145000000, 20)
        other.consume([(frame, False)] * (pre_roll_ms // 20 + 2))
        other.consume([(frame, True)] * 5)
        other.finish("test")
        with wave.open(str(archive.path(other.session_id))) as wav:
            assert wav.readframes(wav.getnframes()) == pcm
    finally:
        store.close()


def test_audio_websocket_origin_and_subscriber_cleanup(tmp_path):
    app = create_app(audio_settings(), tmp_path, autostart=False)
    with TestClient(app) as client:
        bus = app.state.engine.archive.live_audio
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/audio", headers={"origin": "http://evil"}):
                pass
        assert bus.clients == 0
        with client.websocket_connect("/ws/audio", headers={"origin": "http://testserver"}) as ws:
            assert ws.receive_json() == {"type": "state", "state": "waiting"}
            client.portal.call(bus.publish, "test", b"\x03\x00" * 320)
            assert ws.receive_json() == {"type": "reset"}
            assert ws.receive_bytes() == b"\x03\x00" * 320
            # New call: maximum pre-roll followed by ongoing audio before the
            # websocket reader runs again. Every byte must arrive, in order.
            pre_roll = bytes(range(256)) * 375  # 96,000 bytes = 3 seconds.
            continuation = b"\x04\x00" * 1600

            def burst():
                bus.publish("next-call", pre_roll)
                bus.publish("next-call", continuation)

            client.portal.call(burst)
            assert ws.receive_json() == {"type": "reset"}
            assert ws.receive_bytes() == pre_roll + continuation
        # Portal executes after disconnect processing.
        client.portal.call(lambda: None)
        assert bus.clients == 0
        assert not bus.frames


def test_private_digital_staging_is_not_streamed(tmp_path):
    app = create_app(audio_settings(), tmp_path, autostart=False)
    with TestClient(app) as client:
        app.state.engine.conversation = SimpleNamespace(choice="digital", writer=None)
        try:
            with client.websocket_connect("/ws/audio") as ws:
                assert ws.receive_json() == {"type": "state", "state": "digital"}
                assert not app.state.engine.archive.live_audio.frames
        finally:
            app.state.engine.conversation = None
