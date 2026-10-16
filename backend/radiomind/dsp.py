from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from radiomind.config import Window
from radiomind.radio import IQ


@dataclass
class Spectrum:
    frequencies: NDArray[np.float64]
    power: NDArray[np.float64]
    noise_floor: float
    clipped_fraction: float


def compute_psd(iq: IQ, window: Window, fft_size: int) -> Spectrum:
    """Two-sided Welch density: integral equals relative complex-signal power."""
    if len(iq) < fft_size or not np.isfinite(iq).all():
        raise ValueError("Need at least one finite FFT frame")
    frames = iq[: len(iq) // fft_size * fft_size].reshape(-1, fft_size)
    # Direct-conversion receivers have a DC offset. Remove it per FFT block;
    # this also creates an explicit narrow blind spot exactly at the LO frequency.
    frames = frames - frames.mean(axis=1, keepdims=True)
    taper = np.hanning(fft_size)
    fft = np.fft.fftshift(np.fft.fft(frames * taper, axis=1), axes=1)
    density = np.mean(np.abs(fft) ** 2, axis=0) / (window.sample_rate_sps * np.sum(taper**2))
    frequencies = (
        np.fft.fftshift(np.fft.fftfreq(fft_size, 1 / window.sample_rate_sps)) + window.center_hz
    )
    mask = (frequencies >= window.start_hz) & (frequencies < window.end_hz)
    power = 10 * np.log10(np.maximum(density[mask], 1e-20))
    return Spectrum(
        frequencies[mask],
        power,
        float(np.median(power)),
        float(np.mean((np.abs(iq.real) >= 0.99) | (np.abs(iq.imag) >= 0.99))),
    )


class Detector:
    """Per-bin persistence/hysteresis; group adjacent bins into activity regions."""

    def __init__(self, on_db: float = 12, off_db: float = 7, persistence: int = 3) -> None:
        self.on_db, self.off_db, self.persistence = on_db, off_db, persistence
        self.counts: NDArray[np.int64] = np.zeros(0, dtype=np.int64)
        self.active: NDArray[np.bool_] = np.zeros(0, dtype=bool)
        self.noise: float | None = None

    def update(self, spectrum: Spectrum) -> list[dict[str, float]]:
        if len(self.counts) != len(spectrum.power):
            self.counts = np.zeros(len(spectrum.power), dtype=int)
            self.active = np.zeros(len(spectrum.power), dtype=bool)
            self.noise = None
        self.noise = (
            spectrum.noise_floor
            if self.noise is None
            else 0.8 * self.noise + 0.2 * spectrum.noise_floor
        )
        snr = spectrum.power - self.noise
        candidate = snr >= np.where(self.active, self.off_db, self.on_db)
        self.counts = np.where(candidate, np.minimum(self.counts + 1, self.persistence), 0)
        self.active = candidate & (self.active | (self.counts >= self.persistence))
        bins = np.flatnonzero(self.active)
        if not len(bins):
            return []
        groups = np.split(bins, np.where(np.diff(bins) > 1)[0] + 1)
        results = []
        for group in groups:
            peak = group[np.argmax(spectrum.power[group])]
            weights = np.maximum(10 ** ((spectrum.power[group] - self.noise) / 10) - 1, 0)
            center = float(np.average(spectrum.frequencies[group], weights=weights))
            cumulative = np.cumsum(weights) / np.sum(weights)
            occupied = group[np.searchsorted(cumulative, [0.025, 0.975])]
            results.append(
                {
                    "frequency_hz": center,
                    "peak_frequency_hz": float(spectrum.frequencies[peak]),
                    "start_hz": float(spectrum.frequencies[occupied[0]]),
                    "end_hz": float(spectrum.frequencies[occupied[-1]]),
                    "snr_db": round(float(snr[peak]), 2),
                }
            )
        return results


def refine_channel(
    spectrum: Spectrum, candidate: dict[str, float], step_hz: int
) -> dict[str, float | str]:
    """Bounded centroid, not AFC or protocol recognition. No tuning during a call."""
    seed = candidate["frequency_hz"]
    peak = candidate.get("peak_frequency_hz", seed)
    original = round(peak / step_hz) * step_hz
    fallback = round(seed / step_hz) * step_hz
    if abs(fallback - original) > step_hz:
        fallback = original
    result: dict[str, float | str] = {
        "peak_hz": peak,
        "estimated_hz": seed,
        "frequency_hz": fallback,
        "correction_hz": fallback - original,
        "method": "coarse_centroid",
    }
    frequencies = spectrum.frequencies
    if len(frequencies) < 3:
        return result
    resolution = float(frequencies[1] - frequencies[0])
    result["resolution_hz"] = resolution
    # Refine only a narrow isolated region; a broad/multiple-channel region
    # cannot be safely collapsed into a single conversation frequency.
    if candidate.get("end_hz", seed) - candidate.get("start_hz", seed) > 16000:
        result.update(frequency_hz=original, correction_hz=0, method="broad_peak_fallback")
        return result
    half = 6250.0
    if seed - half < frequencies[0] or seed + half > frequencies[-1]:
        result.update(frequency_hz=original, correction_hz=0, method="edge_peak_fallback")
        return result
    mask = np.abs(frequencies - seed) <= half
    power = np.maximum(10 ** ((spectrum.power[mask] - spectrum.noise_floor) / 10) - 1, 0)
    # Keep only bins at least 6 dB above the noise estimate. Low-SNR estimates
    # keep the coarse result; no noise-only movement to a different channel.
    power = np.where(power >= 3, power, 0)
    if not np.any(power):
        return result
    if (power[0] + power[-1]) / np.sum(power) > 0.25:
        result.update(frequency_hz=original, correction_hz=0, method="ambiguous_peak_fallback")
        return result
    center = float(np.average(frequencies[mask], weights=power))
    selected = round(center / step_hz) * step_hz
    if abs(selected - original) > step_hz:
        result.update(frequency_hz=original, correction_hz=0, method="displacement_peak_fallback")
        return result
    result.update(
        frequency_hz=selected,
        estimated_hz=round(center, 1),
        correction_hz=selected - original,
        method="fine_centroid",
    )
    return result
