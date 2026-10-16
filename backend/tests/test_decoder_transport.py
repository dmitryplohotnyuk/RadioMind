import io
import queue
import runpy
import socket
import threading
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_digital import conversation

from radiomind.digital import DigitalDecoder, Evidence


def sender(connection):
    worker = DigitalDecoder.__new__(DigitalDecoder)
    worker.connection = connection
    worker.mode = "auto"
    worker.iq_input = False
    worker.stopping = threading.Event()
    worker.inputs = queue.Queue(64)
    worker.sent_bytes = worker.input_samples = 0
    worker.max_send_ms = 0.0
    worker.transport_failure = worker.error = None
    worker.process = SimpleNamespace(poll=lambda: None)
    worker.lock = threading.Lock()
    worker.evidence = Evidence()
    worker.log_tail = deque(maxlen=12)
    return worker


def test_local_socket_preserves_all_bytes_and_block_order():
    tx, rx = socket.socketpair()
    tx.settimeout(1)
    rx.settimeout(1)
    worker = sender(tx)
    payload = bytes(range(256)) * 1200
    for at in range(0, len(payload), 8191):
        worker.inputs.put(payload[at : at + 8191])
    worker.inputs.put(None)
    thread = threading.Thread(target=worker._send)
    thread.start()
    try:
        received = bytearray()
        while len(received) < len(payload):
            received.extend(rx.recv(1201))
        thread.join(1)
        assert not thread.is_alive()
        assert bytes(received) == payload
        assert worker.sent_bytes == len(payload)
        assert worker.inputs.unfinished_tasks == 0
        assert worker.status()["transport"]["failure"] is None
    finally:
        worker.stopping.set()
        tx.close()
        rx.close()
        thread.join(1)


@pytest.mark.parametrize(
    "error", [ConnectionResetError(10054, "peer reset"), TimeoutError("stalled")]
)
def test_partial_send_failure_is_not_retried_or_followed_by_later_blocks(error):
    accepted = []

    class PartialConnection:
        def sendall(self, data):
            accepted.append(data[:3])
            raise error

    worker = sender(PartialConnection())
    worker.inputs.put(b"abcdefgh")
    worker.inputs.put(b"next-block")
    worker._send()
    assert accepted == [b"abc"]
    assert worker.inputs.get_nowait() == b"next-block"
    assert worker.sent_bytes == 0  # A failed sendall cannot reveal its partial byte count.
    status = worker.status()["transport"]
    assert status["mode"] == "auto"
    assert status["failure"]["exception"] == type(error).__name__
    assert status["failure"]["process_exit"] is None
    with pytest.raises(RuntimeError, match="Digital decoder input failed"):
        worker.check()


def test_requested_shutdown_does_not_attempt_or_retry_input():
    worker = sender(None)
    worker.connection = SimpleNamespace(sendall=lambda _: pytest.fail("send after stop"))
    worker.stopping.set()
    worker._send()
    assert worker.error is None and worker.transport_failure is None


def test_failure_log_tail_is_bounded_and_excludes_voice_log_prefix():
    worker = sender(None)
    lines = [b"Src=12345 Dst=67890\n"]
    lines += [b"Sync: NXDN48 \x1b[32mrtl_tcp: " + b"x" * 1000 + b"\n"] * 20
    worker.process.stderr = io.BytesIO(b"".join(lines))
    worker._logs()
    assert len(worker.log_tail) == 12
    assert all(len(line) <= 512 and line.startswith("rtl_tcp:") for line in worker.log_tail)
    assert "Src=" not in "".join(worker.log_tail)
    assert "Sync:" not in "".join(worker.log_tail)
    assert worker.status()["transport"]["log_tail"] == []
    worker.transport_failure = {"exception": "ConnectionResetError"}
    assert len(worker.status()["transport"]["log_tail"]) == 12


def test_transport_failure_survives_attempt_persistence(tmp_path, monkeypatch):
    conv, store = conversation(tmp_path, monkeypatch)
    evidence = {"mode": "auto", "failure": {"exception": "ConnectionResetError", "errno": 10054}}
    conv.digital.metadata.update(error="Digital decoder input failed", transport=evidence)
    try:
        conv.finish("capture_or_storage_error", interrupted=True)
        attempt = store.digital_attempts()[0]
        assert attempt["diagnostic_reason"] == "decoder_error"
        assert attempt["decoder_transport"] == evidence
        assert not store.recordings()
    finally:
        store.close()


def test_prepared_replay_has_expected_clock_offset_and_seeded_noise():
    prepare = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/validate_digital_iq.py")
    )["prepare_replay"]
    iq = np.full(48, 0.5 + 0j)
    clean = io.BytesIO()
    count = prepare(clean, iq, complex_input=True, offset_hz=750, noise=0)
    assert len(clean.getbuffer()) == count * 8
    assert clean.tell() == 0
    samples = np.frombuffer(clean.getbuffer(), dtype=np.complex64)[:4096]
    frequency = np.angle(samples[1:] * samples[:-1].conj()).mean() * 8_000_000 / (2 * np.pi)
    assert frequency == pytest.approx(1_000_750, abs=1)
    np.testing.assert_allclose(np.abs(samples), 0.5, atol=1e-6)
    noisy_a, noisy_b = io.BytesIO(), io.BytesIO()
    for output in (noisy_a, noisy_b):
        prepare(output, iq, complex_input=True, offset_hz=750, noise=0.01)
    assert noisy_a.getvalue() == noisy_b.getvalue()
    assert noisy_a.getvalue() != clean.getvalue()
    with pytest.raises(ValueError, match="limit"):
        prepare(io.BytesIO(), np.zeros(600000), complex_input=True, offset_hz=0, noise=0)
