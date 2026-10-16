import ctypes as ct
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_hackrf_boundary import fake_source
from test_scan_archive import audio_settings, require_native

from radiomind.api import create_app
from radiomind.cleaning import adaptive_mix
from radiomind.config import RX_GAINS, Settings, Window
from radiomind.receiver_settings import ReceiverPreferences, apply_preferences
from radiomind.recording import RecordingWriter


def test_adaptive_mix_keeps_detail_bounds_and_existing_squelch_pauses():
    rng = np.random.default_rng(42)
    original = rng.normal(0, 1000, 16000).astype(np.float32)
    np.testing.assert_array_equal(adaptive_mix(original, original), original)
    suppressed = adaptive_mix(original, np.zeros_like(original))
    # Neural rejection must not turn an otherwise audible recording into silence.
    assert np.std(suppressed) / np.std(original) > 0.9
    original[4000:8000] = 0
    wet = original.copy()
    wet[4000:8000] = 50  # Filter tail must not reintroduce sound into muted pauses.
    result = adaptive_mix(original, wet)
    assert not np.any(result[4000:8000])
    assert len(result) == len(original)
    assert np.isfinite(result).all()
    assert adaptive_mix(np.zeros(0), np.zeros(0)).size == 0


def test_rejected_quiet_speech_with_surviving_click_stays_audible():
    t = np.arange(32000, dtype=np.float32) / 16000
    original = (1200 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    original[12000:16000] = 0
    original[100] = 30000  # Peak normalization alone cannot repair this failure.
    wet = original * 0.005
    wet[100] = original[100]
    result = adaptive_mix(original, wet)
    region = slice(18000, 28000)
    assert 20 * np.log10(np.std(result[region]) / np.std(original[region])) > -4
    assert np.max(np.abs(result)) <= 32001
    assert not np.any(result[12000:16000])
    assert len(result) == len(original)


@pytest.mark.parametrize("length", [1, 17, 319, 16000])
def test_silent_and_short_cleanup_remains_finite(length):
    zeros = np.zeros(length, dtype=np.float32)
    np.testing.assert_array_equal(adaptive_mix(zeros, zeros), zeros)


def test_long_squelch_pause_does_not_hide_rejected_short_transmission():
    original = np.zeros(320000, dtype=np.float32)
    original[8000:16000] = 1000 * np.sin(np.arange(8000) * 0.2)
    result = adaptive_mix(original, np.zeros_like(original))
    assert np.std(result[8000:16000]) / np.std(original[8000:16000]) > 0.9
    assert not np.any(result[16000:])


def test_adc_reports_both_components_and_signed_rails_without_changing_iq():
    source = fake_source()
    raw = np.tile(np.array([0, -128], dtype=np.int8), 131072)
    source.blocks.put(raw.tobytes())
    iq = source.read_full() if source.continuous else source.read(100)
    np.testing.assert_array_equal(iq, -1j)
    assert source.adc["peak_dbfs"] == 0
    assert source.adc["sampled_rail_fraction"] == 0.5
    assert source.adc["sampled_components"] == 8192
    assert source.adc["rms_dbfs"] == pytest.approx(-3.0103, abs=0.001)


@pytest.mark.parametrize("preset", ["low", "normal", "high"])
def test_gain_presets_use_exact_native_steps_with_amp_and_bias_off(preset):
    source = fake_source()
    source.device = ct.c_void_p(1)
    source.streaming = False
    source.lna_gain, source.vga_gain = RX_GAINS[preset]
    source.callback = None
    calls = []

    def native(name):
        def call(*args):
            calls.append((name, args[-1]))
            return 0

        return call

    names = [
        "amp_enable",
        "antenna_enable",
        "sample_rate",
        "baseband_filter_bandwidth",
        "lna_gain",
        "vga_gain",
        "freq",
    ]
    source.lib = SimpleNamespace(
        **{f"hackrf_set_{name}": native(name) for name in names}, hackrf_start_rx=native("start")
    )
    source.tune(Window(name="test", start_hz=144000000, end_hz=146000000))
    values = dict(calls)
    assert values["lna_gain"] == RX_GAINS[preset][0]
    assert values["vga_gain"] == RX_GAINS[preset][1]
    assert values["amp_enable"] == values["antenna_enable"] == 0
    assert values["sample_rate"] == 8000000
    assert source.adc == {}


def test_gain_api_persistence_validation_and_legacy_clients(tmp_path):
    base = Settings()
    payload = {"ranges": [{"start_hz": 144000000, "end_hz": 146000000}], "receive_gain": "high"}
    with TestClient(create_app(base, tmp_path, autostart=False)) as client:
        assert client.post("/api/settings", json=payload).json()["active"]["receive_gain"] == "high"
        assert (
            client.post("/api/settings", json={**payload, "receive_gain": "maximum"}).status_code
            == 422
        )
        payload.pop("receive_gain")
        assert client.post("/api/settings", json=payload).json()["active"]["receive_gain"] == "high"
    with TestClient(create_app(base, tmp_path, autostart=False)) as client:
        assert client.get("/api/settings").json()["desired"]["receive_gain"] == "high"
    assert (
        apply_preferences(base, ReceiverPreferences.model_validate(payload)).receive_gain
        == "normal"
    )


@pytest.mark.parametrize("legacy", ["v1", "v2"])
def test_legacy_cleaned_copy_is_retained_and_new_copy_is_published(tmp_path, legacy):
    require_native()
    settings = audio_settings()
    app = create_app(settings, tmp_path, autostart=False)
    with TestClient(app) as client:
        archive = app.state.engine.archive
        writer = RecordingWriter(archive, settings.windows[0], 145000000, np.zeros(1600), 20)
        writer.finish("test")
        sid = writer.recording_id
        original = archive.path(sid).read_bytes()
        old = archive.path(sid).with_suffix(f".clean-{legacy}.wav")
        old.write_bytes(original)
        archive.used_bytes += len(original)
        url = f"/api/conversations/{sid}"
        assert app.state.cleaner.status(sid) == "outdated"
        assert client.get(url + "/audio?variant=cleaned").content == original
        assert client.post(url + "/clean").json()["status"] == "processing"
        client.portal.call(app.state.cleaner.close)
        assert app.state.cleaner.status(sid) == "ready"
        assert old.read_bytes() == archive.path(sid).read_bytes() == original
        assert app.state.cleaner.path(sid).name.endswith(".clean-v3.wav")
        assert client.get(url + "/audio?variant=cleaned").status_code == 200
