"""Bounded continuous RX/NFM throughput check, no IQ or audio files."""
import argparse
import json
import time
from pathlib import Path

import psutil

from radiomind.config import load_settings
from radiomind.hackrf import HackRFSource
from radiomind.nfm import NFMDemodulator
from radiomind.policy import require_permission
from radiomind.speech import SpeechGate

p = argparse.ArgumentParser()
p.add_argument('--seconds', type=int, default=45)
p.add_argument('--approve-rx', action='store_true')
a = p.parse_args()
if not a.approve_rx or not 1 <= a.seconds <= 300:
    p.error('Explicit RX approval and bounded duration required')
settings = load_settings(Path('config/hackrf-fast.yaml'))
window = settings.windows[0]
require_permission(settings, window, 'observe')
source = HackRFSource(Path('tools/hackrf/Library/bin/hackrf-0.dll'))
decoder, gate = NFMDemodulator(1_500_000), SpeechGate()
process = psutil.Process()
process.cpu_percent()
report = {'audio_saved': False, 'iq_saved': False, 'result': 'running', 'metrics': []}
started = last = time.monotonic()
blocks = audio_samples = queue_peak = 0
try:
    source.tune(window)
    source.set_continuous(True)
    while time.monotonic() - started < a.seconds:
        iq = source.read_full()
        audio = decoder.process(iq)
        gate.process(audio)
        blocks += 1
        audio_samples += len(audio)
        queue_peak = max(queue_peak, source.blocks.qsize())
        now = time.monotonic()
        if now - last >= 1:
            report['metrics'].append({'elapsed': now-started, 'cpu_percent': process.cpu_percent(), 'rss_bytes': process.memory_info().rss, 'queue': source.blocks.qsize()})
            last = now
    report['result'] = 'passed'
except Exception as exc:
    report['error'] = repr(exc)
    report['result'] = 'failed'
finally:
    report.update(elapsed=time.monotonic()-started, blocks=blocks, audio_seconds=audio_samples/16000, queue_peak=queue_peak, capture=source.metrics())
    source.close()
    Path('runtime/continuous-rx.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != 'metrics'}))
