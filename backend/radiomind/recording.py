import shutil
import struct
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np

from radiomind.config import Settings, Window
from radiomind.live_audio import LiveAudio
from radiomind.nfm import Audio
from radiomind.pcm import PCM_GAIN, pcm16
from radiomind.policy import require_audio
from radiomind.storage import Store


class Archive:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings, self.store = settings, store
        self.live_audio = LiveAudio()
        self.root = store.path.parent / f"{settings.source}-audio"
        self.root.mkdir(parents=True, exist_ok=True)
        self.staging_root = store.path.parent / f"{settings.source}-digital-staging"
        self.staging_root.mkdir(parents=True, exist_ok=True)
        from radiomind.deletion import retry_deletions

        retry_deletions(store, settings.source)
        self.recover()
        self.used_bytes = sum(p.stat().st_size for p in self.root.glob("*.wav"))
        self.reserved_bytes = 0
        from radiomind.digital_journal import recover_journals

        self.recovery_errors = recover_journals(self)

    def path(self, recording_id: str, partial: bool = False) -> Path:
        if UUID(recording_id).hex != recording_id:
            raise ValueError("Invalid recording ID")
        path = self.root / (recording_id + (".partial.wav" if partial else ".wav"))
        if path.resolve().parent != self.root.resolve():
            raise ValueError("Archive path escaped its root")
        return path

    def recover(self) -> None:
        # Only our indexed, unfinished PCM16 mono files. Never touch arbitrary files.
        for row in self.store.unfinished_recordings():
            if row["status"] != "recording":
                continue
            partial, final = self.path(row["id"], True), self.path(row["id"])
            if partial.exists():
                size = partial.stat().st_size
                with partial.open("r+b") as handle:
                    header = handle.read(44)
                    if size >= 44 and header[:4] == b"RIFF" and header[36:40] == b"data":
                        data_size = size - 44
                        handle.seek(4)
                        handle.write(struct.pack("<I", size - 8))
                        handle.seek(40)
                        handle.write(struct.pack("<I", data_size))
                        row["duration_seconds"] = data_size / 32000
                if not final.exists():
                    partial.rename(final)
            row.update(
                status="interrupted",
                end_reason="process_restart",
                discontinuity=True,
                playable=final.exists(),
            )
            self.store.save_recording(row)

    def reserve_check(self, bytes_needed: int) -> None:
        staged = sum(p.stat().st_size for p in self.staging_root.iterdir() if p.is_file())
        if (
            self.used_bytes + self.reserved_bytes + staged + bytes_needed
            > self.settings.audio.max_archive_mb * 1024**2
        ):
            raise RuntimeError("Archive quota reached; existing recordings were preserved")
        if shutil.disk_usage(self.root).free < self.reserved_bytes + bytes_needed + 50 * 1024**2:
            raise RuntimeError("Disk space low; recording stopped without deleting files")


class RecordingWriter:
    def __init__(
        self,
        archive: Archive,
        window: Window,
        frequency_hz: int,
        pre_roll: Audio,
        snr_db: float,
        *,
        session_id: str | None = None,
        part_number: int = 1,
        sample_offset: int = 0,
        start_utc: datetime | None = None,
    ) -> None:
        require_audio(archive.settings, window, frequency_hz)
        archive.reserve_check(44 + pre_roll.size * 2)
        self.archive = archive
        self.recording_id = session_id if session_id and part_number == 1 else uuid4().hex
        self.samples = 0
        self.limited_samples = 0
        self.input_peak = 0.0
        self.closed = False
        self.row: dict[str, Any] = {
            "id": self.recording_id,
            "frequency_hz": frequency_hz,
            "start_utc": (
                start_utc or datetime.now(UTC) - timedelta(seconds=len(pre_roll) / 16000)
            ).isoformat(),
            "session_id": session_id or self.recording_id,
            "part_number": part_number,
            "sample_offset": sample_offset,
            "source": archive.settings.source,
            "window": window.name,
            "status": "recording",
            "playable": False,
            "duration_seconds": 0,
            "sample_rate": 16000,
            "snr_db": snr_db,
            "speech_label": "speech_candidate",
            "dsp_version": "nfm-stream-v3-carrier-squelch",
            "vad_version": (
                "silero-v6.2-onnx+96ms-retention"
                if archive.settings.audio.vad_engine == "silero"
                else "webrtcvad-2.0.14+acoustic-v3-retention"
            ),
            "pcm_gain": PCM_GAIN,
            "discontinuity": False,
            "usb_continuity": "unknown",
        }
        archive.store.save_recording(self.row)
        self.file = wave.open(str(archive.path(self.recording_id, True)), "wb")
        self.file.setnchannels(1)
        self.file.setsampwidth(2)
        self.file.setframerate(16000)
        self.archive.used_bytes += 44
        self.write(pre_roll)

    def write(self, audio: Audio) -> None:
        self.archive.reserve_check(len(audio) * 2)
        if not np.all(np.isfinite(audio)):
            raise RuntimeError("Non-finite audio samples; capture stopped")
        pcm = pcm16(audio)
        self.file.writeframesraw(pcm.tobytes())
        if len(audio):
            self.input_peak = max(self.input_peak, float(np.max(np.abs(audio))))
            self.limited_samples += int(np.count_nonzero(np.abs(audio * PCM_GAIN) > 0.8))
        self.samples += len(audio)
        self.archive.used_bytes += len(audio) * 2

    def finish(self, reason: str, interrupted: bool = False) -> dict[str, Any]:
        if self.closed and interrupted:
            # A failure creating the next part must not leave the previous part
            # looking like a complete conversation. Preserve owner edits as well.
            self.row = self.archive.store.recording(self.recording_id) or self.row
            self.row.update(status="interrupted", end_reason=reason, discontinuity=True)
            self.archive.store.save_recording(self.row)
        if not self.closed:
            self.file.close()
            self.closed = True
            self.archive.path(self.recording_id, True).rename(self.archive.path(self.recording_id))
            existing = self.archive.store.recording(self.recording_id)
            if existing:
                for key in (
                    "title",
                    "review_label",
                    "review_source",
                    "reviewed_utc",
                    "favorite",
                    "listened",
                    "listened_utc",
                ):
                    if key in existing:
                        self.row[key] = existing[key]
            self.row.update(
                duration_seconds=self.samples / 16000,
                status="interrupted" if interrupted else "ready",
                playable=True,
                end_reason=reason,
                discontinuity=interrupted,
                end_utc=(
                    datetime.fromisoformat(self.row["start_utc"])
                    + timedelta(seconds=self.samples / 16000)
                ).isoformat(),
                finalized_utc=datetime.now(UTC).isoformat(),
                input_peak=self.input_peak,
                limited_fraction=self.limited_samples / max(self.samples, 1),
                sample_count=self.samples,
            )
            self.archive.store.save_recording(self.row)
        return self.row
