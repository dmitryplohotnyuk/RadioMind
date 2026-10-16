import wave
from pathlib import Path

import numpy as np
import pytest
from test_audio import audio_settings

from radiomind.digital import AudioPacket, Evidence, command
from radiomind.digital_conversation import DigitalTimeline, MultiModeConversation
from radiomind.nfm import NFMDemodulator
from radiomind.recording import Archive
from radiomind.storage import Store


def test_flat_discriminator_preserves_low_modulation_and_chunk_phase() -> None:
    rate = 8_000_000
    t = np.arange(800_000) / rate
    iq = np.exp(2j * np.pi * 2500 * np.cumsum(np.sin(2 * np.pi * 100 * t)) / rate).astype(
        np.complex64
    )
    whole, split = NFMDemodulator(0), NFMDemodulator(0)
    whole.digital_enabled = split.digital_enabled = True
    analog = whole.process(iq)
    pieces = []
    for start in range(0, len(iq), 131071):
        split.process(iq[start : start + 131071])
        pieces.append(split.digital_audio.copy())
    actual = np.concatenate(pieces)
    assert len(actual) == 4800
    np.testing.assert_allclose(actual, whole.digital_audio, atol=1e-6)
    assert np.std(actual[1000:]) > 0.6
    assert np.std(analog[400:]) < 0.04  # Voice bandpass must not feed a decoder.


def test_sync_is_not_voice_or_encryption_and_corrupt_sync_does_not_lock() -> None:
    evidence = Evidence()
    evidence.observe("NOTICE: Encrypted option")
    evidence.observe("12:00:00 Sync: +YSF FICH (CRC ERR)")
    evidence.observe("12:00:00 Sync: +YSF FICH (FEC ERR)")
    assert evidence.protocol is None and not evidence.encrypted
    evidence.observe("12:00:00 Sync: +DMR [SLOT1] slot2 | Color Code=02 | VC1")
    assert evidence.protocol is None
    evidence.observe("12:00:00 Sync: +DMR [SLOT1] slot2 | Color Code=02 | VC2")
    assert evidence.protocol == "DMR"
    evidence.observe("SLOT 1 ENC; ALG: 21;")
    evidence.observe("12:00:00 Sync: +DMR [SLOT1] slot2 | Color Code=02 | VC3")
    assert evidence.encrypted  # Late crypto metadata cannot revert to plaintext.


def test_bad_frame_changes_context_without_confirming_other_protocol():
    evidence = Evidence()
    evidence.observe("Sync: +DMR", 0.1)
    evidence.observe("Sync: +DMR", 0.2)
    evidence.observe("\x1b[31mSync: +YSF FICH (CRC ERR)\x1b[0m", 0.3)
    evidence.observe("Encrypted", 0.4)
    assert evidence.protocol is None  # Corrupt other-mode sync cannot keep the old label.
    assert "DMR" not in evidence.encryption_at
    assert evidence.invalid_counts == {"YSF": 1}
    evidence.observe("Sync: +DMR", 0.5)
    evidence.observe("Protected LC", 0.6)
    assert evidence.encryption_at["DMR"] == 0.6


def test_returning_protocol_requires_fresh_syncs_not_lifetime_counts():
    evidence = Evidence()
    for mode in ["DMR", "DMR", "NXDN96", "NXDN96"]:
        evidence.observe("Sync: +" + mode)
    assert evidence.protocol == "NXDN96"
    evidence.observe("Sync: +DMR")
    assert evidence.protocol is None and evidence.counts["DMR"] == 3
    evidence.observe("Sync: +DMR")
    assert evidence.protocol == "DMR" and evidence.context_syncs == 2


def test_dmr_direct_and_repeated_call_evidence_excludes_corruption_and_mixed_mode():
    evidence = Evidence()
    sync = "Sync: +DMR MS/DM MODE/MONO | Color Code=13 | VC*"
    call = " SLOT 1 TGT=100 SRC=22 Group Call"
    evidence.observe(sync + " FEC ERR")
    assert evidence.dmr_direct_frames == 0
    for _ in range(2):
        evidence.observe(sync)
        evidence.observe(call)
    assert evidence.dmr_direct_frames == 2 and evidence.dmr_call_repeats == 2
    assert not evidence.dmr_bs_seen
    evidence.observe(call + " CRC ERR")
    assert evidence.dmr_call_repeats == 2
    evidence.observe("SLOT 1 TGT=101 SRC=22 Private Call")
    assert evidence.dmr_call_repeats == 1
    evidence.observe("Sync: +DMR [SLOT1] slot2 | VC1 FEC ERR")
    evidence.observe(sync)
    assert evidence.dmr_bs_seen  # Later direct frames cannot erase BS evidence.
    evidence.observe("Sync: -M17 BRT")
    evidence.observe(call)
    assert evidence.dmr_call_repeats == 0


