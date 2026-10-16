"""Compare bounded RX window timing, no audio/IQ persistence or transmissions."""

import argparse
import json
import time
from pathlib import Path

from radiomind.config import load_settings
from radiomind.dsp import Detector, compute_psd
from radiomind.hackrf import HackRFSource
from radiomind.policy import require_permission
from radiomind.scheduler import Scheduler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve-rx", action="store_true")
    args = parser.parse_args()
    if not args.approve_rx:
        parser.error("Explicit RX approval required")
    settings = load_settings(Path("config/hackrf-recorder.yaml"))
    for window in settings.windows:
        require_permission(settings, window, "observe")
    reports = []
    source = HackRFSource(
        Path("tools/hackrf/Library/bin/hackrf-0.dll"), history_ms=1000
    )
    try:
        for dwell, period in [(600, 100), (300, 50), (150, 25)]:
            scheduler = Scheduler(
                [w.model_copy(update={"dwell_ms": dwell}) for w in settings.windows]
            )
            visits = []
            current = None
            frames = 0
            started = time.monotonic()
            visit_start = started
            while len(visits) < 21:
                tick = time.monotonic()
                window = scheduler.choose(tick, ready=current is None or frames >= 3)
                if window != current:
                    if visits:
                        visits[-1]["frames"] = frames
                        visits[-1]["duration_ms"] = (tick - visit_start) * 1000
                    if len(visits) == 20:
                        break
                    visit_start = tick
                    source.tune(window)
                    current = window
                    frames = 0
                    detector = Detector()
                    visits.append({"window": window.name, "start_s": tick - started})
                iq = source.read(settings.fft_size * settings.averages)
                if frames == 0:
                    visits[-1]["first_frame_ms"] = (time.monotonic() - tick) * 1000
                signals = detector.update(compute_psd(iq, window, settings.fft_size))
                frames += 1
                visits[-1]["signals"] = len(signals)
                if frames == 3:
                    visits[-1]["third_frame_ms"] = (
                        time.monotonic() - visit_start
                    ) * 1000
                time.sleep(max(0, period / 1000 - (time.monotonic() - tick)))
            reports.append(
                {
                    "dwell_ms": dwell,
                    "period_ms": period,
                    "visits": visits,
                    "elapsed_s": time.monotonic() - started,
                    "sweep_seconds": visits[10]["start_s"],
                    "min_frames": min(v["frames"] for v in visits),
                    "capture": source.metrics(),
                }
            )
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in reports[-1].items()
                        if k not in {"visits", "capture"}
                    }
                ),
                flush=True,
            )
    finally:
        source.close()
        Path("runtime/scan-comparison.json").write_text(
            json.dumps(
                {"audio_saved": False, "iq_saved": False, "reports": reports}, indent=2
            )
        )


if __name__ == "__main__":
    main()
