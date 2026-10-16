import numpy as np
import pytest
from test_digital import conversation
from test_dsp import WINDOW

from radiomind.dsp import Detector, Spectrum, compute_psd, refine_channel


@pytest.mark.parametrize("blocked_by", ["blacklist", "scan_range", "window_edge"])
def test_engine_rechecks_refined_frequency_before_continuous_capture(
    tmp_path, monkeypatch, blocked_by
):
    import asyncio

    from test_audio import audio_settings

    import radiomind.engine as module
    from radiomind.config import ScanRange
    from radiomind.radio import MockSource
    from radiomind.storage import Store

    settings = audio_settings()
    settings.scan_ranges = [ScanRange(start_hz=144000000, end_hz=146000000)]
    store = Store(tmp_path / "engine.sqlite3", 1000)
    engine = module.Engine(settings, store)
    target = {"blacklist": 145006250, "scan_range": 146000000, "window_edge": 140000000}[blocked_by]
    if blocked_by == "blacklist":
        engine.rules.change(target, "exclude")
    continuous = []

    class OnePreview(MockSource):
        def read(self, samples):
            engine.stop_requested = True
            return super().read(samples)

        def set_continuous(self, enabled):
            continuous.append(enabled)

    monkeypatch.setattr(module, "MockSource", OnePreview)
    monkeypatch.setattr(
        module.Detector, "update", lambda *_: [{"frequency_hz": 145000000.0, "snr_db": 20.0}]
    )
    monkeypatch.setattr(module, "refine_channel", lambda *_: {"frequency_hz": target})
    try:
        asyncio.run(engine._capture())
        assert engine.error is None
        assert engine.frames == 1
        assert not continuous
        assert not store.recordings()
    finally:
        store.close()


def acquire(iq, nominal):
    candidates = Detector(persistence=1).update(compute_psd(iq, WINDOW, 2048))
    candidate = min(candidates, key=lambda c: abs(c["frequency_hz"] - nominal))
    return candidate, refine_channel(compute_psd(iq, WINDOW, 8192), candidate, 6250)


@pytest.mark.parametrize("grid", range(16))
@pytest.mark.parametrize("offset", [-600, 0, 600])
def test_noisy_fm_center_across_fft_bins(grid, offset):
    nominal = 145000000 + grid * 6250
    t = np.arange(16384) / 8_000_000
    rng = np.random.default_rng(4)
    # Narrow FM voice-band tone, shifted oscillator and broadband receiver noise.
    iq = 0.5 * np.exp(
        2j * np.pi * (nominal + offset - WINDOW.center_hz) * t + 2.4j * np.sin(2 * np.pi * 1000 * t)
    )
    iq += 0.01 * (rng.normal(size=len(t)) + 1j * rng.normal(size=len(t)))
    _, estimate = acquire(iq.astype(np.complex64), nominal)
    assert estimate["frequency_hz"] == nominal


def test_suppressed_carrier_sideband_no_longer_selects_next_grid_channel():
    nominal = 145000000
    t = np.arange(16384) / 8_000_000
    rng = np.random.default_rng(2)
    # Wider FM is a deliberate acquisition stress case, not NFM voice acceptance.
    iq = 0.5 * np.exp(
        2j * np.pi * (nominal - WINDOW.center_hz) * t + 2.4j * np.sin(2 * np.pi * 2500 * t)
    )
    iq += 0.01 * (rng.normal(size=len(t)) + 1j * rng.normal(size=len(t)))
    candidate, estimate = acquire(iq.astype(np.complex64), nominal)
    assert round(candidate["peak_frequency_hz"] / 6250) * 6250 == nominal + 6250
    assert estimate["frequency_hz"] == nominal
    assert estimate["correction_hz"] == -6250


@pytest.mark.parametrize("offset", [-500, 0, 500])
def test_four_level_fsk_center_with_noise(offset):
    nominal = 145018750
    t = np.arange(16384) / 8_000_000
    symbols = np.resize([-2700.0, -900.0, 900.0, 2700.0], 100)
    frequency = symbols[(t * 4800).astype(int)]
    iq = 0.5 * np.exp(
        2j * np.pi * ((nominal + offset - WINDOW.center_hz) * t + np.cumsum(frequency) / 8_000_000)
    )
    rng = np.random.default_rng(15)
    iq += 0.01 * (rng.normal(size=len(t)) + 1j * rng.normal(size=len(t)))
    _, estimate = acquire(iq.astype(np.complex64), nominal)
    assert estimate["frequency_hz"] == nominal


def test_refinement_does_not_pull_toward_stronger_adjacent_channel():
    t = np.arange(16384) / 8_000_000
    nominal = 145000000
    iq = 0.2 * np.exp(2j * np.pi * 1_000_000 * t)
    iq += 0.6 * np.exp(2j * np.pi * 1_012_500 * t)
    fine = compute_psd(iq.astype(np.complex64), WINDOW, 8192)
    candidate = {"frequency_hz": nominal, "peak_frequency_hz": nominal}
    assert refine_channel(fine, candidate, 6250)["frequency_hz"] == nominal
    candidate.update(start_hz=nominal - 12500, end_hz=nominal + 12500)
    assert refine_channel(fine, candidate, 6250)["method"] == "broad_peak_fallback"


def test_edge_and_noise_cannot_move_peak_to_unobserved_channel():
    f = np.arange(140000000, 140030000, 1000, dtype=float)
    s = Spectrum(f, np.full(len(f), -100.0), -100.0, 0.0)
    c = {"frequency_hz": 140001000.0, "peak_frequency_hz": 140001000.0}
    assert refine_channel(s, c, 6250)["method"] == "edge_peak_fallback"
    c.update(frequency_hz=140015000.0, peak_frequency_hz=140015000.0)
    assert refine_channel(s, c, 6250)["method"] == "coarse_centroid"


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("absent", "rf_not_confirmed"),
        ("gone", "rf_disappeared"),
        ("active", "no_digital_sync"),
        ("bad_frames", "frame_errors_observed"),
        ("single_sync", "insufficient_sync"),
        ("error", "decoder_error"),
    ],
)
def test_attempt_explains_measured_rejection_and_keeps_acquisition(
    tmp_path, monkeypatch, kind, expected
):
    conv, store = conversation(tmp_path, monkeypatch)
    conv.evidence_samples = 16000
    if kind != "absent":
        conv.rf_samples = conv.last_rf_sample = 16000 if kind != "gone" else 3200
    if kind == "bad_frames":
        conv.digital.metadata["invalid_counts"] = {"DMR": 2}
    if kind == "single_sync":
        conv.digital.metadata["sync_counts"] = {"DMR": 1}
    if kind == "error":
        conv.digital.metadata["error"] = "pipe failed"
    conv.acquisition = {"correction_hz": -6250, "method": "fine_centroid"}
    try:
        conv.finish("speech_not_confirmed")
        row = store.digital_attempts()[0]
        assert row["diagnostic_reason"] == expected
        assert row["signal_evidence"]["observed_ms"] == 1000
        assert row["acquisition"]["correction_hz"] == -6250
        assert not store.recordings()
    finally:
        store.close()
