import base64
import json
import queue
import socket
import struct
import threading

import numpy as np
import pytest
from test_digital_recovery import journal_fixture

from radiomind.digital import AudioPacket, DigitalDecoder
from radiomind.digital_journal import DigitalJournal, recover_journals
from radiomind.digital_timeline import DigitalTimeline
from radiomind.nfm import NFMDemodulator
from radiomind.tetra import DigitalDispatch, TetraDecoder
from radiomind.tetra_dsp import TetraDemodulator, rrc_taps


def test_complex_channelizer_is_chunk_invariant_and_rejects_adjacent_channel():
    t = np.arange(800_000) / 8_000_000
    iq = np.exp(2j * np.pi * (1_000_000 + 4000) * t).astype(np.complex64)
    whole, split = NFMDemodulator(1_000_000), NFMDemodulator(1_000_000)
    whole.digital_iq_enabled = split.digital_iq_enabled = True
    whole.process(iq)
    pieces = []
    for at in range(0, len(iq), 73117):
        split.process(iq[at : at + 73117])
        pieces.append(split.digital_iq.copy())
    actual = np.concatenate(pieces)
    assert len(actual) == 4800
    np.testing.assert_allclose(actual, whole.digital_iq, atol=2e-5)
    phase = np.angle(actual[1001:] * actual[1000:-1].conj()).mean()
    assert phase * 48000 / (2 * np.pi) == pytest.approx(4000, abs=1)
    reject = NFMDemodulator(1_000_000)
    reject.digital_iq_enabled = True
    reject.process(np.exp(2j * np.pi * 1_080_000 * t).astype(np.complex64))
    assert np.std(reject.digital_iq[1000:]) < np.std(actual[1000:]) / 1000


def test_virtual_rtl_commands_never_accept_a_retune_or_other_rate():
    worker = DigitalDecoder.__new__(DigitalDecoder)
    worker.error = None
    worker.stopping = threading.Event()
    worker.rate_ready = threading.Event()
    worker.connection, peer = socket.socketpair()
    thread = threading.Thread(target=worker._commands)
    thread.start()
    try:
        command = struct.pack(">BI", 2, 1536000)
        peer.sendall(command[:2])
        peer.sendall(command[2:])
        assert worker.rate_ready.wait(1) and worker.error is None
        peer.sendall(struct.pack(">BI", 1, 145000000))
        thread.join(1)
        assert worker.error and "unsupported" in worker.error
    finally:
        worker.stopping.set()
        peer.close()
        worker.connection.close()
        thread.join(1)


def tetra_event_reader():
    reader = TetraDecoder.__new__(TetraDecoder)
    reader.syncs = 2
    reader.error = None
    reader.input_samples = 0
    reader.encryption_at = {}
    reader.frame_origin = reader.frame_last = None
    reader.frame_epoch = 0
    reader.outputs = queue.Queue(512)
    return reader


def frame(slot=1, fn=1, mn=1):
    return {
        "type": "audio",
        "slot": slot,
        "fn": fn,
        "mn": mn,
        "pcm": base64.b64encode(np.full(480, 100 * slot, dtype="<i2").tobytes()).decode(),
    }


def test_tetra_four_slots_share_clock_and_multiframe_wrap():
    reader = tetra_event_reader()
    for slot in range(1, 5):
        reader.accept(frame(slot, 17, 60))
    reader.accept(frame(1, 1, 1))
    timeline = DigitalTimeline(100000)
    timeline.append(reader.drain())
    assert timeline.end == 960  # 120ms, not four times longer.
    assert [slot for slot, _ in timeline.tracks()] == [1, 2, 3, 4]
    assert [len(audio) for _, audio in timeline.tracks()] == [1920] * 4
    reader.accept(frame(1, 2, 1))
    with pytest.raises(ValueError, match="backwards"):
        reader.accept(frame(1, 1, 1))


