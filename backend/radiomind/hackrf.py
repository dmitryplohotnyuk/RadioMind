"""Narrow ctypes boundary: only native receive and device-information functions."""

import ctypes as ct
import os
import queue
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from radiomind.config import RX_GAINS, ReceiveGain, Window
from radiomind.radio import IQ


class Transfer(ct.Structure):
    _fields_ = [
        ("device", ct.c_void_p),
        ("buffer", ct.POINTER(ct.c_uint8)),
        ("buffer_length", ct.c_int),
        ("valid_length", ct.c_int),
        ("rx_ctx", ct.c_void_p),
        ("tx_ctx", ct.c_void_p),
    ]


Callback = ct.CFUNCTYPE(ct.c_int, ct.POINTER(Transfer))


class BoardSerial(ct.Structure):
    _fields_ = [("part_id", ct.c_uint32 * 2), ("serial_no", ct.c_uint32 * 4)]


class HackRFSource:
    def __init__(
        self,
        library: Path,
        history_ms: int = 0,
        serial: str | None = None,
        receive_gain: ReceiveGain = "normal",
    ) -> None:
        self.lna_gain, self.vga_gain = RX_GAINS[receive_gain]
        self.adc: dict[str, float | int] = {}
        path = library.resolve(strict=True)
        self.dll_directory = os.add_dll_directory(str(path.parent)) if os.name == "nt" else None
        self.lib = ct.CDLL(str(path))
        self.device = ct.c_void_p()
        self.device_serial: str | None = None
        self.streaming = False
        self.initialized = False
        self.blocks: queue.Queue[bytes] = queue.Queue(maxsize=1)
        self.buffer_lock = threading.Lock()
        self.continuous = False
        self.application_dropped_samples = 0
        self.received_samples = 0
        self.preview_discarded_samples = 0
        self.callback_error: str | None = None
        self.settle_blocks = 0
        self._init_history(history_ms)
        self.callback = Callback(self._receive)
        self._bind("hackrf_init", [])
        self._bind("hackrf_exit", [])
        self._bind("hackrf_open", [ct.POINTER(ct.c_void_p)])
        self._bind("hackrf_open_by_serial", [ct.c_char_p, ct.POINTER(ct.c_void_p)])
        self._bind("hackrf_close", [ct.c_void_p])
        self._bind("hackrf_start_rx", [ct.c_void_p, Callback, ct.c_void_p])
        self._bind("hackrf_stop_rx", [ct.c_void_p])
        self._bind("hackrf_set_sample_rate", [ct.c_void_p, ct.c_double])
        self._bind("hackrf_set_freq", [ct.c_void_p, ct.c_uint64])
        self._bind("hackrf_set_amp_enable", [ct.c_void_p, ct.c_uint8])
        self._bind("hackrf_set_antenna_enable", [ct.c_void_p, ct.c_uint8])
        self._bind("hackrf_set_lna_gain", [ct.c_void_p, ct.c_uint32])
        self._bind("hackrf_set_vga_gain", [ct.c_void_p, ct.c_uint32])
        self._bind("hackrf_set_baseband_filter_bandwidth", [ct.c_void_p, ct.c_uint32])
        self._bind("hackrf_version_string_read", [ct.c_void_p, ct.c_char_p, ct.c_uint8])
        self._bind("hackrf_board_id_read", [ct.c_void_p, ct.POINTER(ct.c_uint8)])
        self._bind("hackrf_board_partid_serialno_read", [ct.c_void_p, ct.POINTER(BoardSerial)])
        self.lib.hackrf_library_version.restype = ct.c_char_p
        self.lib.hackrf_library_release.restype = ct.c_char_p
        try:
            self._check(self.lib.hackrf_init(), "initialize")
            self.initialized = True
            if serial:
                self._check(
                    self.lib.hackrf_open_by_serial(serial.encode("ascii"), ct.byref(self.device)),
                    "open",
                )
            else:
                self._check(self.lib.hackrf_open(ct.byref(self.device)), "open")
            identity = BoardSerial()
            if self.lib.hackrf_board_partid_serialno_read(self.device, ct.byref(identity)) == 0:
                self.device_serial = "".join(f"{word:08x}" for word in identity.serial_no)
        except Exception:
            self.close()
            raise

    def _bind(self, name: str, arguments: list[Any]) -> None:
        function = getattr(self.lib, name)
        function.argtypes, function.restype = arguments, ct.c_int

    def _init_history(self, milliseconds: int = 0) -> None:
        self.history_limit = min(max(milliseconds, 0), 1000) * 8000
        self.history: deque[bytes] = deque()
        self.history_samples = 0
        self.stream_samples = 0
        self.stream_start: float | None = None
        self.capture_start_sample = 0
        self.capture_start_utc: str | None = None
        self.capture_history_samples = 0
        self.tune_generation = 0

    def _remember(self, block: bytes) -> None:
        if not self.history_limit:
            return
        self.history.append(block)
        self.history_samples += len(block) // 2
        # Limit both samples and entries, leaving FIFO room for incoming live IQ.
        while len(self.history) > 64:
            self.history_samples -= len(self.history.popleft()) // 2
        excess = self.history_samples - self.history_limit
        while excess > 0:
            first = self.history.popleft()
            size = len(first) // 2
            removed = min(size, excess)
            if removed < size:
                self.history.appendleft(first[removed * 2 :])
            self.history_samples -= removed
            excess -= removed

    def _reset_history(self) -> None:
        self.history.clear()
        self.history_samples = self.stream_samples = 0
        self.stream_start = None
        self.capture_start_utc = None
        self.capture_history_samples = 0
        self.tune_generation += 1

    @staticmethod
    def _check(code: int, operation: str) -> None:
        if code != 0:
            raise RuntimeError(f"HackRF {operation} failed (libhackrf code {code})")

    def info(self) -> dict[str, object]:
        version = ct.create_string_buffer(255)
        board = ct.c_uint8()
        self._check(self.lib.hackrf_version_string_read(self.device, version, 255), "firmware read")
        self._check(self.lib.hackrf_board_id_read(self.device, ct.byref(board)), "board read")
        return {
            "firmware": version.value.decode("ascii", errors="replace"),
            "board_id": board.value,
            "library_version": self.lib.hackrf_library_version().decode(),
            "library_release": self.lib.hackrf_library_release().decode(),
        }

    def _receive(self, pointer: Any) -> int:
        try:
            transfer = pointer.contents
            size = transfer.valid_length
            if size <= 0 or size % 2 or size > transfer.buffer_length:
                raise RuntimeError("Malformed native IQ transfer")
            self.received_samples += size // 2
            if self.settle_blocks:
                self.settle_blocks -= 1
                self.preview_discarded_samples += size // 2
                return 0
            block = ct.string_at(transfer.buffer, size)
            with self.buffer_lock:
                if self.stream_start is None:
                    self.stream_start = time.time() - size / 2 / 8_000_000
                self.stream_samples += size // 2
                if self.continuous:
                    try:
                        self.blocks.put_nowait(block)
                    except queue.Full:
                        self.application_dropped_samples += size // 2
                        raise RuntimeError(
                            "Continuous IQ buffer overflow; audio has a gap"
                        ) from None
                else:
                    self._remember(block)
                    try:
                        old = self.blocks.get_nowait()
                        self.preview_discarded_samples += len(old) // 2
                    except queue.Empty:
                        pass
                    self.blocks.put_nowait(block)
            return 0
        except Exception as exc:
            self.callback_error = str(exc)
            return -1

    def tune(self, window: Window) -> None:
        if self.streaming:
            self._check(self.lib.hackrf_stop_rx(self.device), "stop RX")
            self.streaming = False
        while not self.blocks.empty():
            self.preview_discarded_samples += len(self.blocks.get_nowait()) // 2
        self._reset_history()
        self.callback_error = None
        self._check(self.lib.hackrf_set_amp_enable(self.device, 0), "disable RF amplifier")
        self._check(self.lib.hackrf_set_antenna_enable(self.device, 0), "disable antenna power")
        self._check(
            self.lib.hackrf_set_sample_rate(self.device, window.sample_rate_sps), "sample rate"
        )
        self._check(self.lib.hackrf_set_baseband_filter_bandwidth(self.device, 7_000_000), "filter")
        self._check(self.lib.hackrf_set_lna_gain(self.device, self.lna_gain), "LNA gain")
        self._check(self.lib.hackrf_set_vga_gain(self.device, self.vga_gain), "VGA gain")
        self._check(self.lib.hackrf_set_freq(self.device, window.center_hz), "frequency")
        self.settle_blocks = 4
        self.adc = {}
        self._check(self.lib.hackrf_start_rx(self.device, self.callback, None), "start RX")
        self.streaming = True

    def read(self, samples: int) -> IQ:
        return self._read(samples)

    def set_continuous(self, enabled: bool) -> None:
        with self.buffer_lock:
            if enabled == self.continuous:
                return
            while not self.blocks.empty():
                self.preview_discarded_samples += len(self.blocks.get_nowait()) // 2
            self.blocks = queue.Queue(maxsize=128 if enabled else 1)
            if enabled:
                self.capture_history_samples = self.history_samples
                self.capture_start_sample = self.stream_samples - self.history_samples
                anchor = self.stream_start if self.stream_start is not None else time.time()
                self.capture_start_utc = datetime.fromtimestamp(
                    anchor + self.capture_start_sample / 8_000_000, UTC
                ).isoformat()
                for block in self.history:
                    self.blocks.put_nowait(block)
            self.history.clear()
            self.history_samples = 0
            self.continuous = enabled

    def read_full(self) -> IQ:
        if not self.continuous:
            raise RuntimeError("Full audio input requires continuous FIFO mode")
        return self._read(None)

    def _read(self, samples: int | None) -> IQ:
        if self.callback_error:
            raise RuntimeError(self.callback_error)
        try:
            block = self.blocks.get(timeout=3)
        except queue.Empty as exc:
            raise RuntimeError("HackRF RX timeout: check USB/device ownership") from exc
        raw = np.frombuffer(block, dtype=np.int8)
        available = len(raw) // 2
        if samples is None:
            samples = available
        if available < samples:
            raise RuntimeError("Requested FFT block exceeds native transfer; reduce FFT/averages")
        self.preview_discarded_samples += available - samples
        # Bounded read-side diagnostic, never additional work in the USB callback.
        # This samples ADC components; it cannot rule out analog front-end overload.
        measured = (
            raw.reshape(-1, 2)[:: max(1, len(raw) // 8192)].reshape(-1)[:8192].astype(np.float32)
        )
        peak = max(abs(int(raw.min())), abs(int(raw.max())))
        self.adc = {
            "peak_dbfs": float(20 * np.log10(max(peak / 128, 1e-9))),
            "rms_dbfs": float(10 * np.log10(max(float(np.mean(measured**2)) / 128**2, 1e-18))),
            "sampled_rail_fraction": float(np.mean((measured <= -128) | (measured >= 127))),
            "sampled_components": len(measured),
        }
        # Interleaved I/Q already has complex64 layout after one float conversion.
        # Avoid allocating separate real/imaginary arithmetic temporaries per transfer.
        iq = raw[: samples * 2].astype(np.float32).view(np.complex64)
        iq *= np.float32(1 / 128)
        return iq

    def metrics(self) -> dict[str, object]:
        return {
            "adc": getattr(self, "adc", {}),
            "rx_gain_db": {"lna": self.lna_gain, "vga": self.vga_gain},
            "device_serial": self.device_serial,
            "hardware_connected": bool(self.device.value),
            "synthetic": False,
            "received_samples": self.received_samples,
            "preview_discarded_samples": self.preview_discarded_samples,
            "usb_dropped_samples": None,
            "preview_only": not self.continuous,
            "application_dropped_samples": self.application_dropped_samples,
            "queued_blocks": self.blocks.qsize(),
            "callback_error": self.callback_error,
            "history_seconds": self.history_samples / 8_000_000,
            "capture_history_seconds": self.capture_history_samples / 8_000_000,
            "capture_start_sample": self.capture_start_sample,
            "capture_start_utc": self.capture_start_utc,
            "tune_generation": self.tune_generation,
            "stream_samples": self.stream_samples,
            "timestamp_basis": "host_first_transfer_plus_sample_clock",
        }

    def close(self) -> None:
        errors: list[str] = []
        if self.streaming:
            code = self.lib.hackrf_stop_rx(self.device)
            if code:
                errors.append(f"HackRF stop RX during close failed (libhackrf code {code})")
            self.streaming = False
        if self.device.value:
            # libhackrf frees the handle even when its stop command returns an error.
            # Always release it after a failed stop, and never retry a freed handle.
            code = self.lib.hackrf_close(self.device)
            self.device = ct.c_void_p()
            if code:
                errors.append(f"HackRF close failed (libhackrf code {code})")
        if self.initialized:
            code = self.lib.hackrf_exit()
            self.initialized = False
            if code:
                errors.append(f"HackRF exit failed (libhackrf code {code})")
        if self.dll_directory:
            self.dll_directory.close()
            self.dll_directory = None
        if errors:
            raise RuntimeError("; ".join(errors))
