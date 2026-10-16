import json
import subprocess
import sys
import wave
from uuid import uuid4

import numpy as np
import pytest
from test_audio import audio_settings
from test_digital import conversation, packet

from radiomind.digital import AudioPacket
from radiomind.digital_journal import DigitalJournal, publish, recover_journals
from radiomind.digital_timeline import DigitalTimeline
from radiomind.pcm import pcm16
from radiomind.recording import Archive
from radiomind.storage import Store


def journal_fixture(tmp_path):
    settings = audio_settings()
    archive = Archive(settings, Store(tmp_path / "test.sqlite3", 1000))
    metadata = {
        "capture_group": uuid4().hex,
        "source": "mock",
        "window": settings.windows[0].model_dump(),
        "frequency_hz": 145000000,
        "start_utc": "2026-10-14T12:00:00+00:00",
        "snr_db": 20,
        "protocol": "DMR",
        "part_samples": 160000,
    }
    timeline = DigitalTimeline(1024 * 1024)
    timeline.append([packet(0.02), packet(0.04), packet(1.04)])
    return archive, metadata, timeline


@pytest.mark.parametrize(
    "confirmed,identical,expected", [(True, True, 1), (False, True, 2), (True, False, 2)]
)
@pytest.mark.parametrize("recover", [False, True])
def test_direct_mono_publication_requires_evidence_and_exact_complete_tracks(
    tmp_path, confirmed, identical, expected, recover
):
    archive, metadata, _ = journal_fixture(tmp_path)
    timeline = DigitalTimeline(1024 * 1024)
    a = np.tile(np.array([500, 500], dtype="<i2"), (160, 1))
    b = a.copy()
    if not identical:
        b[-1, 1] += 1  # Even a single changed sample must preserve both slots.
    timeline.append([AudioPacket(0.02, a.tobytes()), AudioPacket(0.04, b.tobytes())])
    if confirmed:
        metadata["decoder_evidence"] = {"dmr_direct_mono": True}
    journal = DigitalJournal(archive, metadata)
    journal.checkpoint(timeline, "ready", reason="fixture_end")
    journal.close()
    try:
        if recover:
            assert recover_journals(archive) == []
        else:
            publish(archive, journal.metadata, timeline)
        rows = archive.store.recordings()
        assert len(rows) == expected
        assert {r["digital_slot"] for r in rows} == ({1} if expected == 1 else {1, 2})
        if expected == 1:
            assert rows[0]["digital_channel_layout"] == "direct_mono"
    finally:
        archive.store.close()


def test_abrupt_process_exit_recovers_committed_slots_and_gap_only(tmp_path):
    archive, metadata, timeline = journal_fixture(tmp_path)
    config = tmp_path / "capture.json"
    config.write_text(
        json.dumps({"settings": archive.settings.model_dump(), "metadata": metadata}),
        encoding="utf-8",
    )
    code = """
import json, os, sys
from pathlib import Path
import numpy as np
from radiomind.config import Settings
from radiomind.digital import AudioPacket
from radiomind.digital_journal import DigitalJournal
from radiomind.digital_timeline import DigitalTimeline
from radiomind.recording import Archive
from radiomind.storage import Store
p = Path(sys.argv[1])
config = json.loads(p.read_text(encoding='utf-8'))
archive = Archive(Settings.model_validate(config['settings']), Store(p.parent/'child.sqlite3',1000))
timeline = DigitalTimeline(1024*1024)
pcm = np.tile(np.array([500,-1500], dtype='<i2'), (160,1)).tobytes()
timeline.append([AudioPacket(at,pcm) for at in [0.02,0.04,1.04]])
journal = DigitalJournal(archive, config['metadata'])
journal.checkpoint(timeline)
# This final packet has not committed: simulate a hard process exit, no finally.
journal.db.execute('INSERT INTO packets(at,pcm) VALUES(?,?)', (1.06,pcm))
os._exit(23)
"""
    result = subprocess.run([sys.executable, "-c", code, str(config)], timeout=30)
    assert result.returncode == 23
    recovered = Archive(archive.settings, archive.store)
    assert not recovered.recovery_errors
    rows = sorted(archive.store.recordings(), key=lambda row: row["digital_slot"])
    assert len(rows) == 2
    for row, (_, expected) in zip(rows, timeline.tracks(), strict=True):
        assert row["status"] == "interrupted" and row["end_reason"] == "process_restart"
        assert row["discontinuity"] and row["sample_count"] == 16640
        with wave.open(str(recovered.path(row["id"])), "rb") as reader:
            assert reader.readframes(reader.getnframes()) == pcm16(expected).tobytes()
    Archive(archive.settings, archive.store)
    assert len(archive.store.recordings()) == 2
    assert not list(recovered.staging_root.iterdir())
    archive.store.close()


