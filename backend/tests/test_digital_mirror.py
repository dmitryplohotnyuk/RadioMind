import wave

import numpy as np
import pytest
from test_digital_recovery import journal_fixture

from radiomind.digital import AudioPacket
from radiomind.digital_journal import DigitalJournal, publish, recover_journals
from radiomind.digital_mirror import mirrored_slot
from radiomind.digital_timeline import DigitalTimeline
from radiomind.pcm import pcm16


def evidence(slot):
    return {
        "protocol": "DMR",
        "dmr_publication_policy": 2,
        "decoder_evidence": {
            "selection_evidence": {"protocol": "DMR", "dmr_call_confirmed": True},
            "worker_evidence": [{"dmr_frames": {"slots": {str(slot): {"voice_burst": 30}}}}],
        },
    }


@pytest.mark.parametrize("slot", [1, 2])
@pytest.mark.parametrize("recover", [False, True])
def test_single_voiced_slot_mirror_preserves_original_pcm_and_recovers(tmp_path, slot, recover):
    archive, metadata, _ = journal_fixture(tmp_path)
    metadata.update(evidence(slot))
    timeline = DigitalTimeline(1024 * 1024)
    a = np.tile(np.array([1000, 1000], dtype="<i2"), (160, 1))
    # A tiny native transition residual, not a second conversation.
    b = a.copy()
    b[80, 2 - slot] += 2
    timeline.append([AudioPacket(i * 0.02, (b if i == 40 else a).tobytes()) for i in range(100)])
    expected = pcm16(dict(timeline.tracks())[slot]).tobytes()
    journal = DigitalJournal(archive, metadata)
    journal.checkpoint(timeline, "ready", reason="fixture_end")
    journal.close()
    try:
        if recover:
            assert recover_journals(archive) == []
        else:
            publish(archive, journal.metadata, timeline)
            publish(archive, journal.metadata, timeline)  # Idempotent retry.
        rows = archive.store.recordings()
        assert len(rows) == 1 and rows[0]["digital_slot"] == slot
        assert rows[0]["digital_channel_layout"] == "single_slot_mirror"
        with wave.open(str(archive.path(rows[0]["id"])), "rb") as reader:
            assert reader.readframes(reader.getnframes()) == expected
    finally:
        archive.store.close()


@pytest.mark.parametrize(
    "case",
    [
        "legacy",
        "unconfirmed",
        "dual_voice",
        "unknown_voice",
        "different",
        "sparse_loud",
        "short",
        "missing",
        "zero",
    ],
)
def test_uncertain_and_distinct_tracks_are_never_folded(case):
    metadata = evidence(1)
    a = np.full(32000, 0.1)
    b = a.copy()
    slots = metadata["decoder_evidence"]["worker_evidence"][0]["dmr_frames"]["slots"]
    if case == "legacy":
        del metadata["dmr_publication_policy"]
    elif case == "unconfirmed":
        metadata["decoder_evidence"]["selection_evidence"] = {}
    elif case in {"dual_voice", "unknown_voice"}:
        slots["2" if case == "dual_voice" else "unknown"] = {"voice_header": 1}
    elif case == "different":
        b[100:420] *= -1  # Even a short distinct fragment prevents folding.
    elif case == "sparse_loud":
        b[100] = 1.0
    elif case == "short":
        a, b = a[:100], b[:100]
    elif case == "missing":
        slots.clear()
    elif case == "zero":
        a[:], b[:] = 0, 0
    assert mirrored_slot(metadata, [(1, a), (2, b)]) is None
