import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import signal

from radiomind.api import create_app
from radiomind.channel_rules import ChannelRules
from radiomind.config import AudioSettings, Settings, Window
from radiomind.conversation import Conversation
from radiomind.nfm import Decimator, NFMDemodulator
from radiomind.policy import require_audio
from radiomind.recording import Archive, RecordingWriter
from radiomind.speech import SpeechGate
from radiomind.storage import Store


def audio_settings() -> Settings:
    return Settings(
        country="UA",
        legal_basis="authorized synthetic test",
        windows=[
            Window(
                name="test",
                start_hz=140_000_000,
                end_hz=148_000_000,
                allowed_actions=["observe", "demodulate", "record_audio"],
            )
        ],
        audio=AudioSettings(
            enabled=True, hang_ms=400, verify_ms=600, pre_roll_ms=200, cooldown_seconds=10
        ),
    )


def test_owner_rejected_digital_candidates_cool_down_and_retry(tmp_path):
    settings = audio_settings()
    store = Store(tmp_path / "rules.sqlite3", 1000)
    rules = ChannelRules(settings, store)
    frequency = 145000000
    store.db.execute("INSERT INTO digital_rejections VALUES(?,?)", (frequency, "DMR"))
    store.db.commit()
    for i in range(settings.audio.cooldown_failures):
        rules.outcome(frequency, True, 100 + i, protocol="DMR")
    row = store.channel(frequency)
    assert row["reason"] == "owner_rejected_digital" and not row["manual"]
    assert not rules.eligible(frequency, row["expires"] - 1)
    assert rules.eligible(frequency, row["expires"] + 1)
    # A different successful mode is not rejected and resets the cooldown.
    rules.outcome(frequency, True, 200, protocol="M17")
    assert store.channel(frequency)["failures"] == 0
    rules.change(frequency, "priority")
    for i in range(10):
        rules.outcome(frequency, True, 300 + i, protocol="DMR")
    assert rules.eligible(frequency, 320)
    store.close()


def test_polyphase_decimation_preserves_chunk_phase() -> None:
    rng = np.random.default_rng(5)
    x = rng.normal(size=4077) + 1j * rng.normal(size=4077)
    taps = signal.firwin(81, 0.04)
    reference = signal.lfilter(taps, [1], x)[::20]
    decoder = Decimator(taps, 20)
    pieces = [decoder.process(x[a:b]) for a, b in [(0, 17), (17, 163), (163, 1824), (1824, 4077)]]
    np.testing.assert_allclose(np.concatenate(pieces), reference, atol=1e-12)


@pytest.mark.parametrize("up,down,tap_count", [(1, 20, 81), (3, 25, 501), (3, 5, 151)])
@pytest.mark.parametrize("complex_input", [False, True])
def test_polyphase_interpolation_matches_explicit_zeros(up, down, tap_count, complex_input):
    rng = np.random.default_rng(44)
    x = rng.normal(size=4077)
    if complex_input:
        x = x + 1j * rng.normal(size=len(x))
    taps = up * signal.firwin(tap_count, 0.04)
    expanded = np.zeros(len(x) * up, dtype=x.dtype)
    expanded[::up] = x
    reference = signal.lfilter(taps, [1], expanded)[::down]
    decoder = Decimator(taps, down, up=up)
    boundaries = [0, 1, 17, 163, 1824, len(x)]
    pieces = [decoder.process(x[a:b]) for a, b in zip(boundaries[:-1], boundaries[1:], strict=True)]
    result = np.concatenate(pieces)
    assert np.iscomplexobj(result) == complex_input
    assert len(result) == len(reference)
    np.testing.assert_allclose(result, reference, atol=1e-12)


def test_nfm_streaming_matches_whole_and_recovers_modulation() -> None:
    rate = 8_000_000
    t = np.arange(1_600_000) / rate
    tone = 0.3 * np.sin(2 * np.pi * 1000 * t)
    iq = np.asarray(
        0.5 * np.exp(2j * np.pi * (125_000 * t + 2500 * np.cumsum(tone) / rate)), dtype=np.complex64
    )
    whole = NFMDemodulator(125_000).process(iq)
    decoder = NFMDemodulator(125_000)
    streamed = np.concatenate(
        [decoder.process(iq[a : a + 131072]) for a in range(0, len(iq), 131072)]
    )
    np.testing.assert_allclose(streamed, whole, atol=2e-5)
    useful = streamed[800:]
    frequencies, psd = signal.periodogram(useful, fs=16000)
    assert abs(frequencies[np.argmax(psd)] - 1000) < 10
    assert np.sqrt(np.mean(useful**2)) > 0.15


