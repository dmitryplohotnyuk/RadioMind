"""Bounded RX-only history/DSP benchmark; persists metrics, never RF audio or IQ."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4
from datetime import datetime, UTC

import numpy as np
import psutil

from radiomind.config import load_settings
from radiomind.hackrf import HackRFSource
from radiomind.nfm import NFMDemodulator
from radiomind.pcm import PCM_GAIN, pcm16
from radiomind.policy import require_audio
from radiomind.speech import SpeechGate
from radiomind.squelch import CarrierSquelch
from radiomind.dsp import compute_psd
from radiomind.digital import AudioPacket, DigitalDecoder, decoder_path, verify_decoder
from radiomind.digital_journal import DigitalJournal, publish
from radiomind.digital_timeline import DigitalTimeline
from radiomind.recording import Archive
from radiomind.storage import Store
from radiomind.tetra import DigitalDispatch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--approve-rx", action="store_true")
    parser.add_argument("--frequency-hz", type=int, default=154400000)
    parser.add_argument("--vad", choices=["webrtc", "silero"], default="webrtc")
    parser.add_argument("--squelch", action="store_true")
    parser.add_argument("--digital", action="store_true")
    parser.add_argument(
        "--complex", action="store_true", help="Use configured IQ discovery probes"
    )
    parser.add_argument(
        "--journal-fixture",
        action="store_true",
        help="Checkpoint synthetic PCM during native RX; no RF audio saved",
    )
    parser.add_argument(
        "--config", type=Path, default=Path("config/hackrf-recorder.yaml")
    )
    parser.add_argument(
        "--library", type=Path, default=Path("tools/hackrf/Library/bin/hackrf-0.dll")
    )
    parser.add_argument(
        "--report", type=Path, default=Path("runtime/preservation-rx.json")
    )
    args = parser.parse_args()
    if not args.approve_rx or not 1 <= args.seconds <= 300:
        parser.error("Explicit RX approval and duration 1..300 seconds required")
    settings = load_settings(args.config)
    window = next(
        w
        for w in settings.windows
        if w.start_hz + 6500 < args.frequency_hz < w.end_hz - 6500
    )
    require_audio(settings, window, args.frequency_hz)
    report = {
        "result": "failed",
        "audio_saved": False,
        "iq_saved": False,
        "metrics": [],
    }
    source = None
    digital = None
    digital_packets = 0
    journal = None
    journal_archive = None
    timeline = DigitalTimeline(8 * 1024**2)
    journal_latencies = []
    next_packet = 0
    next_checkpoint = 1.0
    if args.journal_fixture:
        synthetic = settings.model_copy(deep=True)
        synthetic.source = "mock"
        destination = Path("runtime") / ("journal-rx-fixture-" + uuid4().hex)
        journal_archive = Archive(synthetic, Store(destination / "mock.sqlite3", 1000))
        journal = DigitalJournal(
            journal_archive,
            {
                "capture_group": uuid4().hex,
                "source": "mock",
                "window": window.model_dump(),
                "frequency_hz": args.frequency_hz,
                "start_utc": datetime.now(UTC).isoformat(),
                "snr_db": 20,
                "protocol": "DMR",
                "part_samples": 180 * 16000,
            },
        )
        synthetic_pcm = np.tile(np.array([500, -1500], dtype="<i2"), (160, 1)).tobytes()

    started = time.monotonic()
    samples = blocks = queue_peak = old_clips = new_clips = limited = 0
    process = psutil.Process()
    process.cpu_percent()
    try:
        gate = SpeechGate(args.vad)
        if args.digital:
            verify_decoder(decoder_path())
            digital = (
                DigitalDispatch(
                    decoder_path(),
                    "auto",
                    tetra=settings.digital.tetra_enabled,
                    dstar=settings.digital.dstar_probe_enabled,
                    p25p2=settings.digital.p25p2_probe_enabled,
                )
                if args.complex
                else DigitalDecoder(decoder_path())
            )
        source = HackRFSource(args.library, history_ms=1000)
        source.tune(window)
        until = time.monotonic() + 1.2
        while time.monotonic() < until:
            preview = source.read(settings.fft_size * settings.averages)
        noise_power = (
            10 ** (compute_psd(preview, window, settings.fft_size).noise_floor / 10)
            * 13000
        )
        squelch = CarrierSquelch()
        squelch_stats = []
        source.set_continuous(True)
        report["trigger"] = source.metrics()
        decoder = NFMDemodulator(args.frequency_hz - window.center_hz)
        decoder.digital_enabled = args.digital and not args.complex
        decoder.digital_iq_enabled = args.digital and args.complex
        last = time.monotonic()
        while time.monotonic() - started < args.seconds:
            iq = source.read_full()
            audio = decoder.process(iq)
            if digital:
                if args.complex:
                    digital.feed_iq(decoder.digital_iq)
                else:
                    digital.feed(decoder.digital_audio)
                digital_packets += len(digital.drain())
            gate.process(audio)
            if args.squelch:
                squelch_stats.append(
                    (
                        decoder.last_power / noise_power,
                        float(np.mean(decoder.audio_noise)),
                    )
                )
                audio = squelch.process(
                    audio, decoder.audio_power, noise_power, decoder.audio_noise
                )
            pcm = pcm16(audio)
            samples += len(audio)
            blocks += 1
            if journal:
                while next_packet < int(samples / 320):
                    next_packet += 1
                    timeline.append([AudioPacket(next_packet * 0.02, synthetic_pcm)])
                if samples / 16000 >= next_checkpoint:
                    checkpoint_start = time.perf_counter()
                    journal.checkpoint(timeline)
                    journal_latencies.append(
                        (time.perf_counter() - checkpoint_start) * 1000
                    )
                    next_checkpoint = samples / 16000 + 1

            queue_peak = max(queue_peak, source.blocks.qsize())
            old_clips += int(np.count_nonzero(np.abs(audio * 1.5) >= 1))
            new_clips += int(np.count_nonzero(np.abs(pcm.astype(int)) >= 32767))
            limited += int(np.count_nonzero(np.abs(audio * PCM_GAIN) > 0.8))
            now = time.monotonic()
            if now - last >= 1:
                report["metrics"].append(
                    {
                        "elapsed": now - started,
                        "cpu_percent": process.cpu_percent(),
                        "rss_bytes": process.memory_info().rss,
                        "queue": source.blocks.qsize(),
                    }
                )
                last = now
        report["result"] = "passed"
        if args.squelch:
            report["squelch"] = {
                "muted_fraction": squelch.muted_samples / max(1, squelch.samples),
                "rf_ratio_percentiles": np.percentile(
                    np.array(squelch_stats)[:, 0], [10, 50, 90]
                ).tolist(),
                "fm_noise_percentiles": np.percentile(
                    np.array(squelch_stats)[:, 1], [10, 50, 90]
                ).tolist(),
            }
    except Exception as exc:
        report["error"] = repr(exc)
    finally:
        report.update(
            elapsed=time.monotonic() - started,
            blocks=blocks,
            audio_seconds=samples / 16000,
            queue_peak=queue_peak,
            old_gain_saturation_fraction=old_clips / max(samples, 1),
            new_pcm_saturation_fraction=new_clips / max(samples, 1),
            soft_limited_fraction=limited / max(samples, 1),
        )
        if source is not None:
            report["capture"] = source.metrics()
            source.close()
        if digital is not None:
            digital.close()
            report["digital"] = {
                **digital.status(),
                "packets": digital_packets,
                "tail_packets": len(digital.drain()),
            }
            if digital.error:
                report["result"] = "failed"
                report["error"] = digital.error
        if report.get("capture", {}).get("application_dropped_samples", 0):
            report["result"] = "failed"
            report["error"] = report.get("error", "Application dropped IQ samples")
        if journal and journal_archive:
            try:
                journal.checkpoint(
                    timeline, "ready", reason="synthetic_benchmark", interrupted=False
                )
                publish(journal_archive, journal.metadata, timeline)
                journal.discard()
                report["synthetic_journal"] = {
                    "rf_audio": False,
                    "checkpoints": len(journal_latencies),
                    "checkpoint_ms_percentiles": np.percentile(
                        journal_latencies, [50, 95, 100]
                    ).tolist()
                    if journal_latencies
                    else [],
                    "packets": next_packet,
                    "records": len(journal_archive.store.recordings()),
                }
            finally:
                journal.close()
                journal_archive.store.close()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "metrics"}))
    if report["result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
