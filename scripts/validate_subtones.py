"""Local synthesized speech/FM/CTCSS replay. No RF device, TX or real RF files."""

import argparse
import json
import time
import wave
from pathlib import Path
from uuid import uuid4

import numpy as np

from radiomind.config import load_settings
from radiomind.digital_conversation import MultiModeConversation
from radiomind.recording import Archive
from radiomind.storage import Store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset-hz", type=float, default=0)
    parser.add_argument("--noise", type=float, default=0)
    args = parser.parse_args()
    with wave.open("runtime/fixtures/speech.wav") as wav:
        assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
        rate = wav.getframerate()
        speech = (
            np.frombuffer(wav.readframes(rate * 4), dtype="<i2").astype(float) / 32768
        )
    speech *= 0.7 / max(np.max(np.abs(speech)), 0.001)
    settings = load_settings(Path("config/hackrf-recorder.yaml"))
    settings.source = "mock"
    rows = []
    for tone in (0, 67, 100, 254.1):
        destination = Path("runtime") / ("subtone-fixture-" + uuid4().hex)
        destination.mkdir()
        store = Store(destination / "mock.sqlite3", 1000)
        conv = MultiModeConversation(
            settings,
            Archive(settings, store),
            settings.windows[0],
            145000000,
            30,
            mode=store.digital_mode(145000000),
        )
        phase = 0.0
        rng = np.random.default_rng(23)
        started = time.monotonic()
        try:
            for pos in range(0, round(len(speech) / rate * 8_000_000), 131072):
                t = (pos + np.arange(131072)) / 8_000_000
                modulation = np.interp(
                    t * rate, np.arange(len(speech)), speech, right=0
                )
                if tone:
                    modulation += 0.16 * np.sin(2 * np.pi * tone * t)
                angles = phase + np.cumsum(
                    1_000_000 + args.offset_hz + modulation * 2500
                ) * (2 * np.pi / 8_000_000)
                phase = angles[-1] % (2 * np.pi)
                iq = (0.5 * np.exp(1j * angles)).astype(np.complex64)
                if args.noise:
                    iq += (
                        args.noise
                        * (rng.normal(size=len(iq)) + 1j * rng.normal(size=len(iq)))
                    ).astype(np.complex64)
                frames = conv.decode(iq, 1e-7)
                conv.consume(
                    frames, retention=conv.gate.retention, rf_active=conv.rf_frames
                )
                if conv.done or conv.choice is not None:
                    break
                wait = (pos + len(iq)) / 8_000_000 - (time.monotonic() - started)
                if wait > 0:
                    time.sleep(wait)
            conv.finish("synthetic_subtone_end")
            recordings = store.recordings()
            row = {
                "ctcss_hz": tone or None,
                "hardware_test": False,
                "offset_hz": args.offset_hz,
                "noise_rms": args.noise,
                "choice": conv.choice,
                "checked_ms": conv.checked_ms,
                "records": len(recordings),
                "playable": all(r["playable"] for r in recordings),
                "learned_mode": store.digital_mode(145000000),
                "attempt": store.digital_attempts()[0],
            }
            row["passed"] = (
                row["choice"] == "analog"
                and row["records"] == 1
                and row["playable"]
                and row["learned_mode"] == "auto"
                and not row["attempt"]["decoder_error"]
            )
            rows.append(row)
            print(json.dumps(row), flush=True)
        finally:
            conv.digital.close()
            store.close()
    Path("runtime/subtone-validation.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )
    if not all(row["passed"] for row in rows):
        raise SystemExit("Subtone validation failed")


if __name__ == "__main__":
    main()
