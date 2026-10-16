"""Disposable documentation demo: invented metadata and silent WAV, never RF/USB."""

import argparse
import tempfile
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn

from radiomind.api import create_app
from radiomind.config import Settings, Window
from radiomind.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def seed(data: Path) -> None:
    store = Store(data / "mock.sqlite3", 10000)
    audio = data / "mock-audio"
    audio.mkdir()
    try:
        groups = [(145500000, "Demo · Local club"), (433500000, "Demo · Field team")]
        start = datetime(2026, 1, 15, 10, 30, tzinfo=UTC)
        for index, seconds in enumerate([42, 28, 65, 19, 34]):
            frequency, title = groups[index // 3]
            ident = f"{index + 1:032x}"
            with wave.open(str(audio / f"{ident}.wav"), "wb") as handle:
                handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                handle.writeframes(b"\0\0" * 16000 * seconds)
            store.save_recording(
                {
                    "id": ident,
                    "session_id": ident,
                    "part_number": 1,
                    "frequency_hz": frequency,
                    "start_utc": (start - timedelta(minutes=index * 8)).isoformat(),
                    "source": "mock",
                    "status": "complete",
                    "playable": True,
                    "duration_seconds": seconds,
                    "sample_rate": 16000,
                    "snr_db": 18 + index * 3,
                    "title": [
                        "Morning check-in",
                        "Station update",
                        "Club roundtable",
                        "Team check-in",
                        "End of session",
                    ][index],
                    "favorite": index == 0,
                    "listened": index > 1,
                }
            )
            store.save_frequency_profile(frequency, title, index < 3)
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    (ROOT / "runtime").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="docs-demo-", dir=ROOT / "runtime"
    ) as directory:
        data = Path(directory)
        seed(data)
        settings = Settings(
            source="mock",
            windows=[
                Window(name="Demo VHF", start_hz=144000000, end_hz=146000000),
                Window(name="Demo UHF", start_hz=430000000, end_hz=438000000),
            ],
        )
        print(f"Synthetic demo only: http://127.0.0.1:{args.port}", flush=True)
        uvicorn.run(
            create_app(settings, data, autostart=False),
            host="127.0.0.1",
            port=args.port,
        )


if __name__ == "__main__":
    main()
