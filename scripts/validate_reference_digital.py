"""Replay a public WAV locally through the production decoder, without hardware.

IQ must be stereo 48 kHz (I, Q). Flat input is discriminator audio, not speech.
This tests the decoder adapter, not scanner acquisition or subjective quality.
Source media and output stay outside the user archive. No download or RF access.
"""

import argparse
import hashlib
import json
import time
from collections import deque
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from radiomind.digital import ANSI, MODES, DigitalDecoder, decoder_path, verify_decoder
from radiomind.tetra import DigitalDispatch


class ReferenceDecoder(DigitalDecoder):
    """Bounded diagnostic logs from public references only, never live captures."""

    def __init__(self, *args, **kwargs):
        self.reference_log = deque(maxlen=4000)
        super().__init__(*args, **kwargs)

    def _logs(self):
        assert self.process and self.process.stderr
        while not self.stopping.is_set():
            line = self.process.stderr.readline(8192)
            if not line:
                return
            with self.lock:
                text = ANSI.sub("", line.decode("utf8", errors="replace").strip())
                self.reference_log.append(text)
                if "rtl_tcp:" in text:
                    self.log_tail.append(text[text.index("rtl_tcp:") :][:512])
                self.evidence.observe(text, self.input_samples / 48000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--kind", choices=["iq", "flat"], required=True)
    parser.add_argument("--mode", choices=list(MODES), default="auto")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dmr-probe", action="store_true")
    args = parser.parse_args()
    if args.input.stat().st_size > 50 * 1024**2:
        parser.error("Reference WAV exceeds 50 MiB")
    rate, samples = wavfile.read(args.input)
    if rate != 48000 or not 0 < len(samples) <= rate * 120:
        parser.error("Use a 48 kHz reference up to 120 seconds")
    if samples.dtype.kind == "i":
        samples = samples.astype(np.float32) / (np.iinfo(samples.dtype).max + 1)
    elif samples.dtype.kind != "f":
        parser.error("Use signed integer or float WAV")
    if not np.isfinite(samples).all():
        parser.error("Nonfinite reference samples")
    if args.kind == "iq":
        if samples.ndim != 2 or samples.shape[1] != 2:
            parser.error("IQ reference must contain I and Q channels")
        signal = samples[:, 0] + 1j * samples[:, 1]
    else:
        if samples.ndim == 2 and samples.shape[1] == 1:
            samples = samples[:, 0]
        if samples.ndim != 1:
            parser.error("Flat discriminator reference must be mono")
        # feed() accepts deviation units and multiplies by 6000. Public PCM
        # already has an arbitrary recording level: retain its original scale.
        signal = samples * (32768.0 / 6000.0)
    verify_decoder(decoder_path())
    decoder = (
        DigitalDispatch(
            decoder_path(), args.mode, tetra=False, dmr=True, iq=args.kind == "iq"
        )
        if args.dmr_probe
        else ReferenceDecoder(decoder_path(), args.mode, iq=args.kind == "iq")
    )
    packets = []
    error = None
    max_gap = 0.0
    started = previous = time.monotonic()
    try:
        # Include a short zero tail to drain buffering; no transmitted signal.
        signal = np.pad(signal, (0, rate // 2))
        for pos in range(0, len(signal), 960):
            block = signal[pos : pos + 960]
            now = time.monotonic()
            max_gap = max(max_gap, now - previous)
            previous = now
            if args.kind == "iq":
                decoder.feed_iq(block)
            else:
                decoder.feed(block)
            packets.extend(decoder.drain())
            delay = (pos + len(block)) / rate - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)
    except RuntimeError as exc:
        error = str(exc)
    finally:
        decoder.close()
        packets.extend(decoder.drain())
    status = decoder.status()
    args.report.with_suffix(".decoder.log").write_text(
        "\n".join(getattr(decoder, "reference_log", [])), encoding="utf8"
    )
    channels = 2 if any(len(p.pcm) == 640 for p in packets) else 1
    chunks = []
    for packet in packets:
        x = np.frombuffer(packet.pcm, dtype="<i2").reshape(160, -1)
        chunks.append(np.repeat(x, channels, axis=1) if x.shape[1] < channels else x)
    pcm = np.concatenate(chunks) if chunks else np.empty((0, channels), np.int16)
    # Save only an explicitly labelled local candidate, never archive acceptance.
    candidate = None
    if len(pcm) and not status["encrypted"] and not status["error"] and not error:
        candidate = args.report.with_suffix(".candidate.wav")
        wavfile.write(candidate, 8000, pcm)
    report = {
        "source_file": str(args.input),
        "sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "kind": args.kind,
        "mode": args.mode,
        "dmr_probe": args.dmr_probe,
        "source_seconds": len(samples) / rate,
        "hardware_test": False,
        "scanner_pipeline_test": False,
        "intelligibility_validated": False,
        "status": status,
        "error": error,
        "max_feed_gap_ms": round(max_gap * 1000, 2),
        "pcm_packets": len(packets),
        "first_pcm_input_seconds": packets[0].input_seconds if packets else None,
        "pcm_seconds": len(pcm) / 8000,
        "pcm_nonzero_fraction": float(np.count_nonzero(pcm) / pcm.size)
        if pcm.size
        else 0,
        "candidate": str(candidate) if candidate else None,
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report, indent=2), flush=True)
    if error or status["error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
