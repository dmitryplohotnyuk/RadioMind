"""Cross-platform development checks; no physical receiver is opened."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    node = shutil.which("node")
    if not node:
        raise SystemExit(
            "Node.js 22 is required for frontend checks (not for running the app)"
        )
    env = dict(
        os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1"
    )
    # Git/source exports omit runtime; pytest requires the basetemp parent.
    (ROOT / "runtime").mkdir(exist_ok=True)
    commands = [
        [sys.executable, "-m", "ruff", "check", "backend"],
        [sys.executable, "-m", "ruff", "format", "--check", "backend"],
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            "backend/pyproject.toml",
            "backend/radiomind",
        ],
        [
            sys.executable,
            "-m",
            "pytest",
            "backend/tests",
            "-q",
            "--basetemp",
            f"runtime/pytest-{uuid4().hex}",
        ],
        [sys.executable, "scripts/release.py"],
        [sys.executable, "scripts/doctor.py"],
        [node, "--check", "frontend/app.js"],
        [node, "--check", "frontend/live-audio.js"],
    ]
    commands.extend(
        [node, f"scripts/check_{name}.cjs"]
        for name in ("i18n", "player", "connection", "live_audio")
    )
    for command in commands:
        subprocess.run(command, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
