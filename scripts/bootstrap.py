"""Install the source checkout into its own venv; no receiver or model downloads."""

import argparse
import platform
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        raise SystemExit("Use CPython 3.11, 3.12 or 3.13 (64-bit)")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit(
            "Current installation target is x86-64; Raspberry Pi is deferred"
        )
    target = ROOT / ".venv"
    python = target / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(target)
    for args in (
        ["-m", "pip", "install", "-r", "requirements-build.lock"],
        ["-m", "pip", "install", "--only-binary=:all:", "-r", "requirements.lock"],
        [
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            "--no-deps",
            "-e",
            "./backend",
        ],
        ["-m", "pip", "check"],
    ):
        subprocess.run([str(python), *args], cwd=ROOT, check=True)
    print("Source environment ready. Default start is a mock receiver.")


if __name__ == "__main__":
    main()
