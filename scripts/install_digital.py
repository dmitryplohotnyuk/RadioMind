"""Explicit pinned DSD-neo installation. Downloads public software, never RF data."""

import hashlib
import json
import os
import platform
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v2.10.0"
ASSETS = {
    "Windows": (
        "dsd-neo-msvc-x86_64-native-v2.10.0.zip",
        "4cc5e752e17ca659fc615f5b5441e82e81e5cb361e2ce4d8b857fa90863fee66",
    ),
    "Linux": (
        "dsd-neo-linux-x86_64-portable-v2.10.0.AppImage",
        "492f0980c8d0891dd18e4283c745eefc2d7aaadeeb68cae4a31cc70e57dc0fdf",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    system = platform.system()
    if system not in ASSETS or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Pinned binary installer supports Windows/Linux x86_64 only")
    name, expected = ASSETS[system]
    root = ROOT / "tools" / "digital"
    root.mkdir(parents=True, exist_ok=True)
    package = root / name
    if not package.exists():
        urllib.request.urlretrieve(
            f"https://github.com/arancormonk/dsd-neo/releases/download/{VERSION}/{name}",
            package,
        )
    if digest(package) != expected:
        raise SystemExit("Decoder package hash mismatch; nothing installed")
    target = root / "dsd-neo"
    if system == "Windows":
        with zipfile.ZipFile(package) as archive:
            for info in archive.infolist():
                path = target / info.filename
                if (
                    not path.resolve().is_relative_to(target.resolve())
                    or info.file_size > 100_000_000
                ):
                    raise SystemExit("Unsafe package entry")
                if info.is_dir():
                    continue
                data = archive.read(info)
                if path.exists() and path.read_bytes() != data:
                    raise SystemExit(
                        f"Existing decoder file differs: {path}; not overwritten"
                    )
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_bytes(data)
        executable = target / "bin" / "dsd-neo.exe"
        runtime_files = list((target / "bin").glob("*.dll")) + [executable]
    else:
        # Extract once: no FUSE/privileged container requirement at runtime.
        if not target.exists():
            package.chmod(0o755)
            stage = root / "appimage-extraction"
            stage.mkdir(exist_ok=False)
            subprocess.run(
                [str(package), "--appimage-extract"],
                cwd=stage,
                check=True,
                stdout=subprocess.DEVNULL,
                timeout=120,
            )
            (stage / "squashfs-root").rename(target)
        executable = target / "AppRun"
        runtime_files = [
            p for p in target.rglob("*") if p.is_file() and not p.is_symlink()
        ]
    result = subprocess.run(
        [str(executable), "-h"],
        capture_output=True,
        timeout=20,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if result.returncode != 0 or b"Usage: dsd-neo" not in result.stdout + result.stderr:
        raise SystemExit("Installed decoder launch check failed")
    manifest = {
        "version": VERSION,
        "package_sha256": expected,
        "files": {
            str(p.relative_to(target)).replace("\\", "/"): digest(p)
            for p in runtime_files
        },
    }
    (target / "radiomind-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(
        f"Installed DSD-neo {VERSION}; offline RX adapter ready for testing: {executable}"
    )


if __name__ == "__main__":
    main()
