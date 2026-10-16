import ctypes as ct
import queue
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from radiomind.hackrf import HackRFSource, Transfer


def fake_source() -> HackRFSource:
    source = HackRFSource.__new__(HackRFSource)
    source.blocks = queue.Queue(maxsize=1)
    source.buffer_lock = threading.Lock()
    source.continuous = False
    source.application_dropped_samples = 0
    source.received_samples = 0
    source.preview_discarded_samples = 0
    source.callback_error = None
    source.settle_blocks = 0
    source._init_history()
    return source


def test_native_buffer_is_copied_bounded_and_signed_iq() -> None:
    source = fake_source()
    raw = (ct.c_uint8 * 8)(127, 128, 0, 64, 128, 127, 0, 0)
    transfer = Transfer(None, raw, 8, 8, None, None)
    assert source._receive(ct.pointer(transfer)) == 0
    assert source._receive(ct.pointer(transfer)) == 0
    assert source.blocks.qsize() == 1
    assert source.preview_discarded_samples == 4
    raw[0] = 0
    iq = source.read(2)
    np.testing.assert_allclose(iq, [127 / 128 - 1j, 0.5j])
    assert source.received_samples == 8
    assert source.preview_discarded_samples == 6


def test_malformed_callback_stops_without_crossing_ffi() -> None:
    source = fake_source()
    raw = (ct.c_uint8 * 8)()
    transfer = Transfer(None, raw, 8, 9, None, None)
    assert source._receive(ct.pointer(transfer)) == -1
    assert source.callback_error


def test_continuous_fifo_never_silently_overwrites_samples() -> None:
    source = fake_source()
    source.continuous = True
    raw = (ct.c_uint8 * 8)(1, 2, 3, 4, 5, 6, 7, 8)
    transfer = Transfer(None, raw, 8, 8, None, None)
    assert source._receive(ct.pointer(transfer)) == 0
    assert source._receive(ct.pointer(transfer)) == -1
    assert source.application_dropped_samples == 4
    assert source.preview_discarded_samples == 0
    assert source.blocks.get_nowait() == bytes(raw)


def test_interleaved_conversion_preserves_all_signed_values_and_owned_storage() -> None:
    source = fake_source()
    raw = np.arange(-128, 128, dtype=np.int16).astype(np.int8)
    block = raw.tobytes()
    source.blocks.put_nowait(block)
    iq = source.read(128)
    expected = raw.astype(np.float32) / 128
    assert iq.dtype == np.complex64
    np.testing.assert_array_equal(iq.real, expected[::2])
    np.testing.assert_array_equal(iq.imag, expected[1::2])
    iq[:] = 0
    assert block == raw.tobytes()


@pytest.mark.parametrize("stop_code,close_code", [(0, 0), (-1000, 0), (-1000, -1000)])
def test_native_shutdown_releases_handle_even_after_usb_stop_error(stop_code, close_code):
    source = fake_source()
    source.streaming = source.initialized = True
    source.device = ct.c_void_p(1)
    calls = []

    def native(name, code):
        def call(*args):
            calls.append(name)
            return code

        return call

    source.lib = SimpleNamespace(
        hackrf_stop_rx=native("stop", stop_code),
        hackrf_close=native("close", close_code),
        hackrf_exit=native("exit", 0),
    )
    source.dll_directory = SimpleNamespace(close=native("directory", 0))
    if stop_code:
        with pytest.raises(RuntimeError, match="stop RX during close failed"):
            source.close()
    else:
        source.close()
    assert calls == ["stop", "close", "exit", "directory"]
    assert not source.device.value and not source.initialized and not source.streaming
    source.close()
    assert len(calls) == 4  # No double-free when native close reported an error.
