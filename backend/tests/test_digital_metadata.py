"""Pinned upstream log shapes; synthetic fields, no RF/identity fixtures."""

import json

import pytest
from test_digital import conversation, packet

from radiomind.digital import Evidence
from radiomind.digital_metadata import frame_summary, worker_summary


def context() -> Evidence:
    evidence = Evidence()
    evidence.observe("Sync: +DMR [SLOT1] slot2 | Color Code=01 | IDLE", 1.0)
    evidence.observe("Sync: +DMR [SLOT1] slot2 | Color Code=01 | IDLE", 1.1)
    return evidence


def pi(alg="21", family="DMRA RC4;", mi="12345678", width=32) -> str:
    return f"Slot 2 DMR PI H- ALG ID: {alg}; KEY ID: 01; MI({width}): {mi}; {family}"


@pytest.mark.parametrize(
    "alg,family",
    [
        ("21", "DMRA RC4;"),
        ("22", "DMRA DES;"),
        ("24", "DMRA AES-128;"),
        ("25", "DMRA AES-256;"),
        ("01", "DMRA Compatible RC4;"),
    ],
)
def test_complete_checked_family_indication_is_retained_without_identifiers(alg, family):
    e = context()
    e.observe("\x1b[33m" + pi(alg, family) + " \x1b[0m ", 1.2)
    assert e.encrypted and e.encryption_at == {"DMR": 1.2}
    result = e.dmr_frames.snapshot()
    assert result["slots"]["2"]["crypto_header"] == 1
    encoded = json.dumps(result)
    assert "KEY ID" not in encoded and "12345678" not in encoded and "TGT" not in encoded


@pytest.mark.parametrize("suffix", [" CRC ERR", " FEC ERR", " (Checksum Err);", " G24 ERR"])
def test_corrupt_privacy_header_does_not_mute(suffix):
    e = context()
    e.observe(pi() + suffix, 1.2)
    assert not e.encrypted
    assert e.invalid_counts["DMR"] == 1
    assert e.dmr_frames.snapshot()["slots"]["2"]["invalid"] == 1


@pytest.mark.parametrize(
    "line",
    [
        pi("00", "DMRA;"),
        pi("FF", "DMRA AES-256;"),
        pi("21", "DMRA AES-256;"),
        pi(mi="1234"),
        pi().replace("KEY ID: 01;", "KEY ID: ?;"),
        "Slot 2 DMR PI H- ALG ID: 21;",
        pi("36", "Kirisun Advanced;"),
    ],
)
def test_unknown_malformed_or_ambiguous_pi_is_not_confirmed(line):
    e = context()
    e.observe(line, 1.2)
    assert not e.encrypted
    assert e.dmr_frames.snapshot()["slots"]["2"]["pi_unresolved"] == 1


def test_hytera_requires_full_positive_checksum_branch():
    e = context()
    e.observe(pi("01", "(Checksum Err);", "1234567890", 40), 1.2)
    assert not e.encrypted
    e.observe(pi("01", "Hytera Enhanced;", "1234567890", 40), 1.3)
    assert e.encrypted


def test_pi_needs_fresh_repeated_matching_protocol_context():
    e = Evidence()
    e.observe(pi(), 0)
    e.observe("Sync: +DMR", 1)
    e.observe(pi(), 1)
    assert not e.encrypted
    e.observe("Sync: +DMR", 1.1)
    e.observe(pi(), 3)
    assert not e.encrypted
    e.observe("Sync: +NXDN48", 3.1)
    e.observe(pi(), 3.2)
    assert not e.encrypted


def test_slot_and_burst_classes_and_duplicate_worker_summary():
    e = context()
    for suffix in ("VLC", "TLC", "CSBK", "DATA", "R12U", "IDLE", "VC1", "VC*"):
        e.observe("Sync: +DMR slot1 [SLOT2] | Color Code=02 | " + suffix, 1.2)
    e.observe("Sync: +DMR slot1 [SLOT2] | DATA CRC ERR", 1.3)
    snapshot = e.dmr_frames.snapshot()
    slots = snapshot["slots"]
    assert slots["1"] == {"idle": 1}
    assert slots["2"] == {
        "voice_header": 1,
        "terminator": 1,
        "control": 1,
        "data": 2,
        "idle": 1,
        "voice_burst": 2,
        "invalid": 1,
    }
    worker = {"dmr_frames": snapshot}
    assert frame_summary([worker, worker])["data"] == 2
    assert frame_summary([worker])["idle"] == 2
    assert worker_summary({"transport": []})["mode"] == "multi"


def test_unrelated_probe_error_is_not_candidate_failure(tmp_path, monkeypatch):
    conv, store = conversation(tmp_path, monkeypatch)
    conv.digital.metadata.update(
        sync_candidates=["NXDN48"], sync_counts={"NXDN48": 6}, invalid_counts={"dPMR": 3}
    )
    conv.finish("fixture_end")
    row = store.digital_attempts()[0]
    assert row["diagnostic_reason"] == "sync_without_audio"
    assert row["diagnostic_error_protocols"] == []
    assert row["invalid_counts"] == {"dPMR": 3}
    store.close()


def test_realistic_pi_header_vetoes_delayed_pcm_before_publication(tmp_path, monkeypatch):
    import numpy as np

    conv, store = conversation(tmp_path, monkeypatch)
    e = context()
    e.observe(pi(), 1.2)
    conv.digital.metadata.update(
        protocol="DMR",
        encrypted=e.encrypted,
        encryption_at=e.encryption_at,
        sync_counts=e.counts,
        dmr_frames=e.dmr_frames.snapshot(),
    )
    conv.checked_ms = 1500
    conv.digital.packets = [packet(1.52)]
    conv.consume([(np.zeros(320), False)])
    assert conv.encrypted_call and conv.done and not store.recordings()
    assert not list(conv.archive.root.glob("*.wav"))
    assert store.digital_attempts()[0]["frame_summary"]["crypto_header"] == 1
    store.close()


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("idle", "service_frames_observed"),
        ("crypto_header", "encryption_indicated"),
    ],
)
def test_no_pcm_service_or_crypto_headers_are_diagnostic_only(
    tmp_path, monkeypatch, kind, expected
):
    conv, store = conversation(tmp_path, monkeypatch)
    e = {"protocol": "DMR", "dmr_frames": {"slots": {"1": {kind: 3}}}}
    conv.digital.metadata.update(
        protocol=None, sync_candidates=["DMR"], worker_evidence=[e], sync_counts={"DMR": 3}
    )
    conv.finish("fixture_end")
    row = store.digital_attempts()[0]
    assert row["diagnostic_reason"] == expected
    assert row["worker_evidence"] == [e]
    assert not store.recordings() and conv.choice is None
    store.close()
