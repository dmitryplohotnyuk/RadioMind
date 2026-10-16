"""Local, conservative speech-candidate gate; not a protocol/plaintext classifier."""

from collections import deque

import numpy as np
import webrtcvad

from radiomind.neural_vad import SileroProbability
from radiomind.nfm import Audio
from radiomind.pcm import pcm16


class SpeechGate:
    frame_samples = 320

    def __init__(self, engine: str = "webrtc") -> None:
        self.vad = webrtcvad.Vad(3)
        self.pending: Audio = np.empty(0, dtype=np.float64)
        self.votes: deque[bool] = deque(maxlen=15)
        self.energy: deque[float] = deque(maxlen=15)
        self.last_details: dict[str, float | bool] = {}
        self.retention: list[bool] = []
        self.neural = SileroProbability() if engine == "silero" else None
        self.probability = 0.0
        self.neural_streak = 0

    def frame_is_speech(self, frame: Audio, rf_ok: bool = True) -> bool:
        rms = float(np.sqrt(np.mean(frame**2)))
        if self.neural is not None:
            for probability in self.neural.push(pcm16(frame).astype(np.float32) / 32768):
                self.probability = probability
                self.neural_streak = self.neural_streak + 1 if probability >= 0.5 else 0
            accepted = rf_ok and self.neural_streak >= 3  # 3 distinct model blocks = 96 ms.
            self.last_details = {
                "rms": rms,
                "probability": self.probability,
                "speech_candidate": accepted,
                "retain": rf_ok and self.probability >= 0.25,
            }
            return accepted
        power = np.abs(np.fft.rfft(frame * np.hanning(len(frame)))) ** 2 + 1e-12
        frequencies = np.fft.rfftfreq(len(frame), 1 / 16000)
        # Out-of-band suppression must not make filtered noise look speech-like.
        power = power[(frequencies >= 300) & (frequencies <= 3400)]
        total = float(np.sum(power))
        concentration = float(np.sum(np.sort(power)[-3:]) / total)
        flatness = float(np.exp(np.mean(np.log(power))) / np.mean(power))
        # Fixed gain avoids turning quiet receiver noise into full-scale audio.
        pcm = pcm16(frame).tobytes()
        voiced = bool(self.vad.is_speech(pcm, 16000))
        accepted = rf_ok and voiced and rms > 0.005 and concentration < 0.88 and flatness < 0.35
        self.last_details = {
            "rms": rms,
            "tone_concentration": concentration,
            "spectral_flatness": flatness,
            "vad": voiced,
            "speech_candidate": accepted,
            "retain": rf_ok and voiced and rms > 0.003 and concentration < 0.96 and flatness < 0.65,
        }
        return accepted

    def process(self, samples: Audio, rf_ok: bool = True) -> list[tuple[Audio, bool]]:
        self.pending = np.concatenate((self.pending, samples))
        result = []
        self.retention = []
        offset = 0
        while len(self.pending) - offset >= self.frame_samples:
            frame = self.pending[offset : offset + self.frame_samples].copy()
            offset += self.frame_samples
            self.votes.append(self.frame_is_speech(frame, rf_ok))
            self.energy.append(float(self.last_details["rms"]))
            variation = float(np.std(self.energy)) / max(float(np.mean(self.energy)), 1e-9)
            # 200 ms voiced evidence in a 300 ms window, not one transient VAD vote.
            confirmed = (
                len(self.votes) == self.votes.maxlen and sum(self.votes) >= 10 and variation > 0.12
            )
            if self.neural is not None:
                confirmed = self.votes[-1]
            result.append((frame, confirmed))
            self.retention.append(bool(self.last_details["retain"]))
        self.pending = self.pending[offset:].copy()
        return result
