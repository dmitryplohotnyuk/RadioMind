import numpy as np
import pytest

from radiomind.digital_level import DigitalIQEncoder


def decoded(data):
    raw = np.frombuffer(data, dtype=np.uint8).reshape(-1, 32, 2)
    assert np.all(raw == raw[:, :1, :])
    values = (raw[:, 0].astype(float) - 127.5) / 127
    return values[:, 0] + 1j * values[:, 1]


@pytest.mark.parametrize("amplitude", [0.003, 0.03, 0.9])
def test_encoder_preserves_weak_channel_phase_and_rate(amplitude):
    iq = amplitude * np.exp(2j * np.pi * 2700 * np.arange(960) / 48000)
    encoder = DigitalIQEncoder()
    actual = decoded(encoder.encode(iq))
    assert len(actual) == len(iq)
    assert np.sqrt(np.mean(np.abs(actual) ** 2)) == pytest.approx(max(0.25, amplitude), abs=0.006)
    phase_error = np.angle(actual * iq.conj())
    assert np.max(np.abs(phase_error)) < 0.05
    assert encoder.status()["max_block_rms_dbfs"] == pytest.approx(
        20 * np.log10(amplitude), abs=0.01
    )
    if amplitude == 0.003:
        # Fixed-gain conversion used to collapse this entire varying signal.
        old = np.asarray(np.column_stack((iq.real, iq.imag)) * 127 + 127.5, dtype=np.uint8)
        assert np.unique(old).tolist() == [127]
        assert len(np.unique(np.frombuffer(encoder.encode(iq), dtype=np.uint8))) > 30


def test_encoder_bounds_silence_gain_and_sudden_strong_signal():
    encoder = DigitalIQEncoder()
    assert encoder.encode(np.empty(0)) == b"" and encoder.blocks == 0
    assert np.unique(np.frombuffer(encoder.encode(np.zeros(960)), dtype=np.uint8)).tolist() == [127]
    assert encoder.gain is None
    weak = np.full(960, 1e-6 + 1e-6j)
    encoder.encode(weak)
    assert encoder.gain == 256
    strong = np.full(960, 10 + 10j)
    data = np.frombuffer(encoder.encode(strong), dtype=np.uint8)
    assert data.min() > 0 and data.max() < 255
    assert encoder.gain <= 0.1
    before = encoder.gain
    encoder.encode(weak)
    assert before < encoder.gain < 256
    gain = encoder.gain
    encoder.encode(np.zeros(960))
    assert encoder.gain == gain


@pytest.mark.parametrize(
    "iq", [np.array([np.nan]), np.array([np.inf]), np.zeros((2, 2)), np.zeros(48001)]
)
def test_encoder_rejects_invalid_input_without_changing_state(iq):
    encoder = DigitalIQEncoder()
    with pytest.raises(RuntimeError, match="Invalid complex"):
        encoder.encode(iq)
    assert encoder.blocks == 0 and encoder.gain is None


def test_encoder_constant_channel_is_chunk_consistent():
    iq = 0.003 * np.exp(2j * np.pi * 3000 * np.arange(4800) / 48000)
    whole, split = DigitalIQEncoder(), DigitalIQEncoder()
    actual = b"".join(split.encode(iq[start : start + 240]) for start in range(0, len(iq), 240))
    # Quantization near ties can differ by one LSB; phase and samples stay aligned.
    np.testing.assert_allclose(decoded(actual), decoded(whole.encode(iq)), atol=1 / 127)
