import hashlib
import io
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_audio import audio_settings

from radiomind.api import create_app
from radiomind.cleaning import denoise, library_path, make_copy
from radiomind.config import Settings, load_settings
from radiomind.dsp import Detector, compute_psd
from radiomind.radio import MockSource
from radiomind.recording import RecordingWriter
from radiomind.scheduler import Scheduler


def test_priority_revisits_preserve_full_sweep_and_hold():
    settings = load_settings(
        Path(__file__).resolve().parents[2] / "backend/tests/fixtures/scanner.yaml"
    )
    scheduler = Scheduler(settings.windows)
    scheduler.set_priorities([154400000])
    visits = [scheduler.choose(100 + i).name for i in range(31)]
    assert visits.count("VHF 152-160") > visits.count("VHF 140-148")
    # Filter inserted visits via the scheduler's state and ensure ordinary order.
    scheduler = Scheduler(settings.windows)
    scheduler.set_priorities([154400000, 438000000])
    ordinary = []
    for i in range(40):
        w = scheduler.choose(100 + i)
        if not scheduler.on_priority:
            ordinary.append(w.name)
    assert ordinary == [settings.windows[i % 10].name for i in range(len(ordinary))]
    current = scheduler.choose(200, ready=False)
    assert scheduler.choose(999, ready=False) == current
    scheduler.mode = "watch"
    assert scheduler.choose(1000) == current


def test_fast_profile_requires_detector_time_and_three_real_frames():
    settings = Settings(scan_period_ms=50, frame_period_ms=200)
    raw = settings.model_dump()
    raw["windows"] = [
        settings.effective_windows[0].model_copy(update={"dwell_ms": 300}).model_dump()
    ]
    assert Settings.model_validate(raw).effective_scan_period_ms == 50
    raw["windows"][0]["dwell_ms"] = 150
    with pytest.raises(ValidationError):
        Settings.model_validate(raw)
    # Persistent synthetic carrier still requires 3 separate detector frames.
    source = MockSource()
    window = settings.effective_windows[0]
    source.tune(window)
    detector = Detector()
    results = [detector.update(compute_psd(source.read(16384), window, 2048)) for _ in range(3)]
    assert not results[0] and not results[1] and results[2]
    source.close()


def test_flags_survive_finalization_filter_before_pagination_and_restart(tmp_path):
    settings = audio_settings()
    app = create_app(settings, tmp_path, autostart=False)
    with TestClient(app) as client:
        writer = RecordingWriter(
            app.state.engine.archive, settings.windows[0], 145000000, np.zeros(1600), 20
        )
        path = f"/api/recordings/{writer.recording_id}/review"
        assert client.post(path, json={"favorite": True}).status_code == 200
        assert client.post(path, json={"listened": True}).status_code == 409
        writer.finish("test")
        for _ in range(3):
            other = RecordingWriter(
                app.state.engine.archive, settings.windows[0], 145100000, np.zeros(1600), 20
            )
            other.finish("test")
        assert (
            client.get("/api/conversations?view=favorites&limit=1").json()[0]["id"]
            == writer.recording_id
        )
        assert client.post(path, json={"listened": True}).status_code == 200
        assert len(client.get("/api/conversations?view=unlistened").json()) == 3
        assert client.get("/api/conversations?view=invalid").status_code == 422
    with TestClient(create_app(settings, tmp_path, autostart=False)) as client:
        row = client.get("/api/conversations?view=favorites").json()[0]
        assert row["favorite"] and row["listened"]
        assert client.post(path, json={"listened": False}).status_code == 200
        assert len(client.get("/api/conversations?view=unlistened").json()) == 4


def require_native():
    try:
        library_path()
    except RuntimeError:
        pytest.skip("Validated optional native library not installed")


