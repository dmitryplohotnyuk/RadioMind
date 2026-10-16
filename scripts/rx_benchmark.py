"""Bounded receive-only soak. Persists metrics only, never raw IQ or audio."""
import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

from radiomind.config import load_settings
from radiomind.dsp import compute_psd
from radiomind.hackrf import HackRFSource
from radiomind.policy import require_permission
from radiomind.scheduler import Scheduler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=900)
    parser.add_argument("--approve-rx", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("runtime/rx-benchmark.json"))
    args = parser.parse_args()
    if not args.approve_rx or not 1 <= args.seconds <= 3600:
        parser.error("Require --approve-rx and duration between 1 and 3600 seconds")
    settings = load_settings(args.config)
    if settings.source != "hackrf":
        parser.error("Benchmark requires a hardware profile")
    for window in settings.windows:
        require_permission(settings, window, "observe")
    source = HackRFSource(args.library)
    report: dict = {"started_utc": datetime.now(UTC).isoformat(), "info": source.info(),
                    "requested_seconds": args.seconds, "result": "running", "metrics": [],
                    "raw_iq_saved": False, "audio_saved": False, "usb_loss_measurable": False,
                    "retunes": []}
    process = psutil.Process()
    process.cpu_percent()
    scheduler = Scheduler(settings.windows, settings.mode)
    current = None
    started = time.monotonic()
    last_report = started
    frames = 0
    try:
        while time.monotonic() - started < args.seconds:
            tick = time.monotonic()
            window = scheduler.choose(tick)
            retuned = window != current
            if window != current:
                source.tune(window)
                current = window
            iq = source.read(settings.fft_size * settings.averages)
            if retuned:
                report["retunes"].append({"window": window.name,
                    "elapsed_s": time.monotonic()-started,
                    "tune_to_first_block_ms": (time.monotonic()-tick)*1000})
            spectrum = compute_psd(iq, window, settings.fft_size)
            frames += 1
            now = time.monotonic()
            if now - last_report >= 1:
                sample = {"elapsed_s": round(now-started, 2), "window": window.name,
                          "cpu_percent": process.cpu_percent(), "rss_bytes": process.memory_info().rss,
                          "frames": frames, "noise_dbfs_hz": spectrum.noise_floor,
                          "clipped_fraction": spectrum.clipped_fraction, **source.metrics()}
                report["metrics"].append(sample)
                last_report = now
                if len(report["metrics"]) % 30 == 0:
                    print(json.dumps(sample), flush=True)
            time.sleep(max(0, settings.frame_period_ms/1000 - (time.monotonic()-tick)))
        report["result"] = "passed"
    except BaseException as exc:
        report["result"], report["error"] = "failed", repr(exc)
        raise
    finally:
        report["elapsed_s"] = time.monotonic()-started
        report["frames"] = frames
        report["final_capture"] = source.metrics()
        source.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k:v for k,v in report.items() if k not in {"metrics", "retunes"}}), flush=True)


if __name__ == "__main__":
    main()