@pytest.mark.parametrize("boundary", ["after_rename", "after_first_index"])
def test_publication_failure_retries_without_duplicates_or_rewriting_owner_edits(
    tmp_path, monkeypatch, boundary
):
    archive, metadata, timeline = journal_fixture(tmp_path)
    journal = DigitalJournal(archive, metadata)
    journal.checkpoint(timeline, "ready", reason="owner_stop", interrupted=False)
    original = archive.store.save_recording
    calls = 0

    def fail(row):
        nonlocal calls
        calls += 1
        if boundary == "after_first_index":
            original({**row, "favorite": True, "review_label": "speech"})
        raise OSError("simulated power boundary")

    monkeypatch.setattr(archive.store, "save_recording", fail)
    with pytest.raises(OSError):
        publish(archive, journal.metadata, timeline)
    assert calls == 1
    journal.close()
    first = next(archive.root.glob("*.wav"))
    original_bytes, modified = first.read_bytes(), first.stat().st_mtime_ns
    monkeypatch.setattr(archive.store, "save_recording", original)
    recovered = Archive(archive.settings, archive.store)
    assert not recovered.recovery_errors
    assert len(archive.store.recordings()) == 2
    assert first.read_bytes() == original_bytes and first.stat().st_mtime_ns == modified
    if boundary == "after_first_index":
        assert archive.store.recording(first.stem)["favorite"]
    archive.store.close()


def test_late_veto_persists_across_restart_without_publication(tmp_path):
    archive, metadata, timeline = journal_fixture(tmp_path)
    journal = DigitalJournal(archive, metadata)
    journal.checkpoint(timeline)
    journal.block()
    journal.close()  # crash before transient cleanup
    recovered = Archive(archive.settings, archive.store)
    assert not recovered.recovery_errors
    assert not archive.store.recordings() and not list(archive.root.glob("*.wav"))
    assert not list(archive.staging_root.iterdir())
    archive.store.close()


def test_quota_preserves_checkpoint_and_retry_recovers(tmp_path):
    archive, metadata, timeline = journal_fixture(tmp_path)
    journal = DigitalJournal(archive, metadata)
    journal.checkpoint(timeline)
    journal.close()
    archive.reserved_bytes = archive.settings.audio.max_archive_mb * 1024**2
    assert recover_journals(archive)
    assert journal.path.exists() and not archive.store.recordings()
    archive.reserved_bytes = 0
    assert not recover_journals(archive)
    assert len(archive.store.recordings()) == 2
    archive.store.close()


def test_permission_change_and_corrupt_journal_preserve_data_and_report(tmp_path):
    archive, metadata, timeline = journal_fixture(tmp_path)
    journal = DigitalJournal(archive, metadata)
    journal.checkpoint(timeline)
    journal.close()
    archive.settings.audio.enabled = False
    assert "not authorized" in recover_journals(archive)[0]
    assert journal.path.exists() and not archive.store.recordings()
    archive.settings.audio.enabled = True
    assert not recover_journals(archive)
    corrupt = archive.staging_root / f"{uuid4().hex}.sqlite3"
    corrupt.write_bytes(b"invalid database")
    assert recover_journals(archive) and corrupt.read_bytes() == b"invalid database"
    archive.store.close()


