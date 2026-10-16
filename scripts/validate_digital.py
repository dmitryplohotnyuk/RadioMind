"""Local, public upstream fixtures. No radio device, no network, no audio upload.

Source fixtures stay under ignored tools/, with upstream provenance/license
notices. This is not a hardware or human intelligibility acceptance test.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from radiomind.digital import DigitalDecoder, decoder_path, verify_decoder

CASES = {
    "dmr_voice": "DMR",
    "nxdn48": "NXDN48",
    "nxdn96": "NXDN96",
    "dstar": "D-STAR",
    "ysf": "YSF",
    "dpmr_synth": "dPMR",
    "m17": "M17",
    "p25p1_c4fm_vc": "P25-I",
    "p25p1_cqpsk_vc": "P25-I",
    "p25p2_cc": "P25-II",
    "noise_floor": "auto",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tools/digital/source/dsd-neo-2.10.0/tests/fixtures/iq"),
    )
    parser.add_argument(
        "--report", type=Path, default=Path("runtime/digital-fixtures.json")
    )
    parser.add_argument("--case", choices=list(CASES))
    parser.add_argument("--complex", action="store_true")
    args = parser.parse_args()
    verify_decoder(decoder_path())
    report = []
    for name, mode in CASES.items():
        if args.case and name != args.case:
            continue
        raw = np.fromfile(args.fixtures / (name + ".iq"), dtype=np.uint8).astype(float)
        raw = (raw - 127.5) / 128
        iq = raw[::2] + 1j * raw[1::2]
        flat = np.angle(iq[1:] * np.conj(iq[:-1]))
        worker = DigitalDecoder(decoder_path(), mode, iq=args.complex)
        stream = iq if args.complex else flat
        feed = worker.feed_iq if args.complex else worker.feed
        packets = []
        started = time.monotonic()
        try:
            # Deliberate real-time pacing: exercises streaming, not only EOF decode.
            for offset in range(0, len(stream), 960):
                feed(stream[offset : offset + 960])
                packets.extend(worker.drain())
                time.sleep(0.02)
            for _ in range(20):
                feed(np.zeros(960))
                packets.extend(worker.drain())
                time.sleep(0.02)
        finally:
            worker.close()
            packets.extend(worker.drain())
        status = worker.status()
        nonzero = sum(
            np.count_nonzero(np.frombuffer(p.pcm, dtype="<i2")) for p in packets
        )
        row = {
            "fixture": name,
            "mode": mode,
            "transport": "iq" if args.complex else "flat_fm",
            **status,
            "packets": len(packets),
            "nonzero_samples": int(nonzero),
            "packet_sizes": sorted({len(p.pcm) for p in packets}),
            "seconds": round(time.monotonic() - started, 3),
            "hardware_test": False,
        }
        report.append(row)
        print(json.dumps(row), flush=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if any(r["error"] for r in report):
        raise SystemExit(1)
    if any(r["fixture"] == "noise_floor" and r["nonzero_samples"] for r in report):
        raise SystemExit("Noise fixture produced audio; investigate before enabling")


if __name__ == "__main__":
    main()
