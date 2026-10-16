from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import numpy as np

from radiomind.config import Settings, Window
from radiomind.nfm import Audio, NFMDemodulator
from radiomind.pcm import pcm16
from radiomind.radio import IQ
from radiomind.recording import Archive, RecordingWriter
from radiomind.speech import SpeechGate
from radiomind.squelch import CarrierSquelch


class Conversation:
    """Hold one channel; recording parts never reset the decoder or speech clock."""

    def __init__(
        self,
        settings: Settings,
        archive: Archive,
        window: Window,
        frequency_hz: int,
        snr_db: float,
        capture_start_utc: datetime | None = None,
    ) -> None:
        self.settings, self.archive, self.window = settings, archive, window
        self.frequency_hz, self.snr_db = frequency_hz, snr_db
        self.decoder = NFMDemodulator(frequency_hz - window.center_hz)
        self.gate = SpeechGate(settings.audio.vad_engine)
        self.squelch = CarrierSquelch()
        self.audio_pending: Audio = np.empty(0, dtype=np.float64)
        self.pre_roll: deque[Audio] = deque(maxlen=max(1, settings.audio.pre_roll_ms // 20))
        self.writer: RecordingWriter | None = None
        self.capture_start_utc = capture_start_utc or datetime.now(UTC)
        self.session_id = uuid4().hex
        self.session_start_utc: datetime | None = None
        self.recorded_samples = 0
        self.part_number = 1
        self.elapsed_ms = 0
        self.last_voice_ms = 0
        self.last_rf_ms = 0
        self.done = False
        self.speech_found = False
        self.state = "VERIFY"
        self.end_reason: str | None = None
        self.rf_frames: list[bool] = []
        self.verify_limit_ms = settings.audio.verify_ms
        self.acquisition: dict[str, float | str] = {}
        self.evidence_samples = self.rf_samples = self.last_rf_sample = 0
        self.speech_frames = 0
        self.vad_probability_max = 0.0

    def decode(self, iq: IQ, noise_power: float) -> list[tuple[Audio, bool]]:
        audio = self.decoder.process(iq)
        rf_ok = self.decoder.last_power > noise_power * 4
        frames = self.gate.process(audio, rf_ok)
        self.evidence_samples += len(audio)
        if rf_ok:
            self.rf_samples += len(audio)
            self.last_rf_sample = self.evidence_samples
        self.speech_frames += sum(int(speech) for _, speech in frames)
        self.vad_probability_max = max(
            self.vad_probability_max, float(self.gate.last_details.get("probability", 0))
        )
        # VAD sees the original audio. Only the samples destined for the archive
        # are squelched; it cannot create artificial speech decisions or cut hold.
        quieted = self.squelch.process(
            audio, self.decoder.audio_power, noise_power, self.decoder.audio_noise
        )
        self.audio_pending = np.concatenate((self.audio_pending, quieted))
        for index, (_, speech) in enumerate(frames):
            start = index * self.gate.frame_samples
            frames[index] = (
                self.audio_pending[start : start + self.gate.frame_samples].copy(),
                speech,
            )
        self.audio_pending = self.audio_pending[len(frames) * self.gate.frame_samples :].copy()
        self.rf_frames = [rf_ok] * len(frames)
        return frames

    def signal_evidence(self) -> dict[str, float | int]:
        return {
            "observed_ms": round(self.evidence_samples / 16),
            "rf_present_fraction": round(self.rf_samples / max(1, self.evidence_samples), 3),
            "rf_absent_tail_ms": round((self.evidence_samples - self.last_rf_sample) / 16),
            "speech_frames": self.speech_frames,
            "vad_probability_max": round(self.vad_probability_max, 3),
        }

    def _open_part(self) -> None:
        assert self.session_start_utc is not None
        self.writer = RecordingWriter(
            self.archive,
            self.window,
            self.frequency_hz,
            np.empty(0),
            self.snr_db,
            session_id=self.session_id,
            part_number=self.part_number,
            sample_offset=self.recorded_samples,
            start_utc=self.session_start_utc + timedelta(seconds=self.recorded_samples / 16000),
        )

    def _write(self, audio: Audio) -> None:
        limit = self.settings.audio.max_recording_seconds * 16000
        offset = 0
        while offset < len(audio):
            if self.writer is None:
                self._open_part()
            assert self.writer is not None
            if self.writer.samples == limit:
                self.archive.reserve_check(44 + min(len(audio) - offset, limit) * 2)
                self.writer.finish("part_rotation")
                self.part_number += 1
                self._open_part()
            size = min(len(audio) - offset, limit - self.writer.samples)
            self.writer.write(audio[offset : offset + size])
            if self.archive.live_audio.clients:
                self.archive.live_audio.publish(
                    self.session_id, pcm16(audio[offset : offset + size]).tobytes()
                )
            self.recorded_samples += size
            offset += size

    def consume(
        self,
        frames: list[tuple[Audio, bool]],
        *,
        retention: list[bool] | None = None,
        rf_active: list[bool] | None = None,
    ) -> None:
        for index, (audio, speech) in enumerate(frames):
            if self.done:
                break
            self.elapsed_ms += 20
            # Initial FIR warm-up is explicitly excluded; history starts before detection.
            if self.elapsed_ms < 60:
                continue
            retain = speech or (retention is not None and retention[index])
            carrier = rf_active is not None and rf_active[index]
            if carrier:
                self.last_rf_ms = self.elapsed_ms
            if self.writer is None:
                self.pre_roll.append(audio)
                if speech:
                    self.speech_found = True
                    self.last_voice_ms = self.elapsed_ms
                    pre_roll = np.concatenate(list(self.pre_roll))
                    self.session_start_utc = self.capture_start_utc + timedelta(
                        seconds=self.elapsed_ms / 1000 - len(pre_roll) / 16000
                    )
                    self._write(pre_roll)
                    self.pre_roll.clear()
                    self.state = "RECORD"
                elif self.elapsed_ms >= self.verify_limit_ms:
                    self.finish("speech_not_confirmed")
            else:
                self._write(audio)
                if retain:
                    self.last_voice_ms = self.elapsed_ms
                    self.state = "RECORD"
                else:
                    self.state = "HANG"
                # A missed strict speech vote is not a carrier-off event. Hold longer
                # while RF persists, but release a stuck non-speech carrier eventually.
                quiet_ms = self.elapsed_ms - self.last_voice_ms
                rf_quiet_ms = self.elapsed_ms - self.last_rf_ms
                if quiet_ms >= self.settings.audio.hang_ms and (
                    rf_quiet_ms >= self.settings.audio.hang_ms
                    or quiet_ms >= self.settings.audio.carrier_grace_ms
                ):
                    self.finish(
                        "silence"
                        if rf_quiet_ms >= self.settings.audio.hang_ms
                        else "sustained_non_speech"
                    )

    def finish(self, reason: str, interrupted: bool = False) -> None:
        if self.writer:
            self.writer.finish(reason, interrupted)
        self.done, self.end_reason, self.state = True, reason, "SCAN"

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "frequency_hz": self.frequency_hz,
            "elapsed_seconds": self.elapsed_ms / 1000,
            "speech_found": self.speech_found,
            "session_id": self.session_id,
            "part_number": self.part_number,
            "recording_id": self.writer.recording_id if self.writer else None,
            "recorded_seconds": self.recorded_samples / 16000,
            "reply_wait_remaining_seconds": max(
                0, (self.settings.audio.hang_ms - (self.elapsed_ms - self.last_voice_ms)) / 1000
            ),
            "squelch_open": self.squelch.open,
        }
