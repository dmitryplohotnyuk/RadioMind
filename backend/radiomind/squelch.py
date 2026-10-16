"""Carrier squelch for audio, independent of speech detection and reply timers."""

import numpy as np

from radiomind.nfm import Audio


class CarrierSquelch:
    def __init__(self) -> None:
        self.open = False
        self.gain = 0.0
        self.muted_samples = 0
        self.samples = 0

    def process(
        self, audio: Audio, power: Audio, noise_power: float, fm_noise: Audio | None = None
    ) -> Audio:
        if len(audio) != len(power):
            raise ValueError("Carrier power and audio must be sample aligned")
        if not len(audio):
            return audio
        if not np.isfinite(noise_power) or noise_power <= 0:
            raise ValueError("Invalid squelch noise reference")
        # Open at ~4.8 dB above estimated noise, retain to ~1.8 dB.
        # Quiet speech is not a reason to close: only channel RF power matters.
        ratio = np.maximum(power, 0) / noise_power
        hiss = np.zeros(len(audio)) if fm_noise is None else fm_noise
        if len(hiss) != len(audio):
            raise ValueError("FM noise and audio must be sample aligned")
        # A colored/interfering RF floor can remain high after PTT release.
        # Measure discriminator noise ABOVE the speech band, before audio filtering.
        decisions = np.where(
            (ratio <= 1.5) | (hiss >= 2.25),
            0,
            np.where((ratio >= 3.0) & (hiss <= 1.0), 1, -1),
        )
        indices = np.maximum.accumulate(np.where(decisions >= 0, np.arange(len(audio)), -1))
        states = np.where(indices >= 0, decisions[np.maximum(indices, 0)], int(self.open))
        boundaries = np.r_[0, np.flatnonzero(np.diff(states)) + 1, len(audio)]
        result = np.empty_like(audio)
        for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
            opened = bool(states[start])
            # 2 ms attack, 5 ms release. No dropped samples or change in timeline.
            step = 1 / 32 if opened else -1 / 80
            gains = np.clip(self.gain + step * np.arange(1, end - start + 1), 0, 1)
            result[start:end] = audio[start:end] * gains
            self.gain = float(gains[-1])
            self.muted_samples += int(np.count_nonzero(gains == 0))
        self.open = bool(states[-1])
        self.samples += len(audio)
        return result