@pytest.mark.parametrize("kind", ["silence", "tone", "noise", "band_noise", "multitone"])
def test_speech_gate_rejects_stationary_non_speech(kind: str) -> None:
    rng = np.random.default_rng(48)
    t = np.arange(32000) / 16000
    audio = {
        "silence": np.zeros_like(t),
        "tone": 0.2 * np.sin(2 * np.pi * 1000 * t),
        "noise": rng.normal(0, 0.05, len(t)),
        "multitone": sum(0.025 * np.sin(2 * np.pi * f * t) for f in range(400, 3000, 200)),
        "band_noise": signal.sosfilt(
            signal.butter(3, [300, 3400], btype="bandpass", fs=16000, output="sos"),
            rng.normal(0, 0.06, len(t)),
        ),
    }[kind]
    assert not any(voiced for _, voiced in SpeechGate().process(audio))


def test_local_tts_speech_fixture_when_available() -> None:
    fixture = Path(__file__).resolve().parents[2] / "runtime/fixtures/speech.wav"
    if not fixture.exists():
        pytest.skip("Windows-generated synthetic speech fixture not present")
    with wave.open(str(fixture)) as wav:
        assert wav.getframerate() == 16000 and wav.getnchannels() == 1
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(float) / 32768
    votes = [voiced for _, voiced in SpeechGate().process(samples)]
    assert sum(votes) > len(votes) * 0.2
    assert not any(v for _, v in SpeechGate().process(samples, rf_ok=False))


def test_recording_permission_bandwidth_quota_and_valid_wav(tmp_path: Path) -> None:
    settings = audio_settings()
    window = settings.windows[0]
    with pytest.raises(PermissionError):
        require_audio(Settings(), window, 145_000_000)
    with pytest.raises(PermissionError):
        require_audio(settings, window, window.start_hz + 100)
    with pytest.raises(PermissionError):
        require_audio(
            settings, window.model_copy(update={"allowed_actions": ["observe"]}), 145_000_000
        )
    store = Store(tmp_path / "test.sqlite3", 1000)
    archive = Archive(settings, store)
    writer = RecordingWriter(archive, window, 145_000_000, np.zeros(3200), 20)
    writer.write(np.zeros(1600))
    row = writer.finish("test")
    with wave.open(str(archive.path(row["id"]))) as wav:
        assert wav.getnframes() == 4800 and wav.getframerate() == 16000
    assert row["duration_seconds"] == 0.3
    with pytest.raises(ValueError):
        archive.path("../outside")
    archive.used_bytes = settings.audio.max_archive_mb * 1024**2
    with pytest.raises(RuntimeError, match="quota"):
        RecordingWriter(archive, window, 145_000_000, np.zeros(100), 20)
    assert len(store.recordings()) == 1
    store.close()


def test_conversation_preroll_pause_hang_and_end(tmp_path: Path) -> None:
    settings = audio_settings()
    store = Store(tmp_path / "test.sqlite3", 1000)
    archive = Archive(settings, store)
    conversation = Conversation(settings, archive, settings.windows[0], 145_000_000, 20)
    frame = np.ones(320) * 0.1
    conversation.consume([(frame, False)] * 10 + [(frame, True)] * 10)
    assert conversation.state == "RECORD"
    conversation.consume([(frame, False)] * 10)
    assert conversation.state == "HANG" and not conversation.done
    conversation.consume([(frame, True)] * 2 + [(frame, False)] * 20)
    assert conversation.done and conversation.end_reason == "silence"
    row = store.recordings()[0]
    assert row["status"] == "ready" and row["duration_seconds"] > 0.8
    rejected = Conversation(settings, archive, settings.windows[0], 146_000_000, 20)
    rejected.consume([(frame, False)] * 40)
    assert rejected.done and rejected.writer is None
    assert len(store.recordings()) == 1
    store.close()


def test_cooldown_expiry_manual_and_priority_survive_restart(tmp_path: Path) -> None:
    settings = audio_settings()
    store = Store(tmp_path / "test.sqlite3", 1000)
    rules = ChannelRules(settings, store)
    frequency = 145_000_000
    for now in [0, 10, 20]:
        rules.outcome(frequency, False, now)
    assert not rules.eligible(frequency, 26)
    assert rules.eligible(frequency, 31)
    rules.change(frequency, "priority")
    rules.outcome(frequency, False, 40)
    assert rules.eligible(frequency, 46)
    rules.change(frequency, "exclude")
    assert not ChannelRules(settings, store).eligible(frequency, 10000)
    rules.change(frequency, "restore")
    assert rules.eligible(frequency, 10000)
    rules.outcome(frequency, True, 10000)
    assert store.channel(frequency)["failures"] == 0
    with pytest.raises(ValueError):
        rules.change(10_000_000, "exclude")
    store.close()


