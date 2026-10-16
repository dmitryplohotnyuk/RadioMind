"""Install pinned public Silero assets only; never reads RF recordings."""

import hashlib
import urllib.request
from pathlib import Path

MODEL_HASH = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
ROOT = Path(__file__).resolve().parents[1] / "tools/silero-vad"
BASE = "https://raw.githubusercontent.com/snakers4/silero-vad/v6.2/"


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    target = ROOT / "silero_vad.onnx"
    if target.exists():
        payload = target.read_bytes()
    else:
        with urllib.request.urlopen(
            BASE + "src/silero_vad/data/silero_vad.onnx", timeout=60
        ) as response:
            payload = response.read(10 * 1024**2)
    if hashlib.sha256(payload).hexdigest() != MODEL_HASH:
        raise RuntimeError("Model checksum mismatch; existing file was not overwritten")
    license_path = ROOT / "LICENSE"
    if not license_path.exists():
        with urllib.request.urlopen(BASE + "LICENSE", timeout=30) as response:
            license_path.write_bytes(response.read(65536))
    if not target.exists():
        target.write_bytes(payload)
    print(f"Silero v6.2 ready: {target}; SHA256 {MODEL_HASH}")


if __name__ == "__main__":
    main()
