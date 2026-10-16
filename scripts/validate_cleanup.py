"""Reproducible local TTS + seeded noise comparison, never reads RF archives."""

import json
import time
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

from radiomind.cleaning import denoise


def main():
    fixture = Path("runtime/fixtures/speech.wav")
    with wave.open(str(fixture)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (
            1,
            2,
            16000,
        ):
            raise ValueError("Expected mono PCM16 16 kHz TTS fixture")
        speech = (
            np.frombuffer(wav.readframes(wav.getnframes()), "<i2").astype(np.float32)
            * 0.3
        )
    reference = np.concatenate([np.zeros(16000), speech, np.zeros(16000)]).astype(
        np.float32
    )
    noise = sosfilt(
        butter(4, [300, 3400], fs=16000, btype="bandpass", output="sos"),
        np.random.default_rng(812).normal(size=len(reference)),
    ).astype(np.float32)
    noise *= np.sqrt(np.mean(reference**2) / np.mean(noise**2))
    noisy = np.clip(reference + noise, -32767, 32767).astype("<i2")
    start = time.monotonic()
    cleaned = denoise(noisy)

    def snr(a):
        return float(10 * np.log10(np.sum(reference**2) / np.sum((a - reference) ** 2)))

    report = {
        "fixture": "local synthetic TTS plus seeded band noise at 0 dB",
        "original_snr_db": snr(noisy),
        "cleaned_snr_db": snr(cleaned),
        "silence_noise_reduction_db": float(
            20 * np.log10(np.std(noisy[-8000:]) / max(np.std(cleaned[-8000:]), 1))
        ),
        "sample_count_equal": len(reference) == len(cleaned),
        "elapsed": time.monotonic() - start,
        "duration": len(reference) / 16000,
        "real_rf": False,
    }
    Path("runtime/cleaning-quality.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    if (
        not report["sample_count_equal"]
        or report["cleaned_snr_db"] < report["original_snr_db"] + 3
    ):
        raise RuntimeError("Synthetic cleanup acceptance failed")


if __name__ == "__main__":
    main()
