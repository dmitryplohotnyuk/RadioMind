"""Local deterministic DSP A/B; no device, RF files, or network. Not an RX test."""

import json
import time
from pathlib import Path

import numpy as np
from scipy import signal

from radiomind.nfm import Decimator, NFMDemodulator
from radiomind.speech import SpeechGate
from radiomind.squelch import CarrierSquelch


class ReferenceDecimator(Decimator):
    def process(self, samples):
        if not len(samples):
            return samples
        if self.processed == 0:
            self.history = self.history.astype(samples.dtype)
        h = len(self.history)
        combined = np.concatenate((self.history, samples))
        pad = (self.processed - h) % self.factor
        filtered = signal.upfirdn(
            self.coefficients, np.pad(combined, (pad, 0)), up=self.up, down=self.factor
        )
        start = ((pad + h) * self.up + self.factor - 1) // self.factor
        end = ((pad + h + len(samples)) * self.up + self.factor - 1) // self.factor
        self.history = combined[-h:].copy()
        self.processed += len(samples)
        return np.asarray(filtered[start:end])


def measure(reference, blocks):
    decoder = NFMDemodulator(1234500)
    decoder.digital_iq_enabled = True
    if reference:
        for name, value in vars(decoder).copy().items():
            if isinstance(value, Decimator):
                setattr(
                    decoder,
                    name,
                    ReferenceDecimator(value.coefficients, value.factor, value.up),
                )
    gate, squelch = SpeechGate("silero"), CarrierSquelch()
    outputs, times = [], []
    for block in blocks:
        started = time.perf_counter()
        audio = decoder.process(block)
        gate.process(audio, True)
        quieted = squelch.process(audio, decoder.audio_power, 1e-7, decoder.audio_noise)
        times.append((time.perf_counter() - started) * 1000)
        outputs.append((audio.copy(), quieted, decoder.digital_iq.copy()))
    return outputs, {
        "mean_ms": float(np.mean(times[1:])),
        "p95_ms": float(np.percentile(times[1:], 95)),
    }


def main():
    rng = np.random.default_rng(514)
    blocks = [
        (rng.normal(size=131072) + 1j * rng.normal(size=131072)).astype(np.complex64)
        * 0.01
        for _ in range(4)
    ] * 75
    old, old_times = measure(True, blocks)
    new, new_times = measure(False, blocks)
    differences = []
    for branch in range(3):
        a = np.concatenate([o[branch] for o in old])
        b = np.concatenate([o[branch] for o in new])
        np.testing.assert_allclose(b, a, atol=2e-5, rtol=2e-4)
        differences.append(float(np.max(np.abs(b - a))))
    report = {
        "synthetic": True,
        "input_block_ms": 16.384,
        "blocks": len(blocks),
        "old": old_times,
        "new": new_times,
        "branch_max_errors": differences,
        "speedup": old_times["mean_ms"] / new_times["mean_ms"],
    }
    Path("runtime/overflow-dsp-ab.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
