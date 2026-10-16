import queue
import threading
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from test_audio import audio_settings
from test_digital import FakeDecoder, conversation, packet

from radiomind.config import Settings
from radiomind.digital import DigitalDecoder
from radiomind.digital_level import DigitalIQEncoder
from radiomind.tetra import DigitalDispatch


@pytest.mark.parametrize("enabled,input_mode", [(False, "iq"), (True, "flat_fm")])
def test_phase2_probe_rejects_inactive_or_discriminator_input(enabled, input_mode):
    data = audio_settings().model_dump()
    data["digital"].update(enabled=enabled, input_mode=input_mode, p25p2_probe_enabled=True)
    with pytest.raises(ValidationError, match="P25-II probe requires"):
        Settings.model_validate(data)
    data["digital"].update(enabled=True, input_mode="iq")
    assert Settings.model_validate(data).digital.p25p2_probe_enabled


def test_discovery_probes_share_iq_and_control_sync_cannot_win(monkeypatch):
    created = []

    class Worker(FakeDecoder):
        def __init__(self, executable, mode, *, iq):
            assert iq
            super().__init__(executable, mode)
            self.received = []
            created.append(self)

        def feed_iq(self, block):
            self.received.append(block)

    monkeypatch.setattr("radiomind.digital.DigitalDecoder", Worker)
    dispatch = DigitalDispatch(Path("unused"), "auto", tetra=False, dstar=True, p25p2=True)
    assert [w.mode for w in created] == ["auto", "D-STAR", "P25-II"]
    block = np.zeros(960, dtype=np.complex64)
    dispatch.feed_iq(block)
    assert all(w.received[0] is block for w in created)
    created[2].metadata.update(protocol="P25-II", sync_counts={"P25-II": 16})
    assert not dispatch.drain() and dispatch.selected is None
    assert dispatch.status()["protocol"] is None
    assert dispatch.status()["sync_candidates"] == ["P25-II"]
    # A different worker may subsequently decode audio; control sync never locks it out.
    created[0].metadata.update(protocol="DMR", sync_counts={"DMR": 3}, dmr_call_confirmed=True)
    created[0].packets = [packet(0.02)]
    assert len(dispatch.drain()) == 1
    assert dispatch.status()["protocol"] == "DMR"
    assert all(w.closed for w in created[1:])
    dispatch.close()
    assert all(w.closed for w in created)

    created.clear()
    known = DigitalDispatch(Path("unused"), "P25-II", tetra=False, dstar=True, p25p2=True)
    assert [w.mode for w in created] == ["P25-II"]
    known.close()


def test_probe_start_failure_closes_already_started_workers(monkeypatch):
    created = []

    def factory(executable, mode, *, iq):
        if mode == "P25-II":
            raise RuntimeError("probe failed")
        worker = FakeDecoder(executable, mode)
        created.append(worker)
        return worker

    monkeypatch.setattr("radiomind.digital.DigitalDecoder", factory)
    with pytest.raises(RuntimeError, match="probe failed"):
        DigitalDispatch(Path("unused"), "auto", tetra=False, dstar=True, p25p2=True)
    assert len(created) == 2 and all(w.closed for w in created)


def test_dispatch_encodes_iq_once_and_preserves_each_worker_clock():
    dispatch = DigitalDispatch.__new__(DigitalDispatch)
    dispatch.iq_encoder = DigitalIQEncoder()
    dispatch.workers = []
    for _ in range(3):
        worker = DigitalDecoder.__new__(DigitalDecoder)
        worker.iq_input, worker.closed = True, False
        worker.error = worker.process = None
        worker.input_samples = 0
        worker.inputs = queue.Queue(64)
        dispatch.workers.append(worker)
    iq = np.array([0.5 + 0.25j, -0.25 - 0.5j], dtype=np.complex64)
    dispatch.feed_iq(iq)
    blocks = [w.inputs.get_nowait() for w in dispatch.workers]
    assert all(block is blocks[0] for block in blocks)
    assert all(w.input_samples == 2 for w in dispatch.workers)
    wire = np.frombuffer(blocks[0], dtype=np.uint8).reshape(-1, 2)
    np.testing.assert_array_equal(wire[:32], np.tile([191, 159], (32, 1)))
    np.testing.assert_array_equal(wire[32:], np.tile([95, 64], (32, 1)))
    assert dispatch.iq_encoder.blocks == 1
    with pytest.raises(RuntimeError, match="Invalid complex"):
        dispatch.feed_iq(np.array([complex(float("nan"), 0)]))
    assert all(w.inputs.empty() for w in dispatch.workers)


def test_workers_drain_concurrently():
    barrier = threading.Barrier(3, timeout=2)

    class ClosingWorker:
        def close(self):
            barrier.wait()

    DigitalDispatch._close_workers([ClosingWorker() for _ in range(3)])


@pytest.mark.parametrize("iq", [True, False])
def test_dmr_probe_keeps_onset_requires_call_evidence_and_locks_selected_label(monkeypatch, iq):
    created = []

    class Worker(FakeDecoder):
        def __init__(self, executable, mode, *, iq):
            super().__init__(executable, mode)
            self.received = []
            created.append(self)

        def feed_iq(self, block):
            self.received.append(block)

        feed = feed_iq

    monkeypatch.setattr("radiomind.digital.DigitalDecoder", Worker)
    dispatch = DigitalDispatch(Path("unused"), "auto", tetra=False, dmr=True, iq=iq)
    assert [w.mode for w in created] == ["DMR", "auto"]
    early = [packet(0.1), packet(0.12)]
    created[0].metadata.update(protocol="DMR", sync_counts={"DMR": 4})
    created[0].packets = early.copy()
    assert dispatch.drain() == []  # PCM + unconfirmed sync must not select the probe.
    created[0].metadata["dmr_call_confirmed"] = True
    assert dispatch.drain() == early  # Keep every early PCM sample on confirmation.
    assert created[1].closed and not created[0].closed
    created[0].metadata.update(protocol="M17", encryption_at={"DMR": 0.5})
    status = dispatch.status()
    assert status["protocol"] == "DMR" and status["observed_protocol"] == "M17"
    assert status["encryption_at"] == {"DMR": 0.5}
    block = np.zeros(960)
    (dispatch.feed_iq if iq else dispatch.feed)(block)
    assert created[0].received == [block] and not created[1].received
    dispatch.close()