def test_tetra_crypto_veto_and_invalid_message_cannot_produce_audio():
    reader = tetra_event_reader()
    reader.syncs = 1
    reader.accept(frame())
    assert not reader.drain()
    reader.syncs = 2
    with pytest.raises(ValueError):
        reader.accept(frame(slot=5))
    with pytest.raises(ValueError):
        reader.accept(frame(fn=18))
    reader.accept({"type": "encrypted", "slot": 2})
    reader.accept(frame())
    assert not reader.drain() and reader.status()["encrypted"]


def test_dispatch_keeps_early_pcm_and_never_mixes_workers():
    from test_digital import FakeDecoder, packet

    first, second = FakeDecoder(None), FakeDecoder(None)
    dispatch = DigitalDispatch.__new__(DigitalDispatch)
    dispatch.workers, dispatch.selected = [first, second], None
    dispatch.dmr_probe = None
    dispatch.selected_protocol = None
    dispatch.tail, dispatch.pending = [], {}
    first.packets = [packet(0.02)]
    assert not dispatch.drain()  # PCM before repeated protocol evidence stays private.
    first.metadata["protocol"] = "DMR"
    first.metadata["dmr_call_confirmed"] = True
    second.metadata["protocol"] = "TETRA"
    second.packets = [packet(0.04)]
    result = dispatch.drain()
    assert len(result) == 1 and result[0].input_seconds == 0.02
    assert dispatch.selected is first and second.closed
    first.packets = [packet(0.06)]
    dispatch.close()
    assert len(dispatch.drain()) == 1
    assert not dispatch.drain()


def test_four_slot_journal_recovery_and_legacy_schema(tmp_path):
    archive, metadata, _ = journal_fixture(tmp_path)
    timeline = DigitalTimeline(100000)
    timeline.append(
        [AudioPacket(0.1, np.full(160, s * 100, dtype="<i2").tobytes(), s, 0) for s in range(1, 5)]
    )
    metadata["protocol"] = "TETRA"
    journal = DigitalJournal(archive, metadata)
    journal.checkpoint(timeline)
    journal.close()
    assert not recover_journals(archive)
    assert len(archive.store.recordings()) == 4
    archive.store.close()

    archive, metadata, timeline = journal_fixture(tmp_path / "legacy")
    journal = DigitalJournal(archive, metadata)
    journal.checkpoint(timeline)
    old = {**journal.metadata, "version": 1}
    journal.db.execute("UPDATE metadata SET payload=?", (json.dumps(old),))
    journal.db.execute("ALTER TABLE packets DROP COLUMN slot")
    journal.db.execute("ALTER TABLE packets DROP COLUMN sample_offset")
    journal.db.commit()
    journal.close()
    assert not recover_journals(archive)
    assert len(archive.store.recordings()) == 2
    archive.store.close()


def modulate_tetra(bits, frequency=0):
    from scipy.signal import upfirdn

    pairs = bits.reshape(-1, 2)
    angles = np.where(pairs[:, 0], -1, 1) * np.where(pairs[:, 1], 3, 1) * np.pi / 4
    symbols = np.exp(1j * np.cumsum(angles))
    shaped = upfirdn(rrc_taps(8, 161), symbols, up=8)[::3]
    return (shaped * np.exp(2j * np.pi * frequency * np.arange(len(shaped)) / 48000)).astype(
        np.complex64
    )


@pytest.mark.parametrize("frequency", [0, 500, -700])
def test_tetra_symbol_recovery_with_frequency_offset_and_arbitrary_chunks(frequency):
    bits = np.random.default_rng(123).integers(0, 2, 24000, dtype=np.uint8)
    samples = modulate_tetra(bits, frequency)
    decoder, whole = TetraDemodulator(), TetraDemodulator()
    result = b"".join(decoder.process(samples[i : i + 731]) for i in range(0, len(samples), 731))
    assert result == whole.process(samples)
    actual = np.frombuffer(result, dtype=np.uint8)
    # Matched filters introduce a fixed 44-bit delay for this synthetic pulse.
    np.testing.assert_array_equal(actual[2044:23044], bits[2000:23000])
