from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from radiomind.config import Window

IQ = NDArray[np.complex64]


class RxSource(Protocol):
    def tune(self, window: Window) -> None: ...
    def read(self, samples: int) -> IQ: ...
    def close(self) -> None: ...
    def metrics(self) -> dict[str, object]: ...
    def set_continuous(self, enabled: bool) -> None: ...
    def read_full(self) -> IQ: ...


class MockSource:
    """Reproducible complex IQ. No device access, audio, or raw IQ persistence."""

    def __init__(self, seed: int = 42) -> None:
        self.rng = np.random.default_rng(seed)
        self.window: Window | None = None
        self.position = 0
        self.frames = 0

    def tune(self, window: Window) -> None:
        self.window = window
        self.position = 0
        self.frames = 0

    def read(self, samples: int) -> IQ:
        if self.window is None:
            raise RuntimeError("Source has not been tuned")
        t = (np.arange(samples) + self.position) / self.window.sample_rate_sps
        width = self.window.end_hz - self.window.start_hz
        signal = 0.22 * np.exp(2j * np.pi * width * 0.19 * t)
        if self.frames % 24 < 16:
            signal += 0.12 * np.exp(-2j * np.pi * width * 0.27 * t)
        noise = 0.018 * (self.rng.normal(size=samples) + 1j * self.rng.normal(size=samples))
        self.position += samples
        self.frames += 1
        return np.asarray(signal + noise, dtype=np.complex64)

    def close(self) -> None:
        self.window = None

    def metrics(self) -> dict[str, object]:
        return {
            "hardware_connected": None,
            "usb_dropped_samples": None,
            "synthetic": True,
            "preview_only": True,
        }

    def set_continuous(self, enabled: bool) -> None:
        pass

    def read_full(self) -> IQ:
        return self.read(131072)
