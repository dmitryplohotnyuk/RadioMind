"""Bounded, RX-only DSD-neo process adapter. No tuner, keys or shell commands.

TCP carries flat 48 kHz PCM or virtual RTL complex IQ; loopback UDP returns 20 ms
8 kHz PCM frames (mono or two TDMA slots). Windows stdout in upstream 2.10.0 expands
LF bytes, so binary audio must not use its stdout. Protocol logs stay in RAM.
"""

import hashlib
import json
import os
import queue
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from radiomind.digital_level import DigitalIQEncoder
from radiomind.digital_metadata import INVALID, DMRMetadata
from radiomind.nfm import Audio

ROOT = Path(__file__).resolve().parents[2]
VERSION = "2.10.0"
MODES = {
    "auto": "a",
    "DMR": "s",
    "P25-I": "1",
    "P25-II": "2",
    "NXDN48": "i",
    "NXDN96": "n",
    "D-STAR": "d",
    "YSF": "y",
    "dPMR": "m",
    "M17": "z",
}
VALIDATION = {
    "DMR": "synthetic_pipeline_passed",
    "M17": "synthetic_pipeline_passed",
    "P25-I": "decoder_pcm_fixture_passed",
    "NXDN48": "decoder_pcm_fixture_passed",
    "D-STAR": "decoder_pcm_fixture_passed",
    "YSF": "decoder_pcm_fixture_passed",
    "dPMR": "synthetic_signaling_passed",
    "NXDN96": "synthetic_complex_pipeline_passed",
    "P25-II": "control_fixture_only",
}
ALIASES = {"P25p1": "P25-I", "P25p2": "P25-II", "DSTAR": "D-STAR"}
SYNC = re.compile(r"Sync:\s*[+-]?(DMR|P25p1|P25p2|NXDN48|NXDN96|D-STAR|DSTAR|YSF|dPMR|M17)\b")
ENCRYPTED = re.compile(
    r"\b(?:ENC|Encrypted|ENCRYPTED|Scrambler|Privacy)\b|\bET:\s*[1-3]\b|\bProtected LC\b"
)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
DMR_CALL = re.compile(r"SLOT ([12])\s+TGT=(\d+) SRC=(\d+)\s+.*(?:Group|Private) Call\b(?! Alert)")


def decoder_path(configured: Path | None = None) -> Path:
    if configured:
        return configured.expanduser().resolve()
    relative = Path("bin/dsd-neo.exe") if os.name == "nt" else Path("AppRun")
    return ROOT / "tools" / "digital" / "dsd-neo" / relative


@lru_cache(maxsize=4)
def verify_decoder(executable: Path) -> None:
    root = executable.parent.parent if executable.suffix == ".exe" else executable.parent
    manifest_path = root / "radiomind-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Digital decoder manifest missing; run scripts/install_digital.py")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "v" + VERSION or not manifest.get("files"):
        raise RuntimeError("Unsupported digital decoder manifest")
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise RuntimeError("Digital decoder file missing or outside installation")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Digital decoder integrity check failed")


def capabilities(
    configured: Path | None = None, input_mode: str = "flat_fm", tetra: bool = False
) -> dict[str, Any]:
    available = decoder_path(configured).is_file()
    return {
        "backend": "dsd-neo",
        "version": VERSION,
        "installed": available,
        "formats": [
            {
                "name": name,
                "state": (
                    "needs_iq_input"
                    if name == "P25-II" and input_mode != "iq"
                    else "experimental"
                    if available
                    else "not_installed"
                ),
                "transport": input_mode,
                "validation": VALIDATION[name],
                "live_voice_validated": False,
            }
            for name in MODES
            if name != "auto"
        ]
        + [
            {
                "name": "P25-I CQPSK",
                "state": "experimental" if input_mode == "iq" else "needs_iq_input",
                "validation": "synthetic_complex_pipeline_passed",
                "live_voice_validated": False,
            },
            {
                "name": "TETRA TMO",
                "state": "experimental" if tetra else "disabled",
                "validation": "synthetic_bsch_and_codec_only",
                "live_voice_validated": False,
            },
            {"name": "TETRA DMO", "state": "not_implemented"},
        ],
        "trunk_tracking": False,
        "encrypted_audio": False,
    }


