"""Analog/digital selection and archive ingestion; the decoder never owns RF.

Digital PCM is checkpointed privately to disk during capture. An encryption
indication suppresses the entire candidate before WAV/ASR ingestion. The two
TDMA slots stay separate. Analog capture keeps its original sample clock.
"""

from datetime import UTC, datetime
from typing import Any

import numpy as np

from radiomind.config import Settings, Window
from radiomind.conversation import Conversation
from radiomind.digital import decoder_path
from radiomind.digital_journal import DigitalJournal, publish
from radiomind.digital_metadata import frame_summary, worker_summary
from radiomind.digital_timeline import DigitalTimeline
from radiomind.nfm import Audio
from radiomind.radio import IQ
from radiomind.recording import Archive
from radiomind.tetra import DigitalDispatch


class MultiModeConversation(Conversation):
    def __init__(
        self,
        settings: Settings,
        archive: Archive,
        window: Window,
        frequency_hz: int,
        snr_db: float,
        capture_start_utc: Any = None,
        *,
        mode: str,
    ) -> None:
        super().__init__(settings, archive, window, frequency_hz, snr_db, capture_start_utc)
        # The owner resolves the persisted mode before entering this worker.
        # Shared SQLite access here can deadlock a concurrent HTTP query/UDF.
        if mode == "TETRA" and not settings.digital.tetra_enabled:
            mode = "auto"
        self.iq_mode = settings.digital.input_mode == "iq"
        # Even one worker must pass the same admission policy. Disabling probes
        # must not restore the old sync-plus-PCM shortcut for DMR.
        self.digital: Any = DigitalDispatch(
            decoder_path(settings.digital.executable),
            mode,
            tetra=settings.digital.tetra_enabled,
            dstar=settings.digital.dstar_probe_enabled,
            p25p2=settings.digital.p25p2_probe_enabled,
            dmr=settings.digital.dmr_probe_enabled,
            iq=self.iq_mode,
        )
        self.decoder.digital_enabled = not self.iq_mode
        self.decoder.digital_iq_enabled = self.iq_mode
        self.choice: str | None = None
        self.pending: list[tuple[Audio, bool, bool, bool]] = []
        self.checked_ms = 0
        self.timeline = DigitalTimeline(settings.digital.max_buffer_mb * 1024**2)
        self.digital_metadata: dict[str, Any] = {}
        self.locked_protocol: str | None = None
        self.encrypted_call = False
        self.journal: DigitalJournal | None = None
        self.checkpoint_ms = 0
        self.attempt_saved = False

    def decode(self, iq: IQ, noise_power: float) -> list[tuple[Audio, bool]]:
        frames = super().decode(iq, noise_power)
        if self.choice != "analog":
            if self.iq_mode:
                self.digital.feed_iq(self.decoder.digital_iq)
            else:
                self.digital.feed(self.decoder.digital_audio)
        return frames

    def consume(
        self,
        frames: list[tuple[Audio, bool]],
        *,
        retention: list[bool] | None = None,
        rf_active: list[bool] | None = None,
    ) -> None:
        if self.choice == "analog":
            super().consume(frames, retention=retention, rf_active=rf_active)
            return
        self.digital.check()
        self.checked_ms += 20 * len(frames)
        voice = self.timeline.append(self.digital.drain())
        self.digital_metadata = self.digital.status()
        protocol = self.digital_metadata["protocol"]
        # Noise produces occasional false sync/encryption log lines in upstream.
        # Only actual decoded PCM plus repeated sync may displace analog VAD.
        if protocol and self.timeline.has_audio and self.choice is None:
            self.choice = "digital"
            self.locked_protocol = protocol
            self.pending.clear()
        if self.choice == "digital":
            self.elapsed_ms = self.checked_ms
            self.state = "RECORD" if self.timeline.has_audio else "VERIFY"
            if voice:
                self.speech_found = True
                self.last_voice_ms = self.elapsed_ms
            elif self.timeline.has_audio:
                self.state = "HANG"
            self._check_encryption()
            if self.encrypted_call:
                self.finish("encrypted")
                return
            self._checkpoint()
            if not self.timeline.has_audio and self.checked_ms >= self.settings.digital.verify_ms:
                self.finish("digital_no_voice")
            elif self.timeline.has_audio and (
                self.elapsed_ms - self.last_voice_ms >= self.settings.audio.hang_ms
            ):
                self.finish("digital_voice_ended")
            return
        self.pending.extend(
            (
                audio,
                speech,
                retention[index] if retention else speech,
                rf_active[index] if rf_active else False,
            )
            for index, (audio, speech) in enumerate(frames)
        )
        if self.checked_ms >= self.settings.digital.analog_decision_ms and any(
            frame[1] for frame in self.pending
        ):
            # Give a started digital decoder a chance to settle before committing
            # analog audio. An explicit recognized protocol always takes precedence.
            if self.timeline.has_audio:
                if self.checked_ms < self.settings.digital.verify_ms:
                    return
            self.digital.close()
            self.choice = "analog"
            self.decoder.digital_enabled = False
            self.decoder.digital_iq_enabled = False
            self.timeline = DigitalTimeline(self.settings.digital.max_buffer_mb * 1024**2)
            pending, self.pending = self.pending, []
            self.archive.store.forget_digital(self.frequency_hz)
            self.verify_limit_ms = max(self.verify_limit_ms, self.checked_ms + 20)
            for audio, speech, retain, carrier in pending:
                super().consume([(audio, speech)], retention=[retain], rf_active=[carrier])
                if self.done:
                    break
        elif self.checked_ms >= self.settings.digital.verify_ms:
            self.archive.store.forget_digital(self.frequency_hz)
            self.finish("speech_not_confirmed")

    def finish(self, reason: str, interrupted: bool = False) -> None:
        if self.done:
            return
        if self.choice == "analog":
            super().finish(reason, interrupted)
            self._save_attempt(reason)
            return
        self.digital.close()
        self.digital_metadata = self.digital.status()
        protocol = self.locked_protocol or self.digital_metadata["protocol"]
        self._check_encryption()
        if not self.encrypted_call:
            tail = self.digital.drain()
            try:
                self.timeline.append(tail)
            except RuntimeError:
                interrupted = True
                reason = "digital_buffer_limit"
            # The first decoded audio/crypto indication can arrive while closing
            # the worker. Apply the same veto to this final batch before staging.
            if protocol and self.timeline.has_audio:
                self.locked_protocol = protocol
            voiced_tail = [
                packet
                for packet in tail
                if np.any(np.abs(np.frombuffer(packet.pcm, dtype="<i2").astype(int)) > 8)
            ]
            if voiced_tail:
                self.last_voice_ms = round(voiced_tail[-1].input_seconds * 1000)
        self._check_encryption()
        encrypted = self.encrypted_call
        self.done, self.end_reason, self.state = True, reason, "SCAN"
        # Sync text alone is not a verified intercept. Staging is not playable.
        try:
            if encrypted:
                self.speech_found = False
                if self.journal:
                    try:
                        self.journal.block()
                    finally:
                        # If the disk cannot commit a veto, remove only this
                        # unpublished staging so it cannot be recovered as clear.
                        self.journal.discard()
            elif protocol and self.timeline.has_audio:
                self.locked_protocol = protocol
                interrupted |= bool(self.digital.error)
                self._checkpoint(force=True, state="ready", reason=reason, interrupted=interrupted)
                assert self.journal is not None
                publish(self.archive, self.journal.metadata, self.timeline)
                self.speech_found = True
                self.recorded_samples = self.timeline.end * 2
                self.journal.discard()
                self.archive.store.remember_digital(self.frequency_hz, protocol)
        finally:
            if self.journal:
                self.journal.close()
            self._save_attempt(reason)

    def _save_attempt(self, reason: str) -> None:
        if self.attempt_saved:
            return
        evidence = self.digital.status()
        candidates = evidence.get("sync_candidates", [])
        if evidence.get("protocol"):
            candidates = sorted(set(candidates) | {evidence["protocol"]})
        signal = self.signal_evidence()
        workers = evidence.get("worker_evidence", [worker_summary(evidence)])
        frames = frame_summary(workers)
        relevant = set(candidates) | ({self.locked_protocol} if self.locked_protocol else set())
        errors = sorted(
            p
            for p, count in evidence.get("invalid_counts", {}).items()
            if count and (not relevant or p in relevant)
        )
        # Header evidence may exist with muted/no PCM. This is a diagnostic hint,
        # not a reason to select a decoder or interfere with analog fallback.
        crypto_header = bool(
            frames.get("crypto_header") and "DMR" in relevant and self.choice != "analog"
        )
        service_only = bool(
            "DMR" in relevant
            and sum(frames.get(k, 0) for k in ("idle", "data", "control")) >= 2
            and not frames.get("voice_burst")
            and not frames.get("voice_header")
        )
        diagnosis = (
            "decoder_error"
            if evidence.get("error")
            else "encryption_indicated"
            if self.encrypted_call or crypto_header
            else "audio_selected"
            if self.choice == "analog" or self.speech_found
            else "rf_disappeared"
            if self.rf_samples and signal["rf_absent_tail_ms"] >= 500
            else "rf_not_confirmed"
            if self.evidence_samples and signal["rf_present_fraction"] < 0.1
            else "frame_errors_observed"
            if errors
            else "service_frames_observed"
            if service_only
            else "sync_without_audio"
            if candidates
            else "no_digital_sync"
            if not any(evidence.get("sync_counts", {}).values())
            else "insufficient_sync"
        )
        self.archive.store.save_digital_attempt(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "frequency_hz": self.frequency_hz,
                "protocol": self.locked_protocol or evidence.get("protocol"),
                "outcome": "encryption_indicated"
                if self.encrypted_call or crypto_header
                else "analog_selected"
                if self.choice == "analog"
                else "audio_candidate"
                if self.speech_found
                else "sync_without_audio"
                if candidates
                else "not_decoded",
                "reason": reason,
                "input_mode": self.settings.digital.input_mode,
                "sync_counts": evidence.get("sync_counts", {}),
                "sync_candidates": candidates,
                "invalid_counts": evidence.get("invalid_counts", {}),
                "evidence_version": 2,
                "diagnostic_error_protocols": errors,
                "worker_evidence": workers,
                "selection_evidence": evidence.get("selection_evidence", {}),
                "frame_summary": frames,
                "encryption_protocols": sorted(evidence.get("encryption_at", {})),
                "decoder_error": evidence.get("error"),
                "decoder_transport": evidence.get("transport", {}),
                "decoder_input_level": evidence.get("input_level", {}),
                "checked_ms": self.checked_ms,
                "diagnostic_reason": diagnosis,
                "signal_evidence": signal,
                "acquisition": self.acquisition,
            }
        )
        self.attempt_saved = True

    def _checkpoint(self, force: bool = False, state: str = "active", **extra: Any) -> None:
        if self.journal is None:
            from radiomind.policy import require_audio

            require_audio(self.settings, self.window, self.frequency_hz)
            self.journal = DigitalJournal(
                self.archive,
                {
                    "capture_group": self.session_id,
                    "source": self.settings.source,
                    "window": self.window.model_dump(),
                    "frequency_hz": self.frequency_hz,
                    "start_utc": self.capture_start_utc.isoformat(),
                    "snr_db": self.snr_db,
                    "protocol": self.locked_protocol,
                    "dsp_version": "complex-48k+"
                    + ("tetra-kit-2205072" if self.locked_protocol == "TETRA" else "dsd-neo-2.10.0")
                    if self.iq_mode
                    else "flat-fm-48k+dsd-neo-2.10.0",
                    "part_samples": self.settings.audio.max_recording_seconds * 16000,
                    "dmr_publication_policy": 2,
                },
            )
            force = True
        if force or self.checked_ms - self.checkpoint_ms >= 1000:
            self.journal.checkpoint(
                self.timeline,
                state,
                decoder_evidence={
                    "sync_counts": self.digital_metadata.get("sync_counts", {}),
                    "invalid_counts": self.digital_metadata.get("invalid_counts", {}),
                    "encryption_indicated": self.encrypted_call,
                    "input_mode": self.settings.digital.input_mode,
                    "input_level": self.digital_metadata.get("input_level", {}),
                    "dmr_direct_mono": self.digital_metadata.get("dmr_direct_mono", False),
                    "selection_evidence": self.digital_metadata.get("selection_evidence", {}),
                    "worker_evidence": self.digital_metadata.get(
                        "worker_evidence", [worker_summary(self.digital_metadata)]
                    ),
                },
                **extra,
            )
            self.checkpoint_ms = self.checked_ms

    def _check_encryption(self) -> None:
        # Upstream may hunt false protocols on post-carrier noise. Only an
        # indication associated with this voice protocol/epoch can veto its PCM.
        when = self.digital_metadata.get("encryption_at", {}).get(self.locked_protocol)
        if self.locked_protocol in {"TETRA", "DMR", "P25-II"} and when is not None:
            self.encrypted_call = True
        if when is not None and abs(when * 1000 - self.last_voice_ms) <= 500:
            self.encrypted_call = True

    def status(self) -> dict[str, Any]:
        return {
            **super().status(),
            "recorded_seconds": self.timeline.end / 8000
            if self.choice == "digital"
            else self.recorded_samples / 16000,
            "reception": self.choice or "checking",
            "protocol": self.locked_protocol,
            "digital_buffer_bytes": self.timeline.bytes,
        }