def test_process_command_has_fixed_local_boundaries() -> None:
    args = command(Path("decoder"), "DMR", 12345, 12346)
    assert args[args.index("-i") + 1] == "tcp:127.0.0.1:12345"
    assert args[args.index("-o") + 1] == "udp:127.0.0.1:12346"
    assert not set(args) & {"-q", "-K", "-k", "-H", "-T", "-U", "-fZ", "-8", "--config"}
    with pytest.raises(KeyError):
        command(Path("decoder"), "invalid", 12345, 12346)


def test_alternating_dmr_slots_confirm_independently_without_cross_slot_matches():
    e = Evidence()
    e.observe("Sync: +DMR [SLOT1] slot2 | VC1")
    e.observe("Sync: +DMR slot1 [SLOT2] | VC1")
    e.observe("SLOT 1 TGT=100 SRC=22 Group Call")
    e.observe("SLOT 2 TGT=100 SRC=22 Group Call")
    assert e.dmr_call_repeats == 1  # Same address on different slots is not repetition.
    e.observe("SLOT 2 TGT=200 SRC=33 Group Call")
    e.observe("SLOT 1 TGT=100 SRC=22 Group Call")
    assert e.dmr_call_repeats == 2
    e.observe("SLOT 2 TGT=200 SRC=33 Group Call")
    assert e.dmr_call_repeats == 2
    e.observe("Sync: +NXDN48")
    assert not e.dmr_calls and e.dmr_call_repeats == 0


def packet(at: float, channels: int = 2) -> AudioPacket:
    pcm = np.zeros((160, channels), dtype="<i2")
    pcm[:, 0] = 500
    if channels == 2:
        pcm[:, 1] = -1500
    return AudioPacket(at, pcm.tobytes())


def test_digital_timeline_keeps_gaps_and_distinct_slots_and_bounds_sparse_data() -> None:
    timeline = DigitalTimeline(1024 * 1024)
    timeline.append([packet(0.02), packet(0.04), packet(1.04)])
    tracks = timeline.tracks()
    assert len(tracks) == 2 and len(tracks[0][1]) == 16640
    assert np.mean(tracks[0][1][:500]) > 0
    assert np.mean(tracks[1][1][:500]) < 0
    assert np.max(np.abs(tracks[0][1][1000:15000])) == 0
    with pytest.raises(RuntimeError, match="quota"):
        timeline.append([packet(1000)])


class FakeDecoder:
    def __init__(self, executable, mode="auto", **kwargs):
        self.mode = mode
        self.error = None
        self.closed = False
        self.metadata = {"protocol": None, "encrypted": False, "sync_counts": {}}
        self.packets = []

    def check(self):
        if self.error:
            raise RuntimeError(self.error)

    def status(self):
        return self.metadata.copy()

    def drain(self):
        packets, self.packets = self.packets, []
        return packets

    def close(self):
        self.closed = True


def conversation(tmp_path, monkeypatch):
    monkeypatch.setattr("radiomind.digital_conversation.DigitalDispatch", FakeDecoder)
    settings = audio_settings()
    settings.digital.enabled = True
    store = Store(tmp_path / "test.sqlite3", 1000)
    conv = MultiModeConversation(
        settings,
        Archive(settings, store),
        settings.windows[0],
        145000000,
        20,
        mode=store.digital_mode(145000000),
    )
    return conv, store


def test_digital_hold_two_slots_archive_then_learn_format(tmp_path, monkeypatch) -> None:
    conv, store = conversation(tmp_path, monkeypatch)
    conv.digital.metadata.update(protocol="DMR", sync_counts={"DMR": 3}, invalid_counts={"DMR": 2})
    conv.digital.packets = [packet(0.02)]
    conv.consume([(np.zeros(320), False)])
    assert conv.state == "RECORD" and not store.recordings()
    for _ in range(10):
        conv.consume([(np.zeros(320), False)])
    assert not conv.done and conv.state == "HANG"
    conv.digital.packets = [packet(0.24)]
    conv.consume([(np.zeros(320), False)])
    for _ in range(21):
        conv.consume([(np.zeros(320), False)])
    rows = store.recordings()
    assert conv.done and len(rows) == 2 and conv.digital.closed
    assert {r["digital_slot"] for r in rows} == {1, 2}
    assert all(r["protocol"] == "DMR" and r["playable"] for r in rows)
    assert all(r["decoder_evidence"]["invalid_counts"] == {"DMR": 2} for r in rows)
    assert len({r["capture_group"] for r in rows}) == 1
    assert store.digital_mode(145000000) == "DMR"
    for row in rows:
        with wave.open(str(conv.archive.path(row["id"])), "rb") as audio:
            assert audio.getframerate() == 16000 and audio.getnframes() == 640
    store.close()


