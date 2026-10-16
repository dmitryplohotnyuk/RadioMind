import argparse
from pathlib import Path

import uvicorn

from radiomind.api import ROOT, create_app
from radiomind.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RadioMind RX-only scanner and local audio archive"
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "example.yaml")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--hackrf-library", type=Path)
    parser.add_argument(
        "--paused", action="store_true", help="Open the archive without starting capture"
    )
    parser.add_argument(
        "--approve-rx",
        action="store_true",
        help="Explicitly authorize physical RX for the configured windows",
    )
    args = parser.parse_args()
    settings = load_settings(args.config)
    if settings.source == "hackrf" and not args.approve_rx:
        parser.error("Hardware capture requires --approve-rx and an authorized profile")
    app = create_app(settings, args.data_dir, args.hackrf_library, autostart=not args.paused)
    print(f"RadioMind: http://127.0.0.1:{args.port} (local access, no login)", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
