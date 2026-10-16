"""Private, durable PCM staging. Only finalized/recovered calls enter the archive."""

import json
import os
import sqlite3
import wave
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import numpy as np

from radiomind.config import Window
from radiomind.digital import MODES, AudioPacket
from radiomind.digital_mirror import mirrored_slot
from radiomind.digital_timeline import DigitalTimeline
from radiomind.pcm import pcm16
from radiomind.policy import require_audio
from radiomind.recording import Archive


class DigitalJournal:
    """One SQLite file per selected call, FULL synchronous rollback transactions.

    A checkpoint contains both PCM and its eligibility metadata. An active call
    is not an archive recording and is never submitted to ASR. Publication IDs
    derive from the capture UUID, slot and part; retries preserve existing files.
    """

    def __init__(self, archive: Archive, metadata: dict[str, Any]) -> None:
        self.archive = archive
        self.metadata = metadata
        capture = metadata["capture_group"]
        if UUID(capture).hex != capture:
            raise ValueError("Invalid digital capture ID")
        self.path = archive.staging_root / f"{capture}.sqlite3"
        archive.reserve_check(32768)
        # Never adopt/overwrite another active capture.
        with self.path.open("xb"):
            pass
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(
            "CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);"
            "CREATE TABLE packets (id INTEGER PRIMARY KEY, at REAL NOT NULL, pcm BLOB NOT NULL, "
            "slot INTEGER, sample_offset INTEGER);"
        )
        self.saved = 0
        self.closed = False

    def checkpoint(self, timeline: DigitalTimeline, state: str = "active", **extra: Any) -> None:
        pending = timeline.packets[self.saved :]
        # Includes rollback pages and page overhead, in addition to current files.
        self.archive.reserve_check(sum(len(p.pcm) + 128 for _, p in pending) * 2 + 32768)
        metadata = {**self.metadata, **extra, "state": state, "version": 2}
        try:
            self.db.executemany(
                "INSERT INTO packets(at,pcm,slot,sample_offset) VALUES(?,?,?,?)",
                [(p.input_seconds, p.pcm, p.slot, p.sample_offset) for _, p in pending],
            )
            self.db.execute(
                "INSERT INTO metadata VALUES(1,?) ON CONFLICT(id) "
                "DO UPDATE SET payload=excluded.payload",
                (json.dumps(metadata, allow_nan=False),),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.saved = len(timeline.packets)
        self.metadata = metadata

    def block(self) -> None:
        # Commit the veto without requiring additional archive quota. A restart
        # must not publish earlier checkpoints after late encryption metadata.
        metadata = {**self.metadata, "state": "blocked", "version": 2}
        self.db.execute("UPDATE metadata SET payload=? WHERE id=1", (json.dumps(metadata),))
        self.db.commit()
        self.metadata = metadata

    def close(self) -> None:
        if not self.closed:
            self.db.close()
            self.closed = True

    def discard(self) -> None:
        self.close()
        retire(self.path)


def retire(path: Path) -> None:
    # Closed, consumed application journal only. SQLite may retain a non-hot
    # rollback sidecar after a process exits before its first page write.
    path.with_name(path.name + "-journal").unlink(missing_ok=True)
    path.unlink()


def publish(archive: Archive, metadata: dict[str, Any], timeline: DigitalTimeline) -> None:
    """Durable atomic files before indexing; retry after any publication boundary."""
    window = Window.model_validate(metadata["window"])
    frequency = int(metadata["frequency_hz"])
    require_audio(archive.settings, window, frequency)
    if metadata["source"] != archive.settings.source:
        raise ValueError("Digital journal source does not match this profile")
    capture = UUID(metadata["capture_group"])
    start = datetime.fromisoformat(metadata["start_utc"])
    interrupted = metadata["state"] == "active" or metadata.get("interrupted", False)
    reason = "process_restart" if metadata["state"] == "active" else metadata["reason"]
    limit = archive.settings.audio.max_recording_seconds * 16000
    # Freeze part boundaries in the journal, independently of later config edits.
    limit = int(metadata.get("part_samples", limit))
    if not 160000 <= limit <= 9600000:
        raise ValueError("Invalid digital journal part size")
    tracks = timeline.tracks()
    single_slot = mirrored_slot(metadata, tracks)
    mirrored_direct = (
        metadata["protocol"] == "DMR"
        and metadata.get("decoder_evidence", {}).get("dmr_direct_mono") is True
        and len(tracks) == 2
        and np.array_equal(tracks[0][1], tracks[1][1])
    )
    if mirrored_direct:
        tracks = tracks[:1]
    elif single_slot is not None:
        tracks = [(slot, audio) for slot, audio in tracks if slot == single_slot]
    if metadata["protocol"] not in {"DMR", "P25-II", "TETRA"}:
        # Upstream repeats FDMA audio into both output channels in auto mode.
        tracks = tracks[:1]
    for slot, audio in tracks:
        if slot in metadata.get("excluded_slots", []):
            continue
        session = uuid5(capture, f"slot:{slot}").hex
        for offset in range(0, len(audio), limit):
            part = offset // limit + 1
            recording_id = session if part == 1 else uuid5(capture, f"slot:{slot}:part:{part}").hex
            pcm = pcm16(audio[offset : offset + limit]).tobytes()
            final = archive.path(recording_id)
            existing = archive.store.recording(recording_id)
            if existing:
                if existing.get("digital_journal_id") != capture.hex or not final.exists():
                    raise RuntimeError("Digital publication conflicts with an existing recording")
            if final.exists():
                # Crash between rename and index commit: verify exact contents.
                with wave.open(str(final), "rb") as reader:
                    if (
                        reader.getnchannels() != 1
                        or reader.getsampwidth() != 2
                        or reader.getframerate() != 16000
                        or reader.getnframes() * 2 != len(pcm)
                        or reader.readframes(reader.getnframes()) != pcm
                    ):
                        raise RuntimeError("Digital publication file mismatch; original preserved")
                if existing:
                    # Already indexed parts are immutable, including owner labels.
                    continue
            else:
                archive.reserve_check(len(pcm) + 44)
                temporary = archive.staging_root / f"{recording_id}.wav.tmp"
                # A prior crash may leave only this unpublished, deterministic temp.
                with temporary.open("wb") as handle:
                    with wave.open(handle, "wb") as writer:
                        writer.setnchannels(1)
                        writer.setsampwidth(2)
                        writer.setframerate(16000)
                        writer.writeframes(pcm)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.rename(final)
                if os.name != "nt":
                    # Persist the rename on Linux too; Windows uses flushed files.
                    directory = os.open(archive.root, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                archive.used_bytes += len(pcm) + 44
            stamp = start + timedelta(seconds=offset / 16000)
            archive.store.save_recording(
                {
                    "id": recording_id,
                    "session_id": session,
                    "part_number": part,
                    "sample_offset": offset,
                    "start_utc": stamp.isoformat(),
                    "end_utc": (stamp + timedelta(seconds=len(pcm) / 32000)).isoformat(),
                    "finalized_utc": datetime.now(UTC).isoformat(),
                    "frequency_hz": frequency,
                    "source": metadata["source"],
                    "window": window.name,
                    "snr_db": metadata["snr_db"],
                    "sample_rate": 16000,
                    "sample_count": len(pcm) // 2,
                    "duration_seconds": len(pcm) / 32000,
                    "status": "interrupted" if interrupted else "ready",
                    "playable": True,
                    "discontinuity": bool(interrupted),
                    "end_reason": "part_rotation" if offset + limit < len(audio) else reason,
                    "protocol": metadata["protocol"],
                    "digital_slot": slot,
                    **({"digital_channel_layout": "direct_mono"} if mirrored_direct else {}),
                    **(
                        {"digital_channel_layout": "single_slot_mirror"}
                        if single_slot is not None and not mirrored_direct
                        else {}
                    ),
                    "capture_group": capture.hex,
                    "digital_journal_id": capture.hex,
                    "decode_status": "decoded_audio",
                    "decoder_evidence": metadata.get("decoder_evidence", {}),
                    "speech_label": "digital_voice_candidate",
                    "dsp_version": metadata.get("dsp_version", "flat-fm-48k+dsd-neo-2.10.0"),
                    "vad_version": "native-vocoder",
                    "timing_quality": "approximate_digital_gaps",
                    "usb_continuity": "unknown",
                    "encrypted": None,
                    "encryption_status": "not_confirmed",
                }
            )


def recover_journals(archive: Archive) -> list[str]:
    errors = []
    for path in sorted(archive.staging_root.glob("*.sqlite3")):
        try:
            if UUID(path.stem).hex != path.stem or path.is_symlink():
                raise ValueError("Invalid digital journal filename")
            if path.stat().st_size > 256 * 1024**2:
                raise ValueError("Digital journal exceeds recovery size limit")
            if path.stat().st_size == 0:
                retire(path)  # Crash before database initialization; no PCM exists.
                continue
            with closing(sqlite3.connect(path)) as db:
                try:
                    row = db.execute("SELECT payload FROM metadata WHERE id=1").fetchone()
                    if not row:
                        if db.execute("SELECT count(*) FROM packets").fetchone()[0]:
                            raise ValueError("Digital journal PCM has no committed metadata")
                        db.close()
                        retire(path)  # No committed packet; nothing to publish.
                        continue
                    metadata = json.loads(row[0])
                    if metadata["version"] not in {1, 2} or metadata["capture_group"] != path.stem:
                        raise ValueError("Digital journal identity/version mismatch")
                    if metadata["state"] not in {"active", "ready", "blocked"}:
                        raise ValueError("Invalid digital journal state")
                    if metadata["state"] != "blocked":
                        if (
                            metadata["protocol"] not in {*MODES, "TETRA"}
                            or metadata["protocol"] == "auto"
                        ):
                            raise ValueError("Invalid digital journal protocol")
                        timeline = DigitalTimeline(128 * 1024**2)
                        fields = (
                            "at,pcm,slot,sample_offset"
                            if metadata["version"] == 2
                            else "at,pcm,NULL,NULL"
                        )
                        for at, pcm, slot, offset in db.execute(
                            f"SELECT {fields} FROM packets ORDER BY id"
                        ):
                            if len(pcm) not in {320, 640} or not np.isfinite(at) or at < 0:
                                raise ValueError("Invalid digital PCM packet")
                            timeline.append([AudioPacket(at, pcm, slot, offset)])
                        publish(archive, metadata, timeline)
                finally:
                    db.close()
            retire(path)  # Never archive WAVs.
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    return errors