def test_new_protocol_does_not_inherit_previous_sync_label(tmp_path, monkeypatch):
    conv, store = conversation(tmp_path, monkeypatch)
    evidence = Evidence()
    evidence.observe("Sync: NXDN96")
    evidence.observe("Sync: NXDN96")
    assert evidence.protocol == "NXDN96"
    evidence.observe("Sync: +P25p1 NAC/CC: 293; HDU")
    assert evidence.protocol is None
    conv.digital.metadata.update(protocol=evidence.protocol, sync_counts=evidence.counts)
    conv.digital.packets = [packet(0.02)]
    conv.consume([(np.zeros(320), False)])
    assert conv.choice is None
    evidence.observe("Sync: +P25p1 NAC/CC: 293; LDU1")
    conv.digital.metadata.update(protocol=evidence.protocol, sync_counts=evidence.counts)
    conv.consume([(np.zeros(320), False)])
    assert conv.choice == "digital" and conv.locked_protocol == "P25-I"
    conv.finish("fixture_end")
    assert store.recordings() and all(r["protocol"] == "P25-I" for r in store.recordings())
    assert all(r["duration_seconds"] > 0 for r in store.recordings())
    store.close()


def test_late_encryption_suppresses_all_buffered_audio_and_asr(tmp_path, monkeypatch) -> None:
    conv, store = conversation(tmp_path, monkeypatch)
    conv.digital.metadata.update(protocol="DMR", sync_counts={"DMR": 2})
    conv.digital.packets = [packet(0.02)]
    conv.consume([(np.zeros(320), False)])
    conv.digital.metadata["encrypted"] = True
    conv.digital.metadata["encryption_at"] = {"DMR": 0.04}
    conv.consume([(np.zeros(320), False)])
    assert conv.done and not store.recordings()
    assert not list(conv.archive.root.glob("*.wav"))
    store.close()


@pytest.mark.parametrize("protocol", ["DMR", "P25-II"])
def test_early_tdma_crypto_header_cannot_escape_veto_after_decoder_latency(
    tmp_path, monkeypatch, protocol
):
    conv, store = conversation(tmp_path, monkeypatch)
    conv.digital.metadata.update(
        protocol=protocol, sync_counts={protocol: 3}, encryption_at={protocol: 0.1}
    )
    conv.checked_ms = 1500
    conv.digital.packets = [packet(1.52)]
    conv.consume([(np.zeros(320), False)])
    assert conv.encrypted_call and conv.done and not store.recordings()
    assert not conv.speech_found  # Suppressed crypto must count as a failed capture.
    attempts = store.digital_attempts()
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "encryption_indicated"
    assert attempts[0]["encryption_protocols"] == [protocol]
    assert attempts[0]["sync_counts"] == {protocol: 3}
    store.close()


def test_analog_selection_replays_pending_audio_without_losing_beginning(tmp_path, monkeypatch):
    conv, store = conversation(tmp_path, monkeypatch)
    for _ in range(40):
        conv.consume([(np.full(320, 0.1), True)], retention=[True], rf_active=[True])
    assert conv.choice == "analog" and conv.digital.closed
    assert conv.writer is not None and conv.writer.samples >= 11000
    conv.finish("owner_stop")
    assert len(store.recordings()) == 1 and store.recordings()[0]["playable"]
    store.close()


def test_no_sync_and_no_voice_never_enters_archive(tmp_path, monkeypatch):
    conv, store = conversation(tmp_path, monkeypatch)
    for _ in range(351):
        if not conv.done:
            conv.consume([(np.zeros(320), False)])
    assert conv.done and conv.digital.closed and not store.recordings()
    store.close()


def test_false_digital_metadata_on_noise_does_not_override_analog(tmp_path, monkeypatch):
    conv, store = conversation(tmp_path, monkeypatch)
    conv.digital.metadata.update(
        protocol="M17", encrypted=True, sync_counts={"M17": 6}, encryption_at={"M17": 0.2}
    )
    for _ in range(40):
        conv.consume([(np.full(320, 0.1), True)], retention=[True], rf_active=[True])
    assert conv.choice == "analog" and conv.writer is not None
    conv.finish("owner_stop")
    assert len(store.recordings()) == 1
    store.close()


def test_post_carrier_false_encryption_does_not_erase_completed_voice(tmp_path, monkeypatch):
    conv, store = conversation(tmp_path, monkeypatch)
    conv.settings.audio.hang_ms = 6000
    conv.digital.metadata.update(protocol="DMR", sync_counts={"DMR": 3})
    conv.digital.packets = [packet(0.02)]
    conv.consume([(np.zeros(320), False)])
    for _ in range(60):
        conv.consume([(np.zeros(320), False)])
    conv.digital.metadata.update(protocol="M17", encrypted=True, encryption_at={"M17": 1.2})
    conv.consume([(np.zeros(320), False)])
    conv.finish("owner_stop")
    assert len(store.recordings()) == 2
    assert all(row["protocol"] == "DMR" for row in store.recordings())
    store.close()


def test_analog_speech_after_long_probe_is_not_rejected_by_old_verify_deadline(
    tmp_path, monkeypatch
):
    conv, store = conversation(tmp_path, monkeypatch)
    for _ in range(150):
        conv.consume([(np.zeros(320), False)], retention=[False], rf_active=[True])
    conv.consume([(np.full(320, 0.1), True)], retention=[True], rf_active=[True])
    assert conv.choice == "analog" and not conv.done and conv.writer is not None
    conv.finish("owner_stop")
    assert len(store.recordings()) == 1 and store.recordings()[0]["playable"]
    store.close()
