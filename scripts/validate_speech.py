"""Local synthesized speech -> FM IQ -> streaming demod/VAD -> WAV validation."""

import argparse
import json
import time
import wave
from pathlib import Path

import numpy as np

from radiomind.config import AudioSettings, Settings, Window
from radiomind.conversation import Conversation
from radiomind.recording import Archive
from radiomind.storage import Store

parser = argparse.ArgumentParser()
parser.add_argument("--vad", choices=["webrtc", "silero"], default="webrtc")
args = parser.parse_args()
root = Path("runtime/synthetic-" + args.vad)
root.mkdir(parents=True, exist_ok=True)
with wave.open("runtime/fixtures/speech.wav") as wav:
    speech = (
        np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(float)
        / 32768
    )
speech_seconds = len(speech) / 16000
speech = np.concatenate((speech, np.zeros(192000)))
settings = Settings(
    country="UA",
    legal_basis="local synthesized fixture only",
    windows=[
        Window(
            name="Synthetic NFM",
            start_hz=140000000,
            end_hz=148000000,
            allowed_actions=["observe", "demodulate", "record_audio"],
        )
    ],
    audio=AudioSettings(enabled=True, vad_engine=args.vad),
)
store = Store(root / "mock.sqlite3", 10000)
archive = Archive(settings, store)
conversation = Conversation(settings, archive, settings.windows[0], 145500000, 30)
rate = 8000000
phase = 0.0
started = time.perf_counter()
blocks = 0
for start in range(0, len(speech) * 500, 131072):
    count = min(131072, len(speech) * 500 - start)
    positions = (np.arange(count) + start) / 500
    audio = np.interp(positions, np.arange(len(speech)), speech)
    increments = 2 * np.pi * (1500000 + 2500 * audio) / rate
    phases = phase + np.cumsum(increments)
    phase = float(phases[-1] % (2 * np.pi))
    iq = np.asarray(0.4 * np.exp(1j * phases), dtype=np.complex64)
    frames = conversation.decode(iq, 1e-8)
    conversation.consume(
        frames, retention=conversation.gate.retention, rf_active=conversation.rf_frames
    )
    blocks += 1
    if conversation.done:
        break
conversation.finish(conversation.end_reason or "fixture_end")
rows = store.recordings()
assert conversation.speech_found and rows[0]["playable"]
assert rows[0]["duration_seconds"] >= speech_seconds - 0.1
assert (start + count) / rate >= speech_seconds
rows[0]["title"] = "Синтетическая речь · проверка тракта"
store.save_recording(rows[0])
report = {
    "fixture": "Windows System.Speech local TTS, not RF",
    "elapsed_seconds": time.perf_counter() - started,
    "input_seconds_processed": (start + count) / rate,
    "blocks": blocks,
    "recording": rows[0],
}
(root / "report.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False), encoding="utf8"
)
print(json.dumps(report, ensure_ascii=True))
store.close()
