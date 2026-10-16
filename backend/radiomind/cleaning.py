"""Optional, local archive copies. Never participates in RX or speech decisions."""

import asyncio
import ctypes as ct
import hashlib
import os
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import resample_poly

from radiomind.recording import Archive

ROOT = Path(__file__).resolve().parents[2]
DLL_HASH = "06770aeb8855ef942b5dcdb436f84dfdd5867b716ba4b4c8a2c66ade03197f31"
VERSION = "rnnoise-v02-preserve-level-delay20ms-v3"
MAX_SECONDS = 600


def library_path() -> Path:
    # Only this binary has been measured. Other platforms retain original playback.
    path = ROOT / "tools/rnnoise/rnnoise.dll"
    if sys.platform != "win32" or not path.is_file():
        raise RuntimeError("Очистка недоступна: установите RNNoise для Windows")
    if hashlib.sha256(path.read_bytes()).hexdigest() != DLL_HASH:
        raise RuntimeError("RNNoise: контрольная сумма библиотеки не совпала")
    return path


def rnnoise_wet(pcm: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """PCM16-scale floats, mono 16 kHz; aligned wet output, including flushed tail."""
    if not len(pcm):
        return np.empty(0, dtype=np.float32)
    lib = ct.CDLL(str(library_path()))
    lib.rnnoise_create.argtypes = [ct.c_void_p]
    lib.rnnoise_create.restype = ct.c_void_p
    lib.rnnoise_destroy.argtypes = [ct.c_void_p]
    lib.rnnoise_destroy.restype = None
    lib.rnnoise_process_frame.argtypes = [
        ct.c_void_p,
        ct.POINTER(ct.c_float),
        ct.POINTER(ct.c_float),
    ]
    lib.rnnoise_process_frame.restype = ct.c_float
    original = pcm.astype(np.float32)
    up = resample_poly(original, 3, 1).astype(np.float32)
    padded = np.pad(up, (0, 960 + (-len(up) % 480)))
    output = np.zeros_like(padded)
    state = lib.rnnoise_create(None)
    if not state:
        raise RuntimeError("RNNoise could not create state")
    try:
        for i in range(0, len(padded), 480):
            lib.rnnoise_process_frame(
                state,
                output[i : i + 480].ctypes.data_as(ct.POINTER(ct.c_float)),
                padded[i : i + 480].ctypes.data_as(ct.POINTER(ct.c_float)),
            )
    finally:
        lib.rnnoise_destroy(state)
    wet = resample_poly(output[960 : 960 + len(up)], 1, 3)[: len(original)]
    return wet


def adaptive_mix(original: np.ndarray[Any, Any], wet: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Bounded, smoothly varying suppression; residual is an estimate, not speech truth."""
    if not len(original):
        return original.copy()
    residual = uniform_filter1d((original - wet) ** 2, size=1600)
    total = uniform_filter1d(original**2, size=1600)
    strength = 0.35 + 0.6 * np.clip((residual / (total + 1) - 0.03) / 0.25, 0, 1)
    # A large residual can be rejected speech, not just noise. Check the clip's
    # robust upper level: isolated surviving clicks must not hide model collapse.
    # On collapse retain dry audio conservatively; otherwise allow suppression
    # of noise-only intervals. This is not a claim that the input contains speech.
    wet_power = uniform_filter1d(wet**2, size=1600)
    level_region = total > 1  # Exclude exact squelch silence from level matching.
    if not np.any(level_region):
        return original.copy()
    source_level = np.percentile(np.sqrt(total[level_region]), 90)
    wet_level = np.percentile(np.sqrt(np.maximum(wet_power[level_region], 0)), 90)
    if wet_level < source_level * 0.5:
        retained = wet_power / (total + 1)
        ceiling = 0.25 + 0.7 * np.clip((retained - 0.02) / 0.3, 0, 1)
        strength = np.minimum(strength, ceiling)
    strength = uniform_filter1d(strength, size=800)
    result = original + strength * (wet - original)
    # Existing zero-valued squelch pauses are authoritative, not a new speech gate.
    edges = np.diff(np.r_[False, original == 0, False].astype(np.int8))
    for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True):
        if end - start >= 320:
            result[start:end] = 0
    # One constant gain avoids pumping pauses. This is a signal-level match,
    # not a speech detector; limit it to 3.52 dB and available peak headroom.
    output_level = np.percentile(
        np.sqrt(np.maximum(uniform_filter1d(result**2, size=1600)[level_region], 0)), 90
    )
    peak = float(np.max(np.abs(result)))
    gain = min(1.5, max(1.0, source_level / max(float(output_level), 1)))
    gain = min(gain, max(1.0, 32000 / max(peak, 1)))
    result *= gain
    return result


def denoise(pcm: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """PCM16 mono 16 kHz -> same count; compensate 20 ms RNNoise delay and flush tail."""
    original = pcm.astype(np.float32)
    wet = rnnoise_wet(original)
    # Conservative model-collapse fallback and bounded level matching; no cuts
    # and no modification of acquisition/VAD.
    mixed = adaptive_mix(original, wet)
    if not np.all(np.isfinite(mixed)):
        raise RuntimeError("RNNoise returned invalid samples")
    return np.clip(np.rint(mixed), -32767, 32767).astype("<i2")


def make_copy(paths: list[Path], output: Path) -> None:
    if output.exists():
        raise FileExistsError("Cleaned copy already exists")
    chunks = []
    samples = 0
    for path in paths:
        with wave.open(str(path), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise RuntimeError("Unsupported WAV format")
            samples += wav.getnframes()
            if samples > MAX_SECONDS * 16000:
                raise RuntimeError("Для очистки выберите разговор до 10 минут")
            chunks.append(np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2"))
    if not samples:
        raise RuntimeError("Empty conversation")
    cleaned = denoise(np.concatenate(chunks))
    # Exclusive creation; originals and any earlier partial copy are preserved.
    partial = output.with_suffix(".partial.wav")
    with partial.open("xb") as handle, wave.open(handle, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(cleaned.tobytes())
    partial.rename(output)


class Cleaner:
    def __init__(self, archive: Archive) -> None:
        self.archive = archive
        self.task: asyncio.Task[None] | None = None
        self.states: dict[str, str] = {}
        self.errors: dict[str, str] = {}

    def path(self, session_id: str) -> Path:
        return self.archive.path(session_id).with_suffix(".clean-v3.wav")

    def playback_path(self, session_id: str) -> Path:
        current = self.path(session_id)
        if current.is_file():
            return current
        previous = self.archive.path(session_id).with_suffix(".clean-v2.wav")
        if previous.is_file():
            return previous
        return self.archive.path(session_id).with_suffix(".clean-v1.wav")

    def status(self, session_id: str) -> str:
        if self.path(session_id).is_file():
            return "ready"
        if session_id not in self.states and self.playback_path(session_id).is_file():
            return "outdated"
        return self.states.get(session_id, "original")

    def start(self, session_id: str) -> str:
        output = self.path(session_id)
        if self.status(session_id) in {"ready", "processing"}:
            return self.status(session_id)
        if self.task and not self.task.done():
            raise RuntimeError("Уже очищается другая запись. Попробуйте после её завершения")
        library_path()
        parts = self.archive.store.session_parts(session_id)
        if not parts or any(p["status"] == "recording" or not p.get("playable") for p in parts):
            raise ValueError("Сначала дождитесь завершения записи")
        paths = [self.archive.path(p["id"]) for p in parts]
        needed = 44 + sum(p.stat().st_size - 44 for p in paths)
        if needed <= 44 or needed > 44 + MAX_SECONDS * 32000:
            raise ValueError("Для очистки выберите разговор до 10 минут")
        if output.with_suffix(".partial.wav").exists():
            raise RuntimeError("Сохранена незавершённая копия; исходник доступен для прослушивания")
        self.archive.reserve_check(needed)
        self.archive.reserved_bytes += needed
        self.states = {session_id: "processing"}
        self.errors = {}
        self.task = asyncio.create_task(self._run(session_id, paths, output, needed))
        return "processing"

    async def _run(self, session_id: str, paths: list[Path], output: Path, needed: int) -> None:
        try:
            command = [sys.executable, "-m", "radiomind.cleaning", str(output), *map(str, paths)]
            env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
            result = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
                if sys.platform == "win32"
                else 0,
            )
            if result.returncode or not output.is_file() or output.stat().st_size != needed:
                raise RuntimeError("Не удалось очистить запись; оригинал сохранён")
            self.states[session_id] = "ready"
        except Exception as exc:
            self.states[session_id] = "failed"
            self.errors[session_id] = str(exc)
        finally:
            self.archive.reserved_bytes -= needed
            self.archive.used_bytes += sum(
                p.stat().st_size for p in [output, output.with_suffix(".partial.wav")] if p.exists()
            )

    async def close(self) -> None:
        if self.task:
            await self.task


if __name__ == "__main__":
    make_copy([Path(p) for p in sys.argv[2:]], Path(sys.argv[1]))
