"""Streaming NFM DSP; every decimator retains history and global sample phase."""

from typing import Any

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from scipy import signal

from radiomind.radio import IQ

Array = NDArray[Any]
Audio = NDArray[np.float64]


class Decimator:
    def __init__(self, coefficients: Array, factor: int, up: int = 1) -> None:
        self.coefficients = coefficients
        self.reversed_coefficients = coefficients[::-1].copy()
        self.factor = factor
        self.up = up
        self.history: Array = np.zeros((len(coefficients) - 1 + up - 1) // up)
        self.processed = 0

    def process(self, samples: Array) -> Array:
        if not len(samples):
            return samples
        if self.processed == 0:
            # Real power/audio streams must not incur complex FIR arithmetic.
            self.history = self.history.astype(samples.dtype)
        h = len(self.history)
        combined = np.concatenate((self.history, samples))
        if self.up == 1 and np.iscomplexobj(samples) and np.isrealobj(self.coefficients):
            # Evaluate only retained FIR outputs. Separate real/imaginary dot
            # products avoid the costly complex upfirdn kernel on this RX path.
            # This is a view, not an N*taps allocation; optimize=False avoids
            # BLAS packing/thread pools. Global phase and causal history match
            # the reference polyphase implementation, including short chunks.
            windows = sliding_window_view(combined, len(self.coefficients))[
                (-self.processed) % self.factor :: self.factor
            ]
            taps = self.reversed_coefficients
            real = np.einsum("ij,j->i", windows.real, taps, optimize=False)
            imag = np.einsum("ij,j->i", windows.imag, taps, optimize=False)
            output = np.empty(len(real), dtype=np.result_type(samples.dtype, taps.dtype))
            output.real, output.imag = real, imag
            self.history = combined[-h:].copy() if h else combined[:0].copy()
            self.processed += len(samples)
            return output
        pad = (self.processed - h) % self.factor
        filtered = signal.upfirdn(
            self.coefficients, np.pad(combined, (pad, 0)), up=self.up, down=self.factor
        )
        start = ((pad + h) * self.up + self.factor - 1) // self.factor
        end = ((pad + h + len(samples)) * self.up + self.factor - 1) // self.factor
        self.history = combined[-h:].copy()
        self.processed += len(samples)
        return np.asarray(filtered[start:end])


class NFMDemodulator:
    """8 MHz complex IQ -> 16 kHz audio; narrow FM, nominal deviation 2.5 kHz."""

    def __init__(self, offset_hz: int, sample_rate: int = 8_000_000) -> None:
        if sample_rate != 8_000_000:
            raise ValueError("NFM streaming pipeline currently requires 8 MS/s")
        self.offset_hz, self.sample_rate = offset_hz, sample_rate
        self.position = 0
        self.oscillators: dict[int, IQ] = {}
        self.first = Decimator(signal.firwin(241, 150_000, fs=sample_rate).astype(np.float32), 20)
        self.channel = Decimator(signal.firwin(401, 6500, fs=400_000).astype(np.float32), 5)
        self.audio = Decimator(signal.firwin(101, 3600, fs=80_000).astype(np.float32), 5)
        self.previous = np.complex64(0)
        self.sos = signal.butter(3, [300, 3400], btype="bandpass", fs=16_000, output="sos")
        self.zi = np.zeros((len(self.sos), 2))
        self.last_power = 0.0
        # Smooth narrow-channel envelope at 80 kHz, then align to the 16 kHz clock.
        self.power_filter = Decimator(signal.firwin(321, 300, fs=80_000).astype(np.float32), 5)
        self.audio_power: Audio = np.empty(0, dtype=np.float64)
        self.noise_sos = signal.butter(2, 6000, btype="highpass", fs=80_000, output="sos")
        self.noise_zi = np.zeros((len(self.noise_sos), 2))
        self.noise_filter = Decimator(signal.firwin(321, 300, fs=80_000).astype(np.float32), 5)
        self.audio_noise: Audio = np.empty(0, dtype=np.float64)
        self.digital_enabled = False
        self.digital_audio: Audio = np.empty(0, dtype=np.float64)
        self.digital_iq_enabled = False
        self.digital_iq: IQ = np.empty(0, dtype=np.complex64)
        self.iq_filter = Decimator(
            (3 * signal.firwin(501, 19000, fs=1200000)).astype(np.float32), 25, up=3
        )
        # Flat discriminator branch: 80 kHz -> 48 kHz, before speech filtering.
        self.digital_filter = Decimator(
            (3 * signal.firwin(151, 18000, fs=240000)).astype(np.float32), 5, up=3
        )

    def process(self, iq: IQ) -> Audio:
        count = len(iq)
        if count not in self.oscillators:
            # Bounded cache for the fixed transfer plus occasional shorter fixture blocks.
            if len(self.oscillators) >= 4:
                self.oscillators.clear()
            self.oscillators[count] = np.asarray(
                np.exp(-2j * np.pi * self.offset_hz * np.arange(count) / self.sample_rate),
                dtype=np.complex64,
            )
        phase = np.exp(
            -2j * np.pi * self.offset_hz * (self.position % self.sample_rate) / self.sample_rate
        )
        mixed = iq * self.oscillators[count] * np.complex64(phase)
        self.position += count
        wide = self.first.process(mixed)
        if self.digital_iq_enabled:
            self.digital_iq = np.asarray(self.iq_filter.process(wide), dtype=np.complex64)
        narrow = self.channel.process(wide)
        if not len(narrow):
            self.audio_power = np.empty(0, dtype=np.float64)
            self.audio_noise = np.empty(0, dtype=np.float64)
            self.digital_audio = np.empty(0, dtype=np.float64)
            return np.empty(0, dtype=np.float64)
        self.last_power = float(np.mean(np.abs(narrow) ** 2))
        self.audio_power = np.asarray(
            self.power_filter.process(np.abs(narrow) ** 2).real, dtype=np.float64
        )
        previous = np.concatenate(([self.previous], narrow[:-1]))
        self.previous = narrow[-1]
        demodulated = np.angle(narrow * np.conj(previous)) * (80_000 / (2 * np.pi * 2500))
        if self.digital_enabled:
            self.digital_audio = np.asarray(
                self.digital_filter.process(demodulated).real, dtype=np.float64
            )
        high_noise, self.noise_zi = signal.sosfilt(self.noise_sos, demodulated, zi=self.noise_zi)
        self.audio_noise = np.asarray(
            self.noise_filter.process(high_noise**2).real, dtype=np.float64
        )
        reduced = self.audio.process(demodulated).real
        filtered, self.zi = signal.sosfilt(self.sos, reduced, zi=self.zi)
        return np.asarray(filtered, dtype=np.float64)