class Evidence:
    """Log sync is classification evidence, never a plaintext/voice guarantee."""

    def __init__(self) -> None:
        self.protocol: str | None = None
        self.counts: dict[str, int] = {}
        self.encrypted = False
        self.context: str | None = None
        self.context_syncs = 0
        self.encryption_at: dict[str, float] = {}
        self.invalid_counts: dict[str, int] = {}
        self.dmr_direct_frames = 0
        self.dmr_bs_seen = False
        self.dmr_calls: dict[str, tuple[tuple[str, str], int]] = {}
        self.dmr_call_repeats = 0
        self.dmr_frames = DMRMetadata()
        self.last_sync_seconds = -100.0

    def observe(self, line: str, input_seconds: float = 0.0) -> None:
        line = ANSI.sub("", line)
        # Do not interpret startup help/options as received RF metadata.
        if line.startswith(("NOTICE:", "WARNING:")):
            return
        match = SYNC.search(line)
        invalid = bool(INVALID.search(line))
        if match:
            protocol = ALIASES.get(match[1], match[1])
            if protocol != self.context:
                self.context_syncs = 0
                self.protocol = None
                self.dmr_calls.clear()
                self.dmr_call_repeats = 0
                self.dmr_frames.reset_context()
            self.context = protocol
            if protocol == "DMR" and "[SLOT" in line:
                # Uncertain/mixed BS evidence must prevent destructive mono folding.
                self.dmr_bs_seen = True
            if not invalid:
                self.last_sync_seconds = input_seconds
                self.counts[protocol] = self.counts.get(protocol, 0) + 1
                self.context_syncs += 1
                if protocol == "DMR":
                    if "MS/DM MODE/MONO" in line:
                        self.dmr_direct_frames += 1
                # A new valid frame belongs to its own mode. Never keep the old
                # mode's label while waiting for this mode's second sync/PCM.
                self.protocol = protocol if self.context_syncs >= 2 else None
        if invalid and self.context:
            self.invalid_counts[self.context] = self.invalid_counts.get(self.context, 0) + 1
        call = DMR_CALL.search(line)
        if (
            call
            and not invalid
            and self.context == "DMR"
            and all(int(x) > 0 for x in call.groups())
        ):
            identity = (call[2], call[3])
            previous, repeats = self.dmr_calls.get(call[1], (None, 0))
            self.dmr_calls[call[1]] = (identity, repeats + 1 if identity == previous else 1)
            # Alternating independent TDMA calls must not reset each other's
            # confirmation. Addresses stay transient, never in persisted evidence.
            self.dmr_call_repeats = max(count for _, count in self.dmr_calls.values())
        dmr_crypto = False
        if self.context == "DMR" and self.context_syncs >= 2:
            if 0 <= input_seconds - self.last_sync_seconds <= 1.0:
                dmr_crypto = self.dmr_frames.observe(line, invalid=invalid)
        if not invalid and self.context and (ENCRYPTED.search(line) or dmr_crypto):
            self.encrypted = True
            self.encryption_at[self.context] = input_seconds


@dataclass(frozen=True)
class AudioPacket:
    input_seconds: float
    pcm: bytes
    slot: int | None = None
    sample_offset: int | None = None

    @property
    def channels(self) -> int:
        return len(self.pcm) // 320


def command(
    executable: Path, mode: str, input_port: int, output_port: int, *, iq: bool = False
) -> list[str]:
    # Intentionally no arbitrary extra arguments: no RF device, TX, keys,
    # reverse mute, relaxed CRC, network upload, config import or trunk control.
    return [
        str(executable),
        "-f" + MODES[mode],
        "-i",
        f"rtltcp:127.0.0.1:{input_port}:851.375M:0:0:48:0:1"
        if iq
        else f"tcp:127.0.0.1:{input_port}",
        "-o",
        f"udp:127.0.0.1:{output_port}",
        "-s",
        "48000",
        "--frontend",
        "none",
        "--rdio-mode",
        "off",
    ]


