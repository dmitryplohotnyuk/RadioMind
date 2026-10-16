import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
from scipy import signal
from test_audio import audio_settings

from radiomind.engine import Engine, read_decode
from radiomind.nfm import Decimator
from radiomind.storage import Store


def test_single_handoff_preserves_input_frames_and_propagates_capture_loss():
    iq = np.array([1 + 2j, 3 + 4j], dtype=np.complex64)
    frames = [(np.ones(320), True)]
    calls = []

    def read():
        calls.append("read")
        return iq

    def decode(samples, noise):
        assert samples is iq and noise == 0.25
        calls.append("decode")
        return frames

    source = SimpleNamespace(read_full=read)
    result = read_decode(source, SimpleNamespace(decode=decode), 0.25)
    assert result[0] is iq and result[1] is frames
    assert calls == ["read", "decode"]
    assert result[2] >= 0 and result[3] >= 0

    def failed_read():
        raise RuntimeError("Continuous IQ buffer overflow; audio has a gap")

    source.read_full = failed_read
    with pytest.raises(RuntimeError, match="buffer overflow"):
        read_decode(source, SimpleNamespace(decode=decode), 0.25)
    assert calls == ["read", "decode"]


def test_processing_evidence_is_bounded_and_captures_error_snapshot(tmp_path, monkeypatch):
    store = Store(tmp_path / "mock.sqlite3", 1000)
    engine = Engine(audio_settings(), store)
    try:
        for _ in range(1000):
            engine.measure("decode", 10.0)
        assert len(engine.processing) == 1
        assert engine.status()["processing"]["stages"]["decode"] == {
            "count": 1000,
            "mean_ms": 10.0,
            "max_ms": 10.0,
        }
        engine.capture_metrics(
            SimpleNamespace(
                metrics=lambda: {
                    "preview_only": False,
                    "queued_blocks": 128,
                    "application_dropped_samples": 131072,
                }
            )
        )
        assert engine.status()["processing"]["capture_queue_peak"] == 128
        assert engine.source_metrics["application_dropped_samples"] == 131072

        async def fail():
            engine.error = "Continuous IQ buffer overflow; audio has a gap"

        monkeypatch.setattr(engine, "_capture", fail)
        asyncio.run(engine._run())
        assert engine.error and not engine.running
        assert engine.reconnect_attempts == 0  # No silent overflow/restart/merge.
    finally:
        store.close()


@pytest.mark.parametrize("taps,factor", [(241, 20), (401, 5), (1, 3)])
def test_retained_complex_fir_outputs_match_reference_across_irregular_chunks(taps, factor):
    rng = np.random.default_rng(180)
    x = (rng.normal(size=131077) + 1j * rng.normal(size=131077)).astype(np.complex64)
    coefficients = signal.firwin(taps, 0.03).astype(np.float32)
    reference = signal.lfilter(coefficients, [1], x)[::factor]
    decoder = Decimator(coefficients, factor)
    boundaries = [0, 1, 2, 17, 241, 1001, 32001, len(x)]
    output = np.concatenate(
        [decoder.process(x[a:b]) for a, b in zip(boundaries[:-1], boundaries[1:], strict=True)]
    )
    assert output.dtype == np.complex64
    assert len(output) == len(reference)
    np.testing.assert_allclose(output, reference, atol=2e-6, rtol=2e-5)
    assert decoder.process(np.empty(0, dtype=x.dtype)).size == 0


def test_display_work_yields_to_capture_backlog_and_resumes(tmp_path):
    store = Store(tmp_path / "mock.sqlite3", 1000)
    engine = Engine(audio_settings(), store)
    try:
        engine.conversation = SimpleNamespace()
        engine.source_metrics = {"queued_blocks": 16}
        assert not engine.preview_due(1, 0, 131072)
        assert engine.deferred_previews == 1
        engine.source_metrics = {"queued_blocks": 15}
        assert engine.preview_due(1, 0, 131072)
        assert not engine.preview_due(0.01, 0, 131072)
        engine.conversation = None
        engine.source_metrics = {"queued_blocks": 128}
        assert engine.preview_due(1, 0, 131072)  # Scan detection is never deferred.
        assert not engine.preview_due(1, 0, 1)
    finally:
        store.close()
