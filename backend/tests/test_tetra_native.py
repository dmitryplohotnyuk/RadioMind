"""Offline generated receive vectors only. No radio device or transmission."""

import ctypes
import json
import os
import subprocess

import numpy as np
import pytest
from test_complex_digital import modulate_tetra

from radiomind.digital import ROOT
from radiomind.tetra import TetraDecoder, tetra_path, verify_tetra
from radiomind.tetra_dsp import TetraDemodulator


def bsch_vector():
    info = [0] * 60
    for pos, width, value in [
        (4, 6, 7),
        (10, 2, 0),
        (12, 5, 18),
        (17, 6, 2),
        (31, 10, 255),
        (41, 14, 1234),
    ]:
        info[pos : pos + width] = [int(b) for b in f"{value:0{width}b}"]
    crc = 0xFFFF
    for bit in info:
        top = (crc >> 15) ^ bit
        crc = ((crc << 1) & 0xFFFF) ^ (0x1021 if top else 0)
    info += [int(b) for b in f"{crc ^ 0xFFFF:016b}"]
    coded, state = [], 0
    for bit in info + [0] * 4:
        state = ((state << 1) | bit) & 31
        coded.extend((state & poly).bit_count() % 2 for poly in [19, 29, 23, 27])
    punctured = [coded[8 * (j // 3) + [0, 1, 4][j % 3]] for j in range(120)]
    interleaved = [0] * 120
    for j, bit in enumerate(punctured):
        interleaved[(11 * (j + 1)) % 120] = bit
    lfsr = 3
    for j in range(120):
        bit = 0
        for tap in [32, 26, 23, 22, 16, 12, 11, 10, 8, 7, 5, 4, 2, 1]:
            bit ^= lfsr >> (32 - tap)
        bit &= 1
        lfsr = (lfsr >> 1) | (bit << 31)
        interleaved[j] ^= bit
    burst = [0] * 510
    burst[:12] = map(int, "000110101101")
    burst[500:] = map(int, "1011011100")
    burst[214:252] = map(int, "11000001100111001110100111000001100111")
    burst[94:214] = interleaved
    return np.tile(np.asarray(burst, dtype=np.uint8), 200)


def native(bits):
    if not tetra_path().is_file():
        pytest.skip("Optional native TETRA worker not installed")
    verify_tetra()
    result = subprocess.run(
        [str(tetra_path())], input=bits, capture_output=True, cwd=tetra_path().parent, timeout=15
    )
    assert result.returncode == 0, result.stderr[-1000:]
    return [json.loads(line) for line in result.stdout.splitlines()]


def test_native_tetra_bsch_from_complex_phase_and_noise_rejection():
    vector = bsch_vector()
    for frequency in [0, 500]:
        samples = modulate_tetra(vector, frequency)
        demod = TetraDemodulator()
        bits = b"".join(demod.process(samples[i : i + 960]) for i in range(0, len(samples), 960))
        events = native(bits)
        syncs = [e for e in events if e["type"] == "sync"]
        assert len(syncs) > 150
        assert all(e["mcc"] == 255 and e["mnc"] == 1234 and e["color"] == 7 for e in syncs)
        assert not [e for e in events if e["type"] == "audio"]
    noise = np.random.default_rng(8).integers(0, 2, len(vector), dtype=np.uint8)
    assert native(noise.tobytes()) == []


def test_native_receive_codec_fixture_and_bad_frame_header():
    if not tetra_path().is_file():
        pytest.skip("Optional native TETRA worker not installed")
    suffix = ".dll" if os.name == "nt" else ".so"
    decoder = ctypes.CDLL(str(tetra_path().parent / ("codec-1" + suffix)))
    pointer = ctypes.POINTER(ctypes.c_int16)
    decoder.rm_decode.argtypes = [pointer, pointer]
    decoder.rm_decode.restype = ctypes.c_int
    source = (
        ROOT
        / "tools/digital/source/tetra-kit-timeslots-2205072976e18b6fb15b975e734afad2477863ac"
        / "recorder-js/silence.acelp"
    )
    frames = np.frombuffer(source.read_bytes(), dtype="<i2").reshape(-1, 690)
    output = np.zeros(480, dtype="<i2")
    decoder.rm_reset()
    accepted = 0
    for frame in frames:
        accepted += (
            decoder.rm_decode(frame.ctypes.data_as(pointer), output.ctypes.data_as(pointer)) == 0
        )
    assert accepted > 0  # Codec framing only: this silence file is not spoken-voice evidence.
    bad = np.zeros(690, dtype="<i2")
    assert decoder.rm_decode(bad.ctypes.data_as(pointer), output.ctypes.data_as(pointer)) < 0


def test_tetra_worker_streaming_and_cleanup():
    import time

    if not tetra_path().is_file():
        pytest.skip("Optional native TETRA worker not installed")
    worker = TetraDecoder()
    samples = modulate_tetra(bsch_vector()[: 510 * 40])
    try:
        for at in range(0, len(samples), 960):
            worker.feed_iq(samples[at : at + 960])
            time.sleep(0.002)
    finally:
        worker.close()
    assert worker.error is None and worker.status()["protocol"] == "TETRA"
    assert not worker.drain()
    assert worker.process.poll() == 0
    assert all(not t.is_alive() for t in worker.threads)