class DigitalDecoder:
    def __init__(self, executable: Path, mode: str = "auto", *, iq: bool = False) -> None:
        if mode not in MODES:
            raise ValueError("Unknown digital decoder mode")
        if not executable.is_file():
            raise RuntimeError("Digital decoder not installed; run scripts/install_digital.py")
        self.mode = mode
        self.iq_input = iq
        self.iq_encoder = DigitalIQEncoder()
        self.rate_ready = threading.Event()
        self.evidence = Evidence()
        self.lock = threading.Lock()
        self.input_samples = 0
        self.sent_bytes = 0
        self.max_send_ms = 0.0
        self.transport_failure: dict[str, Any] | None = None
        self.log_tail: deque[str] = deque(maxlen=12)
        self.error: str | None = None
        self.last_output = time.monotonic()
        self.closed = False
        self.stopping = threading.Event()
        self.inputs: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
        self.outputs: queue.Queue[AudioPacket] = queue.Queue(maxsize=512)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(3)
        self.audio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.audio.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        self.audio.bind(("127.0.0.1", 0))
        self.audio.settimeout(0.1)
        self.connection: socket.socket | None = None
        self.threads: list[threading.Thread] = []
        self.process: subprocess.Popen[bytes] | None = None
        try:
            self.process = subprocess.Popen(
                command(
                    executable,
                    mode,
                    self.listener.getsockname()[1],
                    self.audio.getsockname()[1],
                    iq=iq,
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=0x08000000 if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
                cwd=executable.parent,
                env={
                    **{k: v for k, v in os.environ.items() if not k.startswith("DSD_NEO_")},
                    "DSD_NEO_LOG_SINK": "stderr",
                    **(
                        {
                            "DSD_NEO_DISABLE_FS4_SHIFT": "1",
                            "DSD_NEO_COMBINE_ROT": "0",
                            "DSD_NEO_TCP_PREBUF_MS": "20",
                        }
                        if iq
                        else {}
                    ),
                },
            )
            for target in (self._logs, self._audio):
                self._thread(target)
            self.connection, _ = self.listener.accept()
            self.connection.settimeout(1)
            self.listener.close()
            if iq:
                self.connection.sendall(struct.pack(">4sII", b"RTL0", 0, 0))
                self._thread(self._commands)
                if not self.rate_ready.wait(3):
                    raise RuntimeError("Digital IQ rate negotiation failed")
                self.check()
            self._thread(self._send)
        except Exception:
            self.close()
            raise

    def _thread(self, target: Any) -> None:
        thread = threading.Thread(target=target, daemon=True)
        self.threads.append(thread)
        thread.start()

    def _logs(self) -> None:
        assert self.process and self.process.stderr
        while not self.stopping.is_set():
            line = self.process.stderr.readline(8192)
            if not line:
                return
            with self.lock:
                text = line.decode("utf-8", errors="replace").strip()
                if "rtl_tcp:" in text:
                    self.log_tail.append(ANSI.sub("", text[text.index("rtl_tcp:") :])[:512])
                self.evidence.observe(text, self.input_samples / 48000)

    def _audio(self) -> None:
        while not self.stopping.is_set():
            try:
                data, address = self.audio.recvfrom(8192)
                if address[0] != "127.0.0.1":
                    continue
                if len(data) not in {320, 640}:
                    self.error = "Unexpected digital PCM packet; capture interrupted"
                    return
                self.last_output = time.monotonic()
                self.outputs.put_nowait(AudioPacket(self.input_samples / 48000, data))
            except TimeoutError:
                continue
            except queue.Full:
                self.error = "Digital output queue overflow; capture interrupted"
                return
            except OSError:
                return

    def _send(self) -> None:
        assert self.connection is not None
        while not self.stopping.is_set():
            try:
                data = self.inputs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if data is None:
                    return
                started = time.monotonic()
                self.connection.sendall(data)
                self.sent_bytes += len(data)
                self.max_send_ms = max(self.max_send_ms, (time.monotonic() - started) * 1000)
            except OSError as exc:
                if not self.stopping.is_set():
                    self.transport_failure = {
                        "exception": type(exc).__name__,
                        "errno": exc.errno,
                        "winerror": getattr(exc, "winerror", None),
                        "message": str(exc),
                        "send_ms": round((time.monotonic() - started) * 1000, 2),
                        "process_exit": self.process.poll() if self.process else None,
                    }
                    self.error = f"Digital decoder input failed ({self.mode}: {type(exc).__name__})"
                return
            finally:
                self.inputs.task_done()

    def _commands(self) -> None:
        """Virtual device only. No command is ever forwarded to the RF source."""
        assert self.connection is not None
        pending = bytearray()
        while not self.stopping.is_set():
            try:
                data = self.connection.recv(1024)
                if not data:
                    return
                pending.extend(data)
                while len(pending) >= 5:
                    op, value = struct.unpack(">BI", pending[:5])
                    del pending[:5]
                    if (op == 1 and value != 851375000) or (op == 2 and value != 1536000):
                        self.error = "Decoder requested unsupported virtual IQ tuning/rate"
                        self.rate_ready.set()
                        return
                    if op == 2:
                        self.rate_ready.set()
                    # Gain/PPM/driver controls are consumed locally and do nothing.
            except TimeoutError:
                continue
            except OSError:
                return

    def feed_iq(self, iq48: np.ndarray[Any, Any]) -> None:
        self.check()
        self.feed_iq_bytes(self.iq_encoder.encode(iq48))

    def feed_iq_bytes(self, encoded: bytes) -> None:
        """Share one immutable virtual RTL block across independent decoder queues."""
        self.check()
        if not self.iq_input or len(encoded) % 64 or len(encoded) > 48000 * 64:
            raise RuntimeError("Invalid encoded complex digital input")
        self.input_samples += len(encoded) // 64
        try:
            self.inputs.put_nowait(encoded)
        except queue.Full as exc:
            self.error = "Digital IQ queue overflow; capture interrupted"
            raise RuntimeError(self.error) from exc

    def feed(self, flat_audio: Audio) -> None:
        self.check()
        # 1.0 is 2.5 kHz deviation, with headroom for wider FSK deviation.
        pcm = np.asarray(np.clip(flat_audio * 6000, -32767, 32767), dtype="<i2")
        self.input_samples += len(pcm)
        try:
            self.inputs.put_nowait(pcm.tobytes())
        except queue.Full as exc:
            self.error = "Digital input queue overflow; capture interrupted"
            raise RuntimeError(self.error) from exc

    def check(self) -> None:
        if self.error:
            raise RuntimeError(self.error)
        if self.closed or (self.process is not None and self.process.poll() is not None):
            raise RuntimeError("Digital decoder stopped unexpectedly")

    def drain(self) -> list[AudioPacket]:
        packets = []
        while True:
            try:
                packets.append(self.outputs.get_nowait())
            except queue.Empty:
                return packets

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "protocol": self.evidence.protocol,
                "encrypted": self.evidence.encrypted,
                "encryption_at": dict(self.evidence.encryption_at),
                "sync_counts": dict(self.evidence.counts),
                "invalid_counts": dict(self.evidence.invalid_counts),
                "dmr_frames": self.evidence.dmr_frames.snapshot(),
                "dmr_call_confirmed": self.evidence.dmr_call_repeats >= 2,
                "dmr_direct_mono": self.evidence.dmr_direct_frames >= 2
                and not self.evidence.dmr_bs_seen,
                "input_level": self.iq_encoder.status() if self.iq_input else {},
                "error": self.error,
                "transport": {
                    "mode": self.mode,
                    "sent_bytes": self.sent_bytes,
                    "input_samples": self.input_samples,
                    "queued_blocks": self.inputs.qsize(),
                    "max_send_ms": round(self.max_send_ms, 2),
                    "failure": self.transport_failure,
                    "log_tail": list(self.log_tail) if self.transport_failure else [],
                },
            }

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        # Bounded drain: no retune while closing, keep last decoder output.
        deadline = time.monotonic() + 0.6
        try:
            self.inputs.put_nowait(None)
        except queue.Full:
            self.error = self.error or "Digital decoder did not drain input"
        while self.inputs.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        if self.inputs.unfinished_tasks:
            self.error = self.error or "Digital decoder drain timeout"
        # Keep TCP open until termination: upstream reconnects after EOF.
        # Let any already-produced tail audio reach the UDP reader first.
        drain_until = time.monotonic() + 0.4
        while time.monotonic() < drain_until and time.monotonic() - self.last_output < 0.15:
            time.sleep(0.01)
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                if sys.platform == "win32":
                    self.process.terminate()
                else:
                    os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    if sys.platform == "win32":
                        self.process.kill()
                    else:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=1)
        self.stopping.set()
        for sock in (self.connection, self.listener, self.audio):
            if sock is not None:
                sock.close()
        for thread in self.threads:
            thread.join(timeout=1)
        if self.process is not None and self.process.stderr is not None:
            self.process.stderr.close()
