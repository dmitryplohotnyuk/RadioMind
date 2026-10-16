"""Seeded narrowband speech/noise A/B; no RF recordings or network access."""

import hashlib
import json
import time
import wave
from pathlib import Path

import numpy as np
from scipy import signal

from radiomind.cleaning import VERSION, adaptive_mix, rnnoise_wet


def score(reference, noisy, output):
    energy = np.convolve(reference**2, np.ones(320) / 320, mode="same")
    active = energy > max(1, np.max(energy) * 0.003)
    ref, audio = reference[active], output[active]
    gain = float(np.dot(audio, ref) / max(np.dot(ref, ref), 1))
    error = audio - gain * ref
    return {
        "active_si_sdr_db": float(
            10 * np.log10(max(np.sum((gain * ref) ** 2), 1) / max(np.sum(error**2), 1))
        ),
        "speech_gain_db": float(20 * np.log10(max(abs(gain), 1e-9))),
        "matched_noise_reduction_db": float(
            20
            * np.log10(
                max(np.std(noisy[~active]), 1)
                / max(np.std(output[~active]) / max(abs(gain), 0.01), 1)
            )
        ),
    }


def main():
    fixture = Path("runtime/fixtures/speech.wav")
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    with wave.open(str(fixture)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (
            1,
            2,
            16000,
        )
        speech = (
            np.frombuffer(wav.readframes(wav.getnframes()), "<i2").astype(float) * 0.3
        )
    band = signal.butter(3, [300, 3400], fs=16000, btype="bandpass", output="sos")
    speech = signal.sosfilt(band, speech)
    reference = np.concatenate((np.zeros(16000), speech, np.zeros(16000)))
    report = {
        "version": VERSION,
        "fixture_sha256": digest,
        "real_rf": False,
        "limits": "One local synthetic voice, seeded band noise. Not a human intelligibility score.",
        "cases": [],
    }
    for snr in (0, 6, 15):
        for level in (1, 0.2):
            ref = reference * level
            noise = signal.sosfilt(
                band, np.random.default_rng(812).normal(size=len(ref))
            )
            noise *= np.sqrt(np.mean(ref**2) / np.mean(noise**2)) * 10 ** (-snr / 20)
            noisy = np.rint(np.clip(ref + noise, -32767, 32767)).astype(np.float32)
            started = time.monotonic()
            wet = rnnoise_wet(noisy)
            old = 0.7 * wet + 0.3 * noisy
            new = np.rint(np.clip(adaptive_mix(noisy, wet), -32767, 32767))
            row = {
                "input_snr_db": snr,
                "level": level,
                "samples_equal": len(new) == len(ref),
                "duration": len(ref) / 16000,
                "seconds": time.monotonic() - started,
                "input": score(ref, noisy, noisy),
                "old": score(ref, noisy, old),
                "new": score(ref, noisy, new),
            }
            # A tradeoff is allowed up to 0.5 dB in speech reconstruction, while
            # requiring better matched-level noise reduction in every scenario.
            row["passed"] = (
                row["samples_equal"]
                and -4 <= row["new"]["speech_gain_db"] <= 4
                and row["new"]["active_si_sdr_db"]
                >= row["old"]["active_si_sdr_db"] - 0.5
                and row["new"]["active_si_sdr_db"] > row["input"]["active_si_sdr_db"]
                and row["new"]["matched_noise_reduction_db"]
                > row["old"]["matched_noise_reduction_db"] + 0.5
            )
            report["cases"].append(row)
    report["fixture_unchanged"] = (
        hashlib.sha256(fixture.read_bytes()).hexdigest() == digest
    )
    report["passed"] = report["fixture_unchanged"] and all(
        r["passed"] for r in report["cases"]
    )
    Path("runtime/adaptive-cleanup-quality.json").write_text(
        json.dumps(report, indent=2)
    )
    print(json.dumps(report))
    if not report["passed"]:
        raise RuntimeError("Adaptive cleanup acceptance failed")


if __name__ == "__main__":
    main()