def test_live_checkpoint_intervals_and_two_slot_rotation(tmp_path, monkeypatch):
    conv, store = conversation(tmp_path, monkeypatch)
    conv.settings.audio.max_recording_seconds = 10
    conv.digital.metadata.update(protocol="DMR", sync_counts={"DMR": 3})
    for index in range(1100):
        conv.digital.packets = [packet((index + 1) * 0.02)]
        conv.consume([(np.zeros(320), False)])
        assert conv.journal is not None
        assert len(conv.timeline.packets) - conv.journal.saved < 50
    assert not store.recordings()  # Staging never enters playback/Whisper.
    conv.finish("owner_stop")
    rows = store.recordings()
    assert len(rows) == 6
    assert {row["part_number"] for row in rows} == {1, 2, 3}
    assert sum(row["sample_count"] for row in rows) == 1100 * 320 * 2
    assert not list(conv.archive.staging_root.iterdir())
    store.close()


def test_no_staged_sound_on_encrypted_first_packet(tmp_path, monkeypatch):
    conv, store = conversation(tmp_path, monkeypatch)
    conv.digital.metadata.update(protocol="DMR", encryption_at={"DMR": 0.02})
    conv.digital.packets = [packet(0.02)]
    conv.consume([(np.zeros(320), False)])
    assert conv.done and not store.recordings()
    assert not list(conv.archive.staging_root.iterdir())
    store.close()


def test_failure_before_first_checkpoint_has_nothing_to_recover(tmp_path):
    archive, metadata, _ = journal_fixture(tmp_path)
    journal = DigitalJournal(archive, metadata)
    journal.close()
    assert not recover_journals(archive)
    assert not list(archive.staging_root.iterdir())
    archive.store.close()


def test_failed_veto_commit_still_discards_only_unpublished_staging(tmp_path, monkeypatch):
    conv, store = conversation(tmp_path, monkeypatch)
    conv.digital.metadata.update(protocol="DMR")
    conv.digital.packets = [packet(0.02)]
    conv.consume([(np.zeros(320), False)])

    def fail():
        raise OSError("disk error while persisting veto")

    monkeypatch.setattr(conv.journal, "block", fail)
    conv.digital.metadata["encryption_at"] = {"DMR": 0.04}
    with pytest.raises(OSError, match="disk error"):
        conv.consume([(np.zeros(320), False)])
    assert not store.recordings() and not list(conv.archive.staging_root.iterdir())
    assert not Archive(conv.settings, store).recovery_errors
    store.close()


def test_conflicting_final_file_is_never_replaced(tmp_path):
    archive, metadata, timeline = journal_fixture(tmp_path)
    journal = DigitalJournal(archive, metadata)
    journal.checkpoint(timeline, "ready", reason="owner_stop", interrupted=False)
    publish(archive, journal.metadata, timeline)
    journal.close()
    final = next(archive.root.glob("*.wav"))
    final.write_bytes(b"owner file changed outside application")
    errors = recover_journals(archive)
    assert errors and final.read_bytes() == b"owner file changed outside application"
    assert journal.path.exists()
    archive.store.close()


def test_first_decoded_audio_and_encryption_at_worker_close_are_not_published(
    tmp_path, monkeypatch
):
    conv, store = conversation(tmp_path, monkeypatch)

    def final_batch():
        conv.digital.metadata.update(protocol="DMR", encryption_at={"DMR": 3.0})
        conv.digital.packets = [packet(3.0)]

    monkeypatch.setattr(conv.digital, "close", final_batch)
    conv.finish("owner_stop")
    assert conv.done and conv.encrypted_call and not store.recordings()
    assert not list(conv.archive.staging_root.iterdir())
    store.close()
