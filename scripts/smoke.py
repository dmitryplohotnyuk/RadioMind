"""Isolated HTTP smoke test with the mock receiver and a disposable archive."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    (ROOT / "runtime").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="mock-smoke-", dir=ROOT / "runtime"
    ) as temporary:
        with (Path(temporary) / "server.log").open("w+", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "radiomind",
                    "--config",
                    "config/example.yaml",
                    "--data-dir",
                    temporary,
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Mock service exited before readiness")
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/api/status", timeout=1
                        ) as r:
                            status = json.load(r)
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Mock service readiness timeout")
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/", timeout=3
                ) as r:
                    assert b"RadioMind" in r.read(), "Frontend missing"
                assert status.get("source") == "mock", status
                assert status.get("running") is True, status
                print(
                    "Mock HTTP smoke passed: frontend + running mock; isolated archive, no USB"
                )
            finally:
                # Windows venv python.exe can be a redirector with a real child.
                # Reap only this spawned tree before removing its mock database.
                try:
                    parent = psutil.Process(process.pid)
                    owned = parent.children(recursive=True) + [parent]
                except psutil.NoSuchProcess:
                    owned = []
                for child in owned:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                _, alive = psutil.wait_procs(owned, timeout=10)
                for child in alive:
                    child.kill()
                psutil.wait_procs(alive, timeout=5)
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
