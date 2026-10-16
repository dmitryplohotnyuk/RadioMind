"""Bounded complex-channel level adaptation before virtual 8-bit RTL input."""

import math
from typing import Any

import numpy as np


class DigitalIQEncoder:
    def __init__(self) -> None:
        self.gain: float | None = None
        self.max_gain = 1.0
        self.blocks = 0
        self.rms = self.peak = 0.0
        self.max_rms = 0.0

    def encode(self, iq: np.ndarray[Any, Any]) -> bytes:
        if iq.ndim != 1 or len(iq) > 48000 or not np.all(np.isfinite(iq)):
            raise RuntimeError("Invalid complex digital input")
        if not len(iq):
            return b""
        components = np.column_stack((iq.real, iq.imag)).astype(np.float64)
        peak = float(np.max(np.abs(components)))
        rms = float(np.sqrt(np.mean(np.abs(iq.astype(np.complex128)) ** 2)))
        if not math.isfinite(rms):
            raise RuntimeError("Invalid complex digital input level")
        # Common positive I/Q gain preserves phase. Fast reduction protects a
        # sudden strong burst; slow increases avoid amplifying every quiet gap.
        if rms > 1e-12:
            target = min(256.0, max(1.0, 0.25 / rms), 1.0 / max(peak, 1e-12))
            if self.gain is None or target < self.gain:
                self.gain = target
            else:
                alpha = -math.expm1(-len(iq) / (48000 * 0.25))
                self.gain += alpha * (target - self.gain)
        gain = self.gain if self.gain is not None else 1.0
        self.blocks += 1
        self.rms, self.peak = rms, peak
        self.max_rms = max(self.max_rms, rms)
        self.max_gain = max(self.max_gain, gain)
        raw = np.asarray(np.clip(components * gain * 127 + 127.5, 0, 255), dtype=np.uint8)
        # Native rate conversion expects 1.536 MS/s, with phase retained.
        return np.repeat(raw, 32, axis=0).tobytes()

    def status(self) -> dict[str, float | int]:
        return {
            "blocks": self.blocks,
            "rms_dbfs": round(20 * math.log10(max(self.rms, 1e-12)), 2),
            "component_peak_dbfs": round(20 * math.log10(max(self.peak, 1e-12)), 2),
            "max_block_rms_dbfs": round(20 * math.log10(max(self.max_rms, 1e-12)), 2),
            "gain_db": round(20 * math.log10(max(self.gain or 1.0, 1e-12)), 2),
            "max_gain_db": round(20 * math.log10(self.max_gain), 2),
        }
