"""Read-only installation checks. Does not open USB, start RX or enumerate devices."""

import argparse
import platform
import sys
from pathlib import Path

from radiomind.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/example.yaml")
    parser.add_argument("--hackrf-library", type=Path)
    args = parser.parse_args()
    settings = load_settings(args.config)
    failures = []
    print(
        f"{platform.system()} {platform.machine()}, Python {platform.python_version()}"
    )
    print(
        f"Profile: {settings.source}; audio={settings.audio.enabled}; digital={settings.digital.enabled}"
    )
    if not (ROOT / "frontend/index.html").is_file():
        failures.append(
            "Keep the full source tree; standalone wheel installation is unsupported"
        )
    if settings.source == "hackrf":
        if args.hackrf_library is None or not args.hackrf_library.is_file():
            failures.append("Pass --hackrf-library with the native DLL/.so path")
    if settings.audio.enabled and settings.audio.vad_engine == "silero":
        from radiomind.neural_vad import SileroProbability

        try:
            SileroProbability()
            print("Silero: loaded")
        except Exception as error:
            failures.append(f"Silero: {error}")
    if settings.digital.enabled:
        from radiomind.digital import decoder_path, verify_decoder

        try:
            verify_decoder(settings.digital.executable or decoder_path())
            print("DSD-neo: manifest verified")
        except Exception as error:
            failures.append(f"DSD-neo: {error}")
    for failure in failures:
        print(f"FAIL: {failure}")
    print(
        "No hardware tested. RNNoise cleanup: Windows x64 only. Raspberry Pi: deferred."
    )
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
