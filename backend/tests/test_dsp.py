import numpy as np
import pytest

from radiomind.config import Window
from radiomind.dsp import Detector, Spectrum, compute_psd

WINDOW = Window(name="test", start_hz=140_000_000, end_hz=148_000_000)


@pytest.mark.parametrize("offset", [-1_000_000, 500_000])
def test_tone_frequency_and_power(offset: int) -> None:
    n = 2048
    t = np.arange(n * 8) / WINDOW.sample_rate_sps
    iq = np.asarray(0.5 * np.exp(2j * np.pi * offset * t), dtype=np.complex64)
    psd = compute_psd(iq, WINDOW, n)
    assert psd.frequencies[np.argmax(psd.power)] == WINDOW.center_hz + offset
    integrated = np.sum(10 ** (psd.power / 10)) * WINDOW.sample_rate_sps / n
    assert integrated == pytest.approx(0.25, rel=0.001)


def test_seeded_noise_does_not_persist() -> None:
    rng = np.random.default_rng(4)
    detector = Detector()
    for _ in range(60):
        iq = np.asarray(
            0.02 * (rng.normal(size=16384) + 1j * rng.normal(size=16384)), dtype=np.complex64
        )
        assert detector.update(compute_psd(iq, WINDOW, 2048)) == []


def test_receiver_dc_offset_does_not_become_a_signal() -> None:
    rng = np.random.default_rng(19)
    detector = Detector()
    for _ in range(8):
        iq = np.asarray(
            0.6 + 0.3j + 0.01 * (rng.normal(size=16384) + 1j * rng.normal(size=16384)),
            dtype=np.complex64,
        )
        assert detector.update(compute_psd(iq, WINDOW, 2048)) == []


def test_hysteresis_and_minimum_persistence() -> None:
    detector = Detector(persistence=3)
    frequencies = np.arange(5, dtype=np.float64)

    def frame(peak: float) -> Spectrum:
        return Spectrum(frequencies, np.array([-100.0, -100.0, peak, -100.0, -100.0]), -100, 0)

    assert not detector.update(frame(-80))
    assert not detector.update(frame(-80))
    assert len(detector.update(frame(-80))) == 1
    assert len(detector.update(frame(-91))) == 1
    assert not detector.update(frame(-95))
    assert not detector.update(frame(-80))


def test_adjacent_bins_grouped_and_invalid_samples_rejected() -> None:
    detector = Detector(persistence=1)
    result = detector.update(
        Spectrum(
            np.arange(6, dtype=np.float64),
            np.array([-100.0, -80.0, -75.0, -100.0, -70.0, -100.0]),
            -100,
            0,
        )
    )
    assert [event["peak_frequency_hz"] for event in result] == [2, 4]
    assert 1 < result[0]["frequency_hz"] < 2
    with pytest.raises(ValueError):
        compute_psd(np.array([np.nan] * 2048, dtype=np.complex64), WINDOW, 2048)
