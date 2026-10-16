"""Install a checksum-pinned native asset, without heavy Python wrapper dependencies."""

import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

WHEEL = "pyrnnoise-0.4.5-py3-none-win_amd64.whl"
SHA = "f46015e5a58212d2883bf8e5a2cafb3c6b115176d8039f8340132cb24866b7da"
DLL_SHA = "06770aeb8855ef942b5dcdb436f84dfdd5867b716ba4b4c8a2c66ade03197f31"
ROOT = Path(__file__).resolve().parents[1] / "tools/rnnoise"


def get(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read(32 * 1024**2)


def main():
    if sys.platform != "win32":
        print(
            "RNNoise copy feature is currently validated on Windows x64 only; original audio remains available."
        )
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / "rnnoise.dll"
    if not path.exists():
        metadata = json.loads(get("https://pypi.org/pypi/pyrnnoise/0.4.5/json"))
        url = next(p["url"] for p in metadata["urls"] if p["filename"] == WHEEL)
        payload = get(url)
        if hashlib.sha256(payload).hexdigest() != SHA:
            raise RuntimeError("RNNoise package checksum mismatch")
        with zipfile.ZipFile(io.BytesIO(payload)) as wheel:
            native = wheel.read("pyrnnoise-0.4.5.data/purelib/pyrnnoise/rnnoise.dll")
            if hashlib.sha256(native).hexdigest() != DLL_SHA:
                raise RuntimeError("RNNoise DLL checksum mismatch")
            path.write_bytes(native)
            (ROOT / "WRAPPER-LICENSE").write_bytes(
                wheel.read("pyrnnoise-0.4.5.dist-info/licenses/LICENSE")
            )
    if hashlib.sha256(path.read_bytes()).hexdigest() != DLL_SHA:
        raise RuntimeError("Existing RNNoise DLL checksum mismatch; preserved")
    if not (ROOT / "COPYING").exists():
        (ROOT / "COPYING").write_bytes(
            get("https://raw.githubusercontent.com/xiph/rnnoise/v0.2/COPYING")
        )
    print("Pinned RNNoise native library ready:", path)


if __name__ == "__main__":
    main()