def test_archive_open_player_and_rules(tmp_path: Path) -> None:
    app = create_app(audio_settings(), tmp_path, autostart=False)
    with TestClient(app) as client:
        archive = app.state.engine.archive
        writer = RecordingWriter(
            archive, app.state.engine.settings.windows[0], 145_000_000, np.zeros(320), 20
        )
        row = writer.finish("test", interrupted=True)
        path = f"/api/recordings/{row['id']}/audio"
        assert client.get(path).status_code == 200
        response = client.get(path)
        assert response.status_code == 200 and response.content.startswith(b"RIFF")
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/recordings").json()[0]["discontinuity"]
        assert client.get("/api/recordings/not-a-uuid/audio").status_code == 404
        assert (
            client.post(
                "/api/channels", json={"frequency_hz": 145000000, "action": "exclude"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/channels", json={"frequency_hz": 145000000, "action": "exclude"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/channels", json={"frequency_hz": 1000000, "action": "exclude"}
            ).status_code
            == 422
        )


def test_archive_recovers_unfinished_header_and_preserves_title(tmp_path: Path) -> None:
    settings = audio_settings()
    store = Store(tmp_path / "test.sqlite3", 1000)
    archive = Archive(settings, store)
    writer = RecordingWriter(archive, settings.windows[0], 145_000_000, np.zeros(3200), 20)
    row = store.recording(writer.recording_id)
    assert row is not None
    row["title"] = "Проверка начала"
    store.save_recording(row)
    writer.finish("test")
    assert store.recording(writer.recording_id)["title"] == "Проверка начала"
    unfinished = RecordingWriter(archive, settings.windows[0], 145_000_000, np.zeros(3200), 20)
    unfinished.file.close()
    recovered = Archive(settings, store)
    row = store.recording(unfinished.recording_id)
    assert row["status"] == "interrupted" and row["playable"]
    with wave.open(str(recovered.path(unfinished.recording_id))) as wav:
        assert wav.getnframes() == 3200
    store.close()


def test_archive_search_dates_pagination_and_channel_rounding(tmp_path: Path) -> None:
    app = create_app(audio_settings(), tmp_path, autostart=False)
    with TestClient(app) as client:
        for i, (title, stamp) in enumerate(
            [("Разговор", "2026-10-13T23:30:00+00:00"), ("Другой", "2026-10-14T22:30:00+00:00")]
        ):
            app.state.store.save_recording(
                {
                    "id": str(i),
                    "title": title,
                    "frequency_hz": 145500000,
                    "start_utc": stamp,
                    "status": "ready",
                }
            )
        assert len(client.get("/api/recordings?q=РАЗГОВОР").json()) == 1
        assert len(client.get("/api/recordings?q=145.5").json()) == 2
        assert len(client.get("/api/recordings?limit=1&offset=1").json()) == 1
        params = {"since": "2026-10-14T00:00:00+03:00", "until": "2026-10-15T00:00:00+03:00"}
        assert client.get("/api/recordings", params=params).json()[0]["title"] == "Разговор"
        response = client.post(
            "/api/channels", json={"frequency_hz": 145500100, "action": "exclude"}
        )
        assert response.json()["frequency_hz"] == 145500000
        assert not app.state.engine.rules.eligible(145500000)


def test_owner_labels_preserve_title_and_survive_finalize(tmp_path: Path) -> None:
    app = create_app(audio_settings(), tmp_path, autostart=False)
    with TestClient(app) as client:
        writer = RecordingWriter(
            app.state.engine.archive, audio_settings().windows[0], 145000000, np.zeros(320), 20
        )
        path = f"/api/recordings/{writer.recording_id}/review"
        assert client.post(path, json={"title": "Owner title"}).status_code == 200
        response = client.post(path, json={"label": "speech"})
        assert response.json()["title"] == "Owner title"
        writer.finish("test")
        row = client.get("/api/recordings").json()[0]
        assert row["review_label"] == "speech" and row["review_source"] == "owner"
        assert client.post(path, json={"title": "New title"}).json()["review_label"] == "speech"
        assert client.post(path, json={"label": "noise"}).json()["review_label"] == "noise"
        assert (
            client.post(path, json={"label": "unreviewed"}).json()["review_label"] == "unreviewed"
        )
        assert client.post(path, json={"label": "invalid"}).status_code == 422
        assert (
            client.post(
                path, json={"label": "noise"}, headers={"Origin": "http://evil.invalid"}
            ).status_code
            == 403
        )
        assert app.state.engine.archive.path(writer.recording_id).exists()
