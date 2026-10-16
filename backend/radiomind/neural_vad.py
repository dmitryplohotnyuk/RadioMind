"""Local CPU Silero v6.2 inference; explicit streaming state, no network calls."""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

MODEL_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
MODEL_PATH = Path(__file__).resolve().parents[2] / "tools/silero-vad/silero_vad.onnx"


@lru_cache(maxsize=1)
def load_session() -> Any:
    import onnxruntime as ort

    if not MODEL_PATH.is_file():
        raise RuntimeError("Silero model missing; run scripts/install_silero.py")
    if hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() != MODEL_SHA256:
        raise RuntimeError("Silero model checksum mismatch")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    ort.disable_telemetry_events()
    return ort.InferenceSession(
        str(MODEL_PATH), sess_options=options, providers=["CPUExecutionProvider"]
    )


class SileroProbability:
    """Input is normalized PCM at 16 kHz. Each result covers 512 samples (32 ms)."""

    def __init__(self) -> None:
        self.session = load_session()
        self.state: NDArray[np.float32] = np.zeros((2, 1, 128), dtype=np.float32)
        self.context: NDArray[np.float32] = np.zeros((1, 64), dtype=np.float32)
        self.pending: NDArray[np.float32] = np.empty(0, dtype=np.float32)

    def push(self, samples: np.ndarray) -> list[float]:
        self.pending = np.concatenate((self.pending, samples.astype(np.float32)))
        results = []
        offset = 0
        while len(self.pending) - offset >= 512:
            chunk = self.pending[offset : offset + 512].reshape(1, 512)
            model_input = np.concatenate((self.context, chunk), axis=1)
            probability, self.state = self.session.run(
                None,
                {"input": model_input, "state": self.state, "sr": np.array(16000, dtype=np.int64)},
            )
            self.context = chunk[:, -64:].copy()
            results.append(float(probability[0][0]))
            offset += 512
        self.pending = self.pending[offset:].copy()
        return results
