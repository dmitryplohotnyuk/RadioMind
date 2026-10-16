"""8 MS/s replay wrapper for synthetic or public IQ; never connected to hardware."""

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import psutil
from scipy.io import wavfile

from radiomind.config import load_settings
from radiomind.digital_conversation import MultiModeConversation
from radiomind.recording import Archive
from radiomind.storage import Store


def prepare_replay(output, iq, *, complex_input, offset_hz, noise, amplitude=1.0):
    """Generate bounded synthetic IQ before opening a real-time native input.

    The temporary file is test data only, never a hardware capture. Generation
    (especially Gaussian noise/exponentials at 8 MS/s) must not starve a decoder.
    """
    total = round((len(iq) + 24000) * 8_000_000 / 48000)
    if total * 8 > 768 * 1024**2:
        raise ValueError("Synthetic replay exceeds 768 MiB temporary-file limit")
    flat = np.angle(iq[1:] * np.conj(iq[:-1]))
    flat *= 2800 / max(np.percentile(np.abs(flat), 98), 0.001)
    flat = np.r_[flat, np.zeros(24000)]
    # Preserve the previous discriminator replay length (one differential sample).
    if not complex_input:
        total = round(len(flat) * 8_000_000 / 48000)
    positions = np.arange(len(iq))
    flat_positions = np.arange(len(flat))
    phase = 0.0
    rng = np.random.default_rng(23)
    for pos in range(0, total, 131072):
        size = min(131072, total - pos)
        t = (pos + np.arange(size)) / 8_000_000
        if complex_input:
            base = np.interp(t * 48000, positions, iq, right=0)
            block = base * np.exp(2j * np.pi * (1_000_000 + offset_hz) * t)
        else:
            frequency = (
                np.interp(t * 48000, flat_positions, flat) + 1_000_000 + offset_hz
            )
            angles = phase + np.cumsum(frequency) * (2 * np.pi / 8_000_000)
            phase = angles[-1] % (2 * np.pi)
            block = np.exp(1j * angles)
        block *= amplitude
        if noise:
            block += noise * (rng.normal(size=size) + 1j * rng.normal(size=size))
        output.write(block.astype(np.complex64).tobytes())
    output.seek(0)
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--case", help="Run one named fixture from the cases below")
    parser.add_argument("--amplitude", type=float, default=1.0)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--reference-wav", type=Path, help="External stereo 48 kHz IQ, local only"
    )
    parser.add_argument("--start-seconds", type=float, default=0)
    parser.add_argument("--duration-seconds", type=float, default=10)
    parser.add_argument(
        "--offset-hz", type=float, default=0, help="Synthetic oscillator error"
    )
    parser.add_argument(
        "--noise",
        type=float,
        default=0,
        help="Synthetic Gaussian IQ noise RMS per component",
    )
    parser.add_argument(
        "--complex", action="store_true", help="Preserve original complex phase"
    )
    args = parser.parse_args()
    if not 0 < args.amplitude <= 1:
        parser.error("amplitude must be in (0, 1]")
    if args.start_seconds < 0 or not 0 < args.duration_seconds <= 11:
        parser.error("Reference start must be nonnegative and duration in (0, 11]")
    reference = None
    reference_meta = None
    if args.reference_wav:
        if not args.complex or args.case:
            parser.error("Reference requires --complex and cannot use --case")
        if args.reference_wav.stat().st_size > 50 * 1024**2:
            parser.error("Reference exceeds 50 MiB")
        rate, raw_reference = wavfile.read(args.reference_wav)
        if rate != 48000 or raw_reference.ndim != 2 or raw_reference.shape[1] != 2:
            parser.error("Reference must be stereo 48 kHz IQ")
        first = round(args.start_seconds * rate)
        raw_reference = raw_reference[
            first : first + round(args.duration_seconds * rate)
        ]
        if raw_reference.dtype.kind == "i":
            raw_reference = raw_reference.astype(float) / (
                np.iinfo(raw_reference.dtype).max + 1
            )
        elif raw_reference.dtype.kind != "f":
            parser.error("Reference must be signed integer or float IQ")
        if not len(raw_reference) or not np.isfinite(raw_reference).all():
            parser.error("Empty or nonfinite reference")
        reference = raw_reference[:, 0] + 1j * raw_reference[:, 1]
        reference_meta = {
            "path": str(args.reference_wav),
            "sha256": hashlib.sha256(args.reference_wav.read_bytes()).hexdigest(),
            "start_seconds": args.start_seconds,
            "duration_seconds": len(reference) / rate,
            "synthetic_8msps_wrapper": True,
        }
    fixtures = Path("tools/digital/source/dsd-neo-2.10.0/tests/fixtures/iq")
    settings = load_settings(Path("config/hackrf-recorder.yaml"))
    settings.source = "mock"
    settings.digital.enabled = True
    settings.digital.input_mode = "iq" if args.complex else "flat_fm"
    settings.digital.tetra_enabled = False
    if not args.complex:
        settings.digital.dstar_probe_enabled = False
        settings.digital.p25p2_probe_enabled = False
    report = []
    cases = [("m17", "M17"), ("dmr_voice", "DMR")]
    if args.complex:
        cases += [
            ("p25p1_cqpsk_vc", "P25-I"),
            ("nxdn96", "NXDN96"),
            ("nxdn48", "NXDN48"),
            ("ysf", "YSF"),
            ("dstar", "D-STAR"),
            ("p25p1_c4fm_vc", "P25-I"),
            ("dpmr_synth", "dPMR"),
            ("p25p2_cc", "P25-II"),
            ("noise_floor", "auto"),
        ]
    if reference is not None:
        cases = [("public_dmr_reference", "DMR")]
    for name, mode in cases:
        if args.case and name != args.case:
            continue
        destination = Path("runtime") / ("digital-iq-" + uuid4().hex)
        destination.mkdir()
        store = Store(destination / "mock.sqlite3", 1000)
        if not args.auto:
            store.remember_digital(145000000, mode)
        if reference is not None:
            iq = reference
        else:
            raw = (
                np.fromfile(fixtures / (name + ".iq"), dtype=np.uint8).astype(float)
                - 127.5
            ) / 128
            iq = raw[::2] + 1j * raw[1::2]
        prepared = tempfile.TemporaryFile(dir="runtime")
        conv = None
        try:
            total = prepare_replay(
                prepared,
                iq,
                complex_input=args.complex,
                offset_hz=args.offset_hz,
                noise=args.noise,
                amplitude=args.amplitude,
            )
            conv = MultiModeConversation(
                settings,
                Archive(settings, store),
                settings.windows[0],
                145000000,
                20,
                mode=store.digital_mode(145000000),
            )
            started = time.monotonic()
            max_decoder_rss = max_decoder_workers = 0
            max_gap = 0.0
            previous_feed = started
            fed = 0
            for pos in range(0, total, 131072):
                if pos % (131072 * 50) == 0:
                    workers = getattr(conv.digital, "workers", [conv.digital])
                    rss = active = 0
                    for worker in workers:
                        process = getattr(worker, "process", None)
                        if process and process.poll() is None:
                            try:
                                rss += psutil.Process(process.pid).memory_info().rss
                                active += 1
                            except psutil.NoSuchProcess:
                                pass
                    max_decoder_rss = max(max_decoder_rss, rss)
                    max_decoder_workers = max(max_decoder_workers, active)
                size = min(131072, total - pos)
                block = np.fromfile(prepared, dtype=np.complex64, count=size)
                if len(block) != size:
                    raise RuntimeError("Incomplete synthetic input")
                frames = conv.decode(block, 1e-8)
                now = time.monotonic()
                max_gap = max(max_gap, now - previous_feed)
                previous_feed = now
                fed += size
                conv.consume(
                    frames, retention=conv.gate.retention, rf_active=conv.rf_frames
                )
                if conv.done:
                    break
                wait = (pos + size) / 8_000_000 - (time.monotonic() - started)
                if wait > 0:
                    time.sleep(wait)
            feed_seconds = time.monotonic() - started
            conv.finish("fixture_end")
            records = store.recordings()
            row = {
                "fixture": name,
                "preset": "auto" if args.auto else mode,
                "choice": conv.choice,
                "decoder": conv.digital_metadata,
                "records": [
                    {
                        key: record.get(key)
                        for key in [
                            "protocol",
                            "digital_slot",
                            "duration_seconds",
                            "playable",
                        ]
                    }
                    for record in records
                ],
                "hardware_test": False,
                "external_reference": reference_meta,
                "offset_hz": args.offset_hz,
                "noise_rms": args.noise,
                "amplitude": args.amplitude,
                "feed_realtime_ratio": round(fed / 8_000_000 / feed_seconds, 3),
                "max_feed_gap_ms": round(max_gap * 1000, 2),
                "sampled_max_decoder_rss_mb": round(max_decoder_rss / 1024**2, 2),
                "sampled_max_decoder_workers": max_decoder_workers,
                "expected_protocol": mode,
                # The two-second upstream DMR snippet yields vocoder PCM but
                # lacks repeated call-address evidence. Under ADR 0042 it must
                # remain private. Public DMR references test accepted voice.
                "expect_audio": name not in {"p25p2_cc", "noise_floor", "dmr_voice"},
                "expectation_note": "DMR fixture lacks repeated call confirmation"
                if name == "dmr_voice"
                else None,
                "attempts": store.digital_attempts(),
            }
            report.append(row)
            print(json.dumps(row), flush=True)
        except RuntimeError as exc:
            # Preserve failures and continue the matrix; never leave an old
            # successful report looking like the result of a failed replay.
            workers = getattr(conv.digital, "workers", [conv.digital]) if conv else []
            row = {
                "fixture": name,
                "choice": None,
                "records": [],
                "expected_protocol": mode,
                "expect_audio": name not in {"p25p2_cc", "noise_floor"},
                "hardware_test": False,
                "external_reference": reference_meta,
                "offset_hz": args.offset_hz,
                "noise_rms": args.noise,
                "amplitude": args.amplitude,
                "error": str(exc),
                "workers": [
                    {
                        "status": worker.status(),
                        "exit_code": worker.process.poll() if worker.process else None,
                    }
                    for worker in workers
                ],
            }
            report.append(row)
            print(json.dumps(row), flush=True)
        finally:
            if conv:
                conv.digital.close()
            prepared.close()
            store.close()
    report_path = args.report or Path("runtime") / (
        ("digital-complex-" if args.complex else "digital-iq-")
        + ("auto.json" if args.auto else "known.json")
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if (
        not report
        or any(row.get("error") for row in report)
        or any(row.get("decoder", {}).get("error") for row in report)
        or any(
            (
                row["choice"] != "digital"
                or not row["records"]
                or any(
                    r["protocol"] != row["expected_protocol"] for r in row["records"]
                )
            )
            if row["expect_audio"]
            else (
                bool(row["records"])
                or (
                    row["fixture"] == "p25p2_cc"
                    and not any(
                        "P25-II" in attempt.get("sync_candidates", [])
                        and attempt["sync_counts"].get("P25-II", 0) >= 2
                        and attempt["outcome"] == "sync_without_audio"
                        for attempt in row["attempts"]
                    )
                )
            )
            for row in report
        )
    ):
        raise SystemExit("Digital replay failed; see report")


if __name__ == "__main__":
    main()