def test_unconfirmed_dmr_probe_does_not_block_other_audio_or_mix_its_pcm(monkeypatch):
    created = []

    def factory(executable, mode, *, iq):
        worker = FakeDecoder(executable, mode)
        created.append(worker)
        return worker

    monkeypatch.setattr("radiomind.digital.DigitalDecoder", factory)
    dispatch = DigitalDispatch(Path("unused"), "auto", tetra=False, dmr=True)
    created[0].metadata.update(protocol="DMR", dmr_call_confirmed=False)
    created[0].packets = [packet(0.1)]
    created[1].metadata.update(protocol="M17")
    actual = packet(0.2, channels=1)
    created[1].packets = [actual]
    assert dispatch.drain() == [actual]
    assert dispatch.status()["protocol"] == "M17" and created[0].closed
    dispatch.close()


def test_dmr_probe_requires_digital_but_supports_flat_input():
    data = audio_settings().model_dump()
    data["digital"].update(dmr_probe_enabled=True, enabled=False)
    with pytest.raises(ValidationError, match="DMR probe requires"):
        Settings.model_validate(data)
    data["digital"].update(enabled=True, input_mode="flat_fm")
    assert Settings.model_validate(data).digital.dmr_probe_enabled


@pytest.mark.parametrize("mode,probe", [("auto", False), ("auto", True), ("DMR", False)])
def test_every_dmr_worker_requires_call_confirmation_and_preserves_onset(monkeypatch, mode, probe):
    created = []

    def factory(executable, mode, *, iq):
        worker = FakeDecoder(executable, mode)
        created.append(worker)
        return worker

    monkeypatch.setattr("radiomind.digital.DigitalDecoder", factory)
    dispatch = DigitalDispatch(Path("unused"), mode, tetra=False, dmr=probe)
    # AUTO is the second worker when the dedicated probe is present.
    worker = created[-1]
    worker.metadata.update(protocol="DMR", sync_counts={"DMR": 200})
    early = [packet(0.02), packet(0.04)]
    worker.packets = early.copy()
    assert dispatch.drain() == [] and dispatch.selected is None
    worker.metadata["dmr_call_confirmed"] = True
    assert dispatch.drain() == early
    selected = dispatch.status()["selection_evidence"]
    assert selected["protocol"] == "DMR" and selected["dmr_call_confirmed"] is True
    worker.metadata.update(protocol=None, dmr_call_confirmed=False)
    assert dispatch.status()["selection_evidence"] == selected
    dispatch.close()


@pytest.mark.parametrize("analog", [False, True])
def test_sync_candidate_is_diagnostic_only_without_audio(tmp_path, monkeypatch, analog):
    conv, store = conversation(tmp_path, monkeypatch)
    conv.digital.metadata.update(
        sync_candidates=["P25-II"],
        sync_counts={"P25-II": 16},
        encryption_at={"P25-II": 0.1},
    )
    try:
        for _ in range(conv.settings.digital.verify_ms // 20 + 1):
            if conv.done or conv.choice == "analog":
                break
            conv.consume([(np.full(320, 0.1) if analog else np.zeros(320), analog)])
        conv.finish("fixture_end")
        assert conv.done and not conv.encrypted_call
        assert store.digital_mode(conv.frequency_hz) == "auto"
        assert len(store.recordings()) == int(analog)
        attempt = store.digital_attempts()[0]
        assert attempt["sync_candidates"] == ["P25-II"]
        assert attempt["protocol"] is None
        assert attempt["outcome"] == ("analog_selected" if analog else "sync_without_audio")
        conv.finish("repeated_finish")
        assert len(store.digital_attempts()) == 1
    finally:
        store.close()


@pytest.mark.parametrize("confirm", [False, True])
def test_no_probe_conversation_cannot_bypass_dmr_confirmation_at_close(
    tmp_path, monkeypatch, confirm
):
    from radiomind.digital_conversation import MultiModeConversation
    from radiomind.recording import Archive
    from radiomind.storage import Store

    created = []

    def factory(executable, mode, **kwargs):
        worker = FakeDecoder(executable, mode)
        created.append(worker)
        return worker

    monkeypatch.setattr("radiomind.digital.DigitalDecoder", factory)
    settings = audio_settings()
    settings.digital.enabled = True
    store = Store(tmp_path / "no-probe.sqlite3", 1000)
    conv = MultiModeConversation(
        settings, Archive(settings, store), settings.windows[0], 145000000, 20, mode="DMR"
    )
    assert len(created) == 1
    worker = created[0]
    worker.metadata.update(protocol="DMR", sync_counts={"DMR": 99})
    worker.packets = [packet(0.02)]
    conv.consume([(np.zeros(320), False)])
    assert conv.choice is None and not store.recordings()
    worker.metadata["dmr_call_confirmed"] = confirm
    conv.finish("fixture_end")
    assert len(store.recordings()) == (2 if confirm else 0)
    if confirm:
        assert store.recordings()[0]["decoder_evidence"]["selection_evidence"]["dmr_call_confirmed"]
    store.close()
