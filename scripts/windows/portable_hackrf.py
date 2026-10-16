"""Fetch pinned conda-forge native userspace tools locally; never install drivers."""
import hashlib
import io
import json
import tarfile
import urllib.request
import zipfile
from pathlib import Path

import zstandard

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / "tools" / "hackrf"
MANIFEST = ROOT / "docs" / "NATIVE_PACKAGES.json"



def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    manifest = []
    for pinned in json.loads(MANIFEST.read_text(encoding="utf-8")):
        name, basename = pinned["name"], pinned["file"]
        with urllib.request.urlopen(f"https://api.anaconda.org/package/conda-forge/{name}") as r:
            metadata = json.load(r)
        candidates = [f for f in metadata["files"] if f["attrs"].get("subdir") == "win-64"]
        package = next(f for f in candidates if f["basename"] == basename) if basename else candidates[-1]
        url = "https:" + package["download_url"]
        with urllib.request.urlopen(url) as r:
            payload = r.read()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != package["sha256"] or digest != pinned["sha256"]:
            raise RuntimeError(f"Checksum mismatch for {name}")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for member in archive.namelist():
                if member.startswith("pkg-") and member.endswith(".tar.zst"):
                    with zstandard.ZstdDecompressor().stream_reader(archive.open(member)) as stream:
                        with tarfile.open(fileobj=stream, mode="r|") as tar:
                            tar.extractall(DESTINATION, filter="data")
        manifest.append({"name": name, "file": package["basename"], "url": url,
                         "sha256": digest, "license": package["attrs"].get("license"),
                         "dependencies": package["attrs"].get("depends")})
        print(f"Extracted {package['basename']}", flush=True)
    (DESTINATION / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
