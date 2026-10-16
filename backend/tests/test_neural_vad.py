import wave
from pathlib import Path

import numpy as np
import pytest

from radiomind import neural_vad
from radiomind.speech import SpeechGate


def test_neural_acquisition_counts_distinct_blocks_and_keeps_retention(monkeypatch) -> None:
    class FakeSession:
        def __init__(self):
            self.calls = 0

        def run(self, _, feed):
            assert feed["input"].shape == (1, 576)
            assert feed["state"].shape == (2, 1, 128)
            self.calls += 1
            probability = 0.8 if self.calls <= 3 else 0.3
            return np.array([[probability]], dtype=np.float32), feed["state"]

    fake = FakeSession()
    monkeypatch.setattr(neural_vad, "load_session", lambda: fake)
    gate = SpeechGate("silero")
    frame = np.ones(320) * 0.1
    votes = [gate.process(frame)[0][1] for _ in range(5)]
    assert votes == [False, False, False, False, True]
    assert fake.calls == 3  # Not five repetitions of a stale probability.
    gate.process(np.tile(frame, 4))
    assert not gate.last_details["speech_candidate"]
    assert gate.retention[-1]
    assert not any(v for _, v in gate.process(frame, rf_ok=False))
    assert not gate.retention[-1]


@pytest.mark.skipif(not neural_vad.MODEL_PATH.exists(), reason="Install pinned local Silero model")
def test_actual_model_chunk_invariance_and_state_isolation() -> None:
    audio = np.random.default_rng(4).normal(0, 0.02, 32000).astype(np.float32)
    expected = neural_vad.SileroProbability().push(audio)
    streaming = neural_vad.SileroProbability()
    actual = []
    for start in range(0, len(audio), 173):
        actual.extend(streaming.push(audio[start : start + 173]))
    np.testing.assert_allclose(actual, expected, atol=1e-7)
    assert len(streaming.pending) == len(audio) % 512
    # A new conversation has no state from the preceding frequency.
    np.testing.assert_allclose(neural_vad.SileroProbability().push(audio), expected, atol=1e-7)


@pytest.mark.skipif(not neural_vad.MODEL_PATH.exists(), reason="Install pinned local Silero model")
def test_actual_silero_local_speech_and_stationary_noise() -> None:
    fixture = Path(__file__).resolve().parents[2] / "runtime/fixtures/speech.wav"
    if not fixture.exists():
        pytest.skip("Local synthesized speech fixture unavailable")
    with wave.open(str(fixture)) as wav:
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(float) / 32768
    for level in (1.0, 0.2):
        frames = SpeechGate("silero").process(audio * level)
        assert sum(v for _, v in frames) > 0.2 * len(frames)
    noise = np.random.default_rng(8).normal(0, 0.1, 32000)
    assert not any(v for _, v in SpeechGate("silero").process(noise))
    tone = 0.2 * np.sin(2 * np.pi * 1000 * np.arange(32000) / 16000)
    assert not any(v for _, v in SpeechGate("silero").process(tone))
