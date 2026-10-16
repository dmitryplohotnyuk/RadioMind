from pathlib import Path

import numpy as np
from test_audio import audio_settings

from radiomind.conversation import Conversation
from radiomind.nfm import NFMDemodulator
from radiomind.recording import Archive
from radiomind.squelch import CarrierSquelch
from radiomind.storage import Store


def test_hysteresis_ramps_quiet_speech_and_chunk_invariance() -> None:
    audio = np.ones(16000) * 0.0001  # Quiet audio must not close the squelch.
    power = np.r_[np.ones(4000) * 5, np.ones(2000) * 2, np.ones(4000), np.ones(6000) * 5]
    whole = CarrierSquelch().process(audio, power, 1)
    gate = CarrierSquelch()
    split = np.concatenate(
        [gate.process(audio[i : i + 263], power[i : i + 263], 1) for i in range(0, len(audio), 263)]
    )
    np.testing.assert_allclose(split, whole, atol=1e-18)
    np.testing.assert_array_equal(whole[32:6000], audio[32:6000])
    assert np.max(np.abs(whole[6080:10000])) == 0
    np.testing.assert_array_equal(whole[10032:], audio[10032:])
    assert len(whole) == len(audio)
    # Strong colored RF noise also closes when discriminator hiss persists.
    gate = CarrierSquelch()
    out = gate.process(np.ones(3200), np.ones(3200) * 100, 1, np.ones(3200) * 4)
    assert not np.any(out)


def test_synthetic_ptt_gap_is_silent_and_reply_keeps_same_session(tmp_path: Path) -> None:
    settings = audio_settings()
    settings.audio.hang_ms = 6000
    store = Store(tmp_path / "ptt.sqlite3", 1000)
    conv = Conversation(settings, Archive(settings, store), settings.windows[0], 145000000, 20)
    # Synthetic 8 MS/s narrow FM, two 250 ms transmissions with a 250 ms RF-off gap.
    rng = np.random.default_rng(42)
    position = 0
    total = 6_000_000
    noise_power = 2 * 0.02**2 / 8_000_000 * 13000
    captured = []
    while position < total:
        count = min(131072, total - position)
        t = (position + np.arange(count)) / 8_000_000
        on = (t < 0.25) | (t >= 0.5)
        # Offset 1 MHz from test window LO; constant phase FM avoids boundary resets.
        phase = 2 * np.pi * 1_000_000 * t - (2500 * 0.3 / 1000) * np.cos(2 * np.pi * 1000 * t)
        iq = np.asarray(
            0.02 * on * np.exp(1j * phase)
            + rng.normal(0, 0.02, count)
            + 1j * rng.normal(0, 0.02, count),
            dtype=np.complex64,
        )
        frames = conv.decode(iq, noise_power)
        for frame, _ in frames:
            captured.append(frame)
            now = len(captured) * 0.02
            voice = 0.08 < now < 0.24 or 0.54 < now < 0.74
            conv.consume([(frame, voice)], rf_active=[voice])
        position += count
    out = np.concatenate(captured)
    assert len(out) + len(conv.audio_pending) == 12000
    assert len(conv.audio_pending) == len(conv.gate.pending)
    assert np.max(np.abs(out[4800:7360])) == 0  # Settled interior of PTT-off gap.
    assert np.std(out[8800:11000]) > 0.1  # Reply restored, including quiet syllables.
    assert not conv.done and conv.speech_found
    session = conv.session_id
    conv.finish("test")
    assert len(store.conversations()) == 1 and store.conversations()[0]["id"] == session
    store.close()


def test_weak_fm_stays_open_without_using_audio_loudness() -> None:
    rng = np.random.default_rng(91)
    decoder = NFMDemodulator(125000)
    gate = CarrierSquelch()
    n = 800000
    t = np.arange(n) / 8e6
    # ~6.8 dB carrier/noise in channel, very quiet modulation.
    iq = np.asarray(
        0.0025
        * np.exp(2j * np.pi * 125000 * t - 1j * (2500 * 0.03 / 1000) * np.cos(2 * np.pi * 1000 * t))
        + rng.normal(0, 0.02, n)
        + 1j * rng.normal(0, 0.02, n),
        dtype=np.complex64,
    )
    audio = decoder.process(iq)
    out = gate.process(audio, decoder.audio_power, 0.0008 / 8e6 * 13000, decoder.audio_noise)
    np.testing.assert_allclose(out[400:], audio[400:], atol=0)
