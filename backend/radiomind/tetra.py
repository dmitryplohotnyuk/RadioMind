"""Experimental TMO downlink receiver. Fixed local bit pipe, no RF or key interface."""

import base64
import hashlib
import json
import os
import queue
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from radiomind.digital import ROOT, AudioPacket, DigitalDecoder
from radiomind.digital_level import DigitalIQEncoder
from radiomind.digital_metadata import worker_summary
from radiomind.tetra_dsp import TetraDemodulator

REVISION = "2205072976e18b6fb15b975e734afad2477863ac"


def tetra_path() -> Path:
    return ROOT / "tools/digital/tetra" / ("tetra-rx.exe" if os.name == "nt" else "tetra-rx")


def verify_tetra() -> None:
    root = tetra_path().parent
    manifest = json.loads((root / "radiomind-manifest.json").read_text())
    suffix = ".dll" if os.name == "nt" else ".so"
    required = {tetra_path().name, *(f"codec-{i}{suffix}" for i in range(1, 5))}
    if manifest.get("revision") != REVISION or not required <= manifest.get("files", {}).keys():
        raise RuntimeError("Unsupported TETRA installation")
    for name, digest in manifest["files"].items():
        path = (root / name).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise RuntimeError("TETRA installation integrity check failed")


class TetraDecoder:
    def __init__(self) -> None:
        verify_tetra()
        self.demod = TetraDemodulator()
        self.error: str | None = None
        self.closed = False
        self.input_samples = 0
        self.syncs = 0
        self.encryption_at: dict[str, float] = {}
        self.frame_origin: int | None = None
        self.frame_last: int | None = None
        self.frame_epoch = 0
        self.inputs: queue.Queue[bytes | None] = queue.Queue(64)
        self.outputs: queue.Queue[AudioPacket] = queue.Queue(512)
        self.process = subprocess.Popen(
            [str(tetra_path())],
            cwd=tetra_path().parent,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000 if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        self.threads = [
            threading.Thread(target=target, daemon=True) for target in (self._send, self._read)
        ]
        for thread in self.threads:
            thread.start()

    def _send(self) -> None:
        assert self.process.stdin
        try:
            while True:
                data = self.inputs.get()
                try:
                    if data is None:
                        return
                    self.process.stdin.write(data)
                    self.process.stdin.flush()
                finally:
                    self.inputs.task_done()
        except OSError:
            if not self.closed:
                self.error = "TETRA input pipe failed"
        finally:
            self.process.stdin.close()

    def _read(self) -> None:
        assert self.process.stdout
        try:
            while line := self.process.stdout.readline(4097):
                if len(line) > 4096 or not line.endswith(b"\n"):
                    raise ValueError("Oversized TETRA output")
                self.accept(json.loads(line))
        except (ValueError, KeyError, TypeError, queue.Full):
            self.error = "Invalid or overflowing TETRA output; capture interrupted"

    def accept(self, event: dict[str, Any]) -> None:
        """Validate native messages before PCM can enter the archive timeline."""
        kind = event["type"]
        if kind == "sync":
            self.syncs += 1
            return
        slot = event["slot"]
        if type(slot) is not int or slot not in {1, 2, 3, 4}:
            raise ValueError("Invalid TETRA slot")
        if kind == "encrypted":
            # Conservative whole-call veto, including any earlier clear packets.
            self.encryption_at["TETRA"] = self.input_samples / 48000
            return
        if kind != "audio" or self.syncs < 2 or self.encryption_at:
            return
        fn, mn = event["fn"], event["mn"]
        if type(fn) is not int or type(mn) is not int or not 1 <= fn <= 17 or not 1 <= mn <= 60:
            raise ValueError("Invalid TETRA frame clock")
        pcm = base64.b64decode(event["pcm"], validate=True)
        if len(pcm) != 960:
            raise ValueError("Invalid TETRA PCM frame")
        frame = (mn - 1) * 17 + fn - 1
        if self.frame_last is not None and frame - self.frame_last < -510:
            self.frame_epoch += 1020
        elif self.frame_last is not None and frame < self.frame_last:
            raise ValueError("TETRA frame clock moved backwards")
        self.frame_last = frame
        frame += self.frame_epoch
        if self.frame_origin is None:
            self.frame_origin = frame
        offset = (frame - self.frame_origin) * 480
        for part in range(3):
            self.outputs.put_nowait(
                AudioPacket(
                    self.input_samples / 48000,
                    pcm[part * 320 : (part + 1) * 320],
                    slot,
                    offset + part * 160,
                )
            )

    def feed_iq(self, iq48: np.ndarray[Any, Any]) -> None:
        self.check()
        if iq48.ndim != 1 or len(iq48) > 48000:
            raise RuntimeError("TETRA input block exceeds bound")
        self.input_samples += len(iq48)
        try:
            self.inputs.put_nowait(self.demod.process(iq48))
        except queue.Full as exc:
            self.error = "TETRA input queue overflow; capture interrupted"
            raise RuntimeError(self.error) from exc

    def check(self) -> None:
        if self.error or self.closed or self.process.poll() is not None:
            raise RuntimeError(self.error or "TETRA receiver stopped")

    def drain(self) -> list[AudioPacket]:
        result = []
        while not self.outputs.empty():
            result.append(self.outputs.get_nowait())
        return result

    def status(self) -> dict[str, Any]:
        return {
            "protocol": "TETRA" if self.syncs >= 2 else None,
            "sync_counts": {"TETRA": self.syncs},
            "encrypted": bool(self.encryption_at),
            "encryption_at": dict(self.encryption_at),
            "error": self.error,
        }

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.inputs.put(None, timeout=0.2)
        except queue.Full:
            self.error = self.error or "TETRA close queue overflow"
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.error = self.error or "TETRA drain timeout"
            self.process.kill()
            self.process.wait(timeout=2)
        # Wake a sender that failed before consuming its sentinel.
        for thread in self.threads:
            thread.join(timeout=0.2)
        if self.process.stdout:
            self.process.stdout.close()


class DigitalDispatch:
    """Race PCM, not sync labels; once selected, never mix decoder outputs."""

    def __init__(
        self,
        executable: Path,
        mode: str,
        *,
        tetra: bool = True,
        dstar: bool = False,
        p25p2: bool = False,
        dmr: bool = False,
        iq: bool = True,
    ) -> None:
        from radiomind.digital import DigitalDecoder

        if not iq and (tetra or dstar or p25p2):
            raise ValueError("IQ-only probes cannot consume discriminator audio")
        self.workers: list[Any] = []
        self.selected: Any = None
        self.tail: list[AudioPacket] = []
        self.pending: dict[int, list[AudioPacket]] = {}
        self.iq_encoder = DigitalIQEncoder()
        self.selected_protocol: str | None = None
        self.dmr_probe: Any = None
        try:
            if mode == "auto" and dmr:
                self.dmr_probe = DigitalDecoder(executable, "DMR", iq=iq)
                self.workers.append(self.dmr_probe)
            if mode != "TETRA":
                self.workers.append(DigitalDecoder(executable, mode, iq=iq))
            if mode == "auto" and dstar:
                # Fixed-rate D-STAR avoids missing a short call during AUTO SPS hunting.
                self.workers.append(DigitalDecoder(executable, "D-STAR", iq=True))
            if mode == "auto" and p25p2:
                # A short 6000-symbol/s burst can end before AUTO visits this rate.
                self.workers.append(DigitalDecoder(executable, "P25-II", iq=True))
            if tetra and mode in {"auto", "TETRA"}:
                self.workers.append(TetraDecoder())
        except Exception:
            self.close()
            raise

    @property
    def error(self) -> str | None:
        return next((w.error for w in self.workers if w.error), None)

    def feed_iq(self, iq: np.ndarray[Any, Any]) -> None:
        encoded: bytes | None = None
        for worker in self.workers:
            if isinstance(worker, DigitalDecoder):
                if encoded is None:
                    encoded = self.iq_encoder.encode(iq)
                worker.feed_iq_bytes(encoded)
            else:
                worker.feed_iq(iq)

    def check(self) -> None:
        for worker in self.workers:
            worker.check()

    def feed(self, flat_audio: np.ndarray[Any, Any]) -> None:
        for worker in self.workers:
            worker.feed(flat_audio)

    def drain(self) -> list[AudioPacket]:
        if self.tail:
            result, self.tail = self.tail, []
            return result
        if self.selected:
            return self.selected.drain()
        for worker in self.workers:
            packets = self.pending.setdefault(id(worker), [])
            packets.extend(worker.drain())
            if len(packets) > 512:
                raise RuntimeError("Digital selection PCM buffer exceeded")
            status = worker.status()
            if (worker is self.dmr_probe or status["protocol"] == "DMR") and not status.get(
                "dmr_call_confirmed"
            ):
                continue
            if status["protocol"] and any(
                np.any(np.abs(np.frombuffer(p.pcm, dtype="<i2").astype(int)) > 8) for p in packets
            ):
                self.selected = worker
                self.selected_protocol = status["protocol"]
                self.selection_evidence = worker_summary(status)
                self._close_workers([other for other in self.workers if other is not worker])
                self.workers = [worker]
                self.pending.clear()
                return packets
        return []

    def status(self) -> dict[str, Any]:
        if self.selected:
            status = self.selected.status()
            return {
                **status,
                "observed_protocol": status["protocol"],
                "worker_evidence": [worker_summary(status)],
                "selection_evidence": getattr(self, "selection_evidence", {}),
                "protocol": self.selected_protocol,
                "input_level": self.iq_encoder.status() if self.iq_encoder.blocks else {},
            }
        evidence = [worker.status() for worker in self.workers]
        counts: dict[str, int] = {}
        invalid: dict[str, int] = {}
        encrypted: dict[str, float] = {}
        for status in evidence:
            for key, count in status.get("sync_counts", {}).items():
                counts[key] = max(counts.get(key, 0), count)
            for key, count in status.get("invalid_counts", {}).items():
                invalid[key] = max(invalid.get(key, 0), count)
            encrypted.update(status.get("encryption_at", {}))
        return {
            "protocol": None,
            "input_level": self.iq_encoder.status(),
            # Diagnostic hints only: sync without PCM must not select a worker,
            # suppress analog speech, teach a preset or hold the RF frequency.
            "sync_candidates": sorted({s["protocol"] for s in evidence if s.get("protocol")}),
            "encrypted": bool(encrypted),
            "encryption_at": encrypted,
            "sync_counts": counts,
            "invalid_counts": invalid,
            "worker_evidence": [worker_summary(s) for s in evidence],
            "error": self.error,
            "transport": [s["transport"] for s in evidence if "transport" in s],
        }

    def close(self) -> None:
        self._close_workers(self.workers)
        if not self.tail:
            self.tail = self.drain()

    @staticmethod
    def _close_workers(workers: list[Any]) -> None:
        # Drain each independent pipe concurrently so shutdown does not multiply
        # decoder timeouts while continuous RF samples are still being queued.
        if len(workers) <= 1:
            for worker in workers:
                worker.close()
            return
        with ThreadPoolExecutor(max_workers=len(workers)) as pool:
            futures = [pool.submit(worker.close) for worker in workers]
            for future in futures:
                future.result()
