import ctypes as ct
import io
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_audio import audio_settings
from test_hackrf_boundary import fake_source

from radiomind.api import create_app
from radiomind.conversation import Conversation
from radiomind.hackrf import Transfer
from radiomind.pcm import pcm16
from radiomind.recording import Archive, RecordingWriter
from radiomind.storage import Store


def feed_raw(source, raw: bytes) -> None:
    native = (ct.c_uint8 * len(raw)).from_buffer_copy(raw)
    transfer = Transfer(None, native, len(raw), len(raw), None, None)
    assert source._receive(ct.pointer(transfer)) == 0


def test_history_snapshot_to_live_is_sample_exact_and_bounded() -> None:
    source = fake_source()
    source._init_history(1)
    raw = np.arange(24000, dtype=np.int32).astype(np.int8).tobytes()
    for start in range(0, 20000, 2000):
        feed_raw(source, raw[start : start + 2000])
        source.read(8)  # Sparse preview must not consume the history.
    assert source.history_samples == 8000
    source.set_continuous(True)
    assert source.capture_start_sample == 2000
    assert source.capture_history_samples == 8000
    feed_raw(source, raw[20000:])
    collected = b"".join(source.blocks.get_nowait() for _ in range(source.blocks.qsize()))
    assert collected == raw[4000:]
    assert source.application_dropped_samples == 0
    assert not source.history
    stamp = datetime.fromisoformat(source.capture_start_utc)
    assert abs(stamp.timestamp() - (source.stream_start + 2000 / 8_000_000)) < 1e-6


def test_history_retune_and_settling_do_not_replay_old_frequency() -> None:
    source = fake_source()
    source._init_history(1000)
    feed_raw(source, bytes([1, 2]) * 100)
    source._reset_history()  # tune invokes this after stopping native RX.
    source.settle_blocks = 1
    feed_raw(source, bytes([3, 4]) * 100)
    feed_raw(source, bytes([5, 6]) * 100)
    source.set_continuous(True)
    assert source.blocks.get_nowait() == bytes([5, 6]) * 100
    assert source.blocks.empty()
    assert source.capture_start_sample == 0
    assert source.tune_generation == 1
    source.set_continuous(True)  # Idempotent: never flush an active capture.
    feed_raw(source, bytes([7, 8]) * 100)
    assert source.blocks.get_nowait() == bytes([7, 8]) * 100


def test_pcm_headroom_linear_speech_and_extreme_peaks() -> None:
    audio = np.array([-100.0, -4.0, -3.0, -1.0, -0.001, 0.0, 0.001, 1.0, 3.0, 4.0, 100.0])
    pcm = pcm16(audio)
    assert np.max(np.abs(pcm.astype(int))) < 32767
    np.testing.assert_array_equal(pcm[2:9], (audio[2:9] * 0.25 * 32767).astype("<i2"))
    assert np.all(np.diff(pcm.astype(int)) >= 0)
    assert pcm[4] == -pcm[6]  # Quiet noise is not raised to full scale.


def test_rotation_preserves_every_sample_timestamp_and_single_playback(tmp_path: Path) -> None:
    settings = audio_settings()
    settings.audio.max_recording_seconds = 10
    started = datetime(2026, 10, 14, 12, tzinfo=UTC)
    samples = np.sin(np.arange(16000 * 31) * 0.19) * 0.2
    app = create_app(settings, tmp_path, autostart=False)
    with TestClient(app) as client:
        conversation = Conversation(
            settings, app.state.engine.archive, settings.windows[0], 145000000, 20, started
        )
        for start in range(0, len(samples), 320):
            conversation.consume([(samples[start : start + 320], True)])
        assert not conversation.done and conversation.part_number == 4
        conversation.finish("silence")
        parts = app.state.store.session_parts(conversation.session_id)
        expected = pcm16(samples[640:]).tobytes()  # Explicit 40 ms FIR warm-up only.
        result = bytearray()
        offset = 0
        for i, part in enumerate(parts):
            assert part["part_number"] == i + 1
            assert part["sample_offset"] == offset
            assert (
                part["start_utc"]
                == (started + timedelta(seconds=(640 + offset) / 16000)).isoformat()
            )
            with wave.open(str(app.state.engine.archive.path(part["id"]))) as wav:
                result.extend(wav.readframes(wav.getnframes()))
                offset += wav.getnframes()
            assert part["limited_fraction"] == 0
        assert bytes(result) == expected
        rows = client.get("/api/conversations").json()
        assert len(rows) == 1 and rows[0]["part_count"] == 4
        assert rows[0]["duration_seconds"] == pytest.approx(len(expected) / 32000)
        assert len(client.get("/api/recordings").json()) == 4
        response = client.get(f"/api/conversations/{conversation.session_id}/audio")
        assert response.status_code == 200
        assert int(response.headers["content-length"]) == len(response.content)
        with wave.open(io.BytesIO(response.content)) as wav:
            assert wav.readframes(wav.getnframes()) == expected
        assert len(client.get("/api/conversations?q=145.0").json()) == 1
        assert client.get("/api/conversations?q=unknown").json() == []
        assert client.get("/api/conversations?offset=1").json() == []
        assert client.get("/api/conversations?since=2026-10-15T00:00:00Z").json() == []


