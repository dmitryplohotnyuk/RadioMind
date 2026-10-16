from pathlib import Path

import pytest
from pydantic import ValidationError

from radiomind.config import Settings, Window, load_settings
from radiomind.policy import require_permission
from radiomind.scheduler import Scheduler


def test_defaults_cannot_authorize_hardware_or_recording() -> None:
    settings = Settings()
    assert settings.windows == [] and settings.source == "mock"
    window = settings.effective_windows[0]
    require_permission(settings, window, "observe")
    for action in ("record_audio", "record_iq", "transcribe", "export", "demodulate"):
        with pytest.raises(PermissionError):
            require_permission(settings, window, action)
    with pytest.raises(ValidationError):
        Settings(source="hackrf")
    with pytest.raises(ValidationError):
        Settings.model_validate({"rx_only": False})
    with pytest.raises(ValidationError):
        Settings.model_validate({"source": "tx"})


def test_hardware_policy_whole_capture_band_and_exact_window() -> None:
    window = Window(name="licensed", start_hz=140_000_000, end_hz=148_000_000)
    settings = Settings(
        source="hackrf", country="UA", legal_basis="owner authorization", windows=[window]
    )
    require_permission(settings, window, "observe")
    with pytest.raises(PermissionError):
        require_permission(settings, window.model_copy(update={"end_hz": 149_000_000}), "observe")
    narrow = Window(name="narrow", start_hz=144_000_000, end_hz=146_000_000)
    narrow_settings = settings.model_copy(update={"windows": [narrow]})
    with pytest.raises(PermissionError):
        require_permission(narrow_settings, narrow, "observe")


def test_watch_sweep_and_coverage_never_invent_observations() -> None:
    windows = Settings().effective_windows
    scheduler = Scheduler(windows)
    assert scheduler.choose(100) == windows[0]
    assert scheduler.coverage(100, None)[1]["seconds_since_last_frame"] is None
    scheduler.observed(windows[0].name, 100)
    assert scheduler.choose(102.1) == windows[1]
    assert scheduler.coverage(103, windows[1].name)[0]["seconds_since_last_frame"] == 3
    scheduler.mode = "watch"
    assert scheduler.choose(1000) == windows[1]


def test_profiles_cover_requested_ranges_without_gaps_or_outside_capture() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = load_settings(root / "backend/tests/fixtures/scanner.yaml")
    for low, high in ((140_000_000, 170_000_000), (420_000_000, 450_000_000)):
        windows = sorted(
            [w for w in settings.windows if low <= w.start_hz < high], key=lambda w: w.start_hz
        )
        end = low
        for window in windows:
            require_permission(settings, window, "observe")
            assert window.start_hz <= end and window.end_hz <= high
            end = max(end, window.end_hz)
        assert end == high


@pytest.mark.parametrize("change", [{"fft_size": 1000}, {"mode": "hybrid"}, {"unknown": True}])
def test_unsupported_config_fails_closed(change: dict) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(change)