def test_native_copy_preserves_original_bytes_samples_and_tail(tmp_path):
    require_native()
    fixture = Path(__file__).resolve().parents[2] / "runtime/fixtures/speech.wav"
    if not fixture.is_file():
        pytest.skip("Local synthetic TTS fixture not installed")
    before = hashlib.sha256(fixture.read_bytes()).hexdigest()
    output = tmp_path / "clean.wav"
    make_copy([fixture], output)
    with wave.open(str(fixture)) as wav:
        original = np.frombuffer(wav.readframes(wav.getnframes()), "<i2")
    with wave.open(str(output)) as wav:
        cleaned = np.frombuffer(wav.readframes(wav.getnframes()), "<i2")
        assert wav.getframerate() == 16000 and len(cleaned) == len(original)
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == before
    # Last spoken second retains energy; no truncation or shifted ending.
    active = np.flatnonzero(np.abs(original.astype(float)) > 1000)
    last = active[-1]
    assert np.std(cleaned[max(0, last - 8000) : last]) > 100
    assert denoise(np.zeros(321, dtype="<i2")).shape == (321,)
    with pytest.raises(FileExistsError):
        make_copy([fixture], output)


def test_cleanup_api_job_and_quota_reservation(tmp_path):
    require_native()
    settings = audio_settings()
    app = create_app(settings, tmp_path, autostart=False)
    with TestClient(app) as client:
        archive = app.state.engine.archive
        writer = RecordingWriter(archive, settings.windows[0], 145000000, np.zeros(1600), 20)
        sid = writer.recording_id
        url = f"/api/conversations/{sid}"
        assert client.post(url + "/clean").status_code == 409
        writer.finish("test")
        original = client.get(url + "/audio").content
        used = archive.used_bytes
        assert client.post(url + "/clean").json()["status"] == "processing"
        # Same ID does not start/reserve a second job.
        assert client.post(url + "/clean").json()["status"] in {"processing", "ready"}
        client.portal.call(app.state.cleaner.close)
        assert app.state.cleaner.status(sid) == "ready"
        assert archive.reserved_bytes == 0 and archive.used_bytes == used * 2
        cleaned = client.get(url + "/audio?variant=cleaned")
        assert cleaned.status_code == 200 and len(cleaned.content) == len(original)
        assert client.get(url + "/audio").content == original
        assert client.post(url + "/clean").json()["status"] == "ready"
        assert archive.used_bytes == used * 2
        with wave.open(io.BytesIO(cleaned.content)) as wav:
            assert wav.getnframes() == 1600
        archive.reserved_bytes = settings.audio.max_archive_mb * 1024**2
        with pytest.raises(RuntimeError, match="quota"):
            archive.reserve_check(1)


def test_failed_copy_releases_reservation_preserves_partial_and_original(tmp_path, monkeypatch):
    require_native()
    settings = audio_settings()
    app = create_app(settings, tmp_path, autostart=False)

    def failed_process(command, **kwargs):
        Path(command[3]).with_suffix(".partial.wav").write_bytes(b"retained partial")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr("radiomind.cleaning.subprocess.run", failed_process)
    with TestClient(app) as client:
        archive = app.state.engine.archive
        writer = RecordingWriter(archive, settings.windows[0], 145000000, np.zeros(1600), 20)
        writer.finish("test")
        original = archive.path(writer.recording_id).read_bytes()
        used = archive.used_bytes
        cleaner = app.state.cleaner

        async def check():
            assert cleaner.start(writer.recording_id) == "processing"
            assert archive.reserved_bytes == len(original)
            with pytest.raises(RuntimeError, match="другая"):
                cleaner.start("a" * 32)
            await cleaner.close()

        client.portal.call(check)
        assert cleaner.status(writer.recording_id) == "failed"
        assert archive.reserved_bytes == 0
        assert archive.used_bytes == used + len(b"retained partial")
        assert archive.path(writer.recording_id).read_bytes() == original
        with pytest.raises(RuntimeError, match="незавершённая"):
            cleaner.start(writer.recording_id)