def test_retention_protects_vad_misses_and_releases_stuck_carrier(tmp_path: Path) -> None:
    settings = audio_settings()
    settings.audio.hang_ms = 6000
    settings.audio.carrier_grace_ms = 10000
    store = Store(tmp_path / "test.sqlite3", 1000)
    try:
        archive = Archive(settings, store)
        conv = Conversation(settings, archive, settings.windows[0], 145000000, 20)
        frame = np.ones(320) * 0.1
        conv.consume([(frame, True)] * 10)
        # Strict acquisition gate misses an entire 12 s utterance, relaxed gate retains it.
        conv.consume([(frame, False)] * 600, retention=[True] * 600, rf_active=[True] * 600)
        assert not conv.done and conv.state == "RECORD"
        conv.consume([(frame, False)] * 250, rf_active=[False] * 250)
        assert not conv.done and conv.state == "HANG"  # Five-second reply gap.
        conv.consume([(frame, True)] * 10, rf_active=[True] * 10)
        conv.consume([(frame, False)] * 350, rf_active=[True] * 350)
        assert not conv.done  # RF protects seven seconds of missed VAD votes.
        conv.consume([(frame, False)] * 150, rf_active=[True] * 150)
        assert conv.done and conv.end_reason == "sustained_non_speech"
    finally:
        store.close()


def test_quota_at_rotation_finalizes_as_interrupted_without_deletion(tmp_path: Path) -> None:
    settings = audio_settings()
    settings.audio.max_recording_seconds = 10
    store = Store(tmp_path / "test.sqlite3", 1000)
    try:
        archive = Archive(settings, store)
        conv = Conversation(settings, archive, settings.windows[0], 145000000, 20)
        frame = np.ones(320) * 0.1
        conv.consume([(frame, True)] * 502)
        assert conv.writer.samples == 160000
        archive.used_bytes = settings.audio.max_archive_mb * 1024**2
        with pytest.raises(RuntimeError, match="quota"):
            conv.consume([(frame, True)])
        conv.finish("capture_or_storage_error", interrupted=True)
        rows = store.conversations()
        assert len(rows) == 1 and rows[0]["discontinuity"] and rows[0]["status"] == "interrupted"
        assert archive.path(rows[0]["id"]).exists()
    finally:
        store.close()


def test_legacy_archive_and_live_parts_are_safe_playback_snapshots(tmp_path: Path) -> None:
    app = create_app(audio_settings(), tmp_path, autostart=False)
    with TestClient(app) as client:
        archive = app.state.engine.archive
        writer = RecordingWriter(archive, audio_settings().windows[0], 145000000, np.ones(320), 20)
        path = f"/api/conversations/{writer.recording_id}/audio"
        assert client.get(path).status_code == 404  # Do not serve mutable partial WAVs.
        row = writer.finish("test")
        del row["session_id"]
        del row["part_number"]
        app.state.store.save_recording(row)
        assert client.get(path).status_code == 200
        assert client.get("/api/conversations").json()[0]["id"] == row["id"]
        assert client.get("/api/conversations/nonexistent/audio").status_code == 404


def test_only_rx_transport_errors_retry_with_a_bound(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    from radiomind.engine import Engine

    settings = audio_settings().model_copy(update={"source": "hackrf"})
    store = Store(tmp_path / "test.sqlite3", 1000)
    engine = Engine(settings, store)
    waits = []
    attempts = []

    async def no_wait(seconds):
        waits.append(seconds)

    async def transport_failure():
        attempts.append(1)
        engine.error = "HackRF RX timeout: fixture"
        engine.running = False

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    monkeypatch.setattr(engine, "_capture", transport_failure)
    try:
        asyncio.run(engine._run())
        assert len(attempts) == 4 and waits == [1, 2, 4]
        assert not engine.running and engine.reconnect_attempts == 3

        async def stop_usb_failure():
            attempts.append(1)
            engine.error = "HackRF stop RX failed (libhackrf code -1000)"

        monkeypatch.setattr(engine, "_capture", stop_usb_failure)
        attempts.clear()
        waits.clear()
        asyncio.run(engine._run())
        assert len(attempts) == 4 and waits == [1, 2, 4]

        async def storage_failure():
            attempts.append(1)
            engine.error = "Archive quota reached; fixture"

        monkeypatch.setattr(engine, "_capture", storage_failure)
        attempts.clear()
        waits.clear()
        asyncio.run(engine._run())
        assert len(attempts) == 1 and waits == []
    finally:
        store.close()
