"""Streaming 48 kHz pi/4-DQPSK receive demodulator for TETRA TMO downlink.

RRC matched filter, Gardner symbol timing and differential phase decisions. This
is an experimental PHY; a following CRC-checked MAC must validate its output.
"""

import math

import numpy as np
from scipy import signal

from radiomind.nfm import Audio
from radiomind.radio import IQ


def rrc_taps(sps: float, count: int = 81, beta: float = 0.35) -> Audio:
    values = []
    for t in (np.arange(count) - (count - 1) / 2) / sps:
        if abs(t) < 1e-10:
            value = 1 + beta * (4 / math.pi - 1)
        elif abs(abs(t) - 1 / (4 * beta)) < 1e-10:
            value = (
                beta
                / math.sqrt(2)
                * (
                    (1 + 2 / math.pi) * math.sin(math.pi / (4 * beta))
                    + (1 - 2 / math.pi) * math.cos(math.pi / (4 * beta))
                )
            )
        else:
            value = (
                math.sin(math.pi * t * (1 - beta))
                + 4 * beta * t * math.cos(math.pi * t * (1 + beta))
            ) / (math.pi * t * (1 - (4 * beta * t) ** 2))
        values.append(value)
    taps = np.asarray(values, dtype=np.float64)
    return taps / np.linalg.norm(taps)


class TetraDemodulator:
    def __init__(self) -> None:
        self.taps = rrc_taps(48000 / 18000)
        self.zi = np.zeros(len(self.taps) - 1, dtype=np.complex128)
        self.buffer: list[complex] = []
        self.omega = 48000 / 18000
        self.position = 3 * self.omega
        self.previous = 0j
        self.frequency = 0.0

    def _sample(self, position: float) -> complex:
        integer = int(position)
        fraction = position - integer
        return self.buffer[integer] * (1 - fraction) + self.buffer[integer + 1] * fraction

    def process(self, samples: IQ) -> bytes:
        if not np.all(np.isfinite(samples)):
            raise RuntimeError("Non-finite TETRA IQ")
        if not len(samples):
            return b""
        filtered, self.zi = signal.lfilter(self.taps, [1], samples, zi=self.zi)
        self.buffer.extend(complex(x) for x in filtered)
        bits = bytearray()
        while self.position + 1 < len(self.buffer):
            late = self._sample(self.position)
            early = self._sample(self.position - self.omega)
            middle = self._sample(self.position - self.omega / 2)
            power = abs(late) ** 2 + abs(early) ** 2 + 1e-12
            error = max(-1.0, min(1.0, ((early - late) * middle.conjugate()).real / power))
            self.omega = max(2.66, min(2.674, self.omega + 0.00005 * error))
            self.position += self.omega + 0.04 * error
            differential = late * self.previous.conjugate()
            self.previous = late
            angle = math.atan2(differential.imag, differential.real) - self.frequency
            residual = (
                math.atan2(math.sin(4 * (angle - math.pi / 4)), math.cos(4 * (angle - math.pi / 4)))
                / 4
            )
            self.frequency += 0.004 * residual
            phase = complex(math.cos(angle), math.sin(angle))
            bits.extend((int(phase.imag < 0), int(phase.real < 0)))
        discard = max(0, int(self.position) - 12)
        if discard:
            del self.buffer[:discard]
            self.position -= discard
        return bytes(bits)
