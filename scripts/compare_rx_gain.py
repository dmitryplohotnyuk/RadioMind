"""Short receive-only gain comparison; scalar metrics, never writes IQ/audio."""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from scipy import signal

from radiomind.config import RX_GAINS, load_settings
from radiomind.hackrf import HackRFSource
from radiomind.policy import require_permission


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve-rx", action="store_true", required=True)
    parser.add_argument("--library", type=Path, required=True)
    args = parser.parse_args()
    settings = load_settings(Path("config/hackrf-recorder.yaml"))
    windows = [
        w for w in settings.windows if w.start_hz in (152000000, 420000000, 438000000)
    ]
    report = {
        "kind": "physical RX gain comparison; changing live signals are not a controlled SNR reference",
        "runs": [],
    }
    source = HackRFSource(args.library)
    try:
        for window in windows:
            require_permission(settings, window, "observe")
            for preset in ("normal", "high", "normal", "low"):
                source.lna_gain, source.vga_gain = RX_GAINS[preset]
                source.tune(window)
                levels, rails, peaks, spectra = [], [], [], []
                start = time.monotonic()
                while time.monotonic() - start < 1.0:
                    iq = source.read(131072)
                    levels.append(source.adc["rms_dbfs"])
                    rails.append(source.adc["sampled_rail_fraction"])
                    peaks.append(source.adc["peak_dbfs"])
                    _, p = signal.welch(
                        iq, fs=8000000, nperseg=16384, return_onesided=False
                    )
                    spectra.append(np.fft.fftshift(p))
                power = 10 * np.log10(np.maximum(np.median(spectra, axis=0), 1e-20))
                # Remove DC and window edges; relative contrast, not calibrated dBm.
                valid = (
                    np.abs(np.fft.fftshift(np.fft.fftfreq(len(power), 1 / 8000000)))
                    > 50000
                )
                valid &= (
                    np.abs(np.fft.fftshift(np.fft.fftfreq(len(power), 1 / 8000000)))
                    < 3000000
                )
                floor = np.percentile(power[valid], 30)
                row = dict(
                    window=window.name,
                    preset=preset,
                    blocks=len(levels),
                    rms_dbfs=float(np.median(levels)),
                    peak_dbfs=float(max(peaks)),
                    max_sampled_rail_fraction=float(max(rails)),
                    noise_floor_dbfs_hz=float(floor),
                    strongest_contrast_db=float(np.max(power[valid]) - floor),
                )
                report["runs"].append(row)
                print(json.dumps(row), flush=True)
    finally:
        try:
            source.close()
        finally:
            Path("runtime/rx-gain-comparison.json").write_text(
                json.dumps(report, indent=2)
            )


if __name__ == "__main__":
    main()
