from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Action = Literal["observe", "demodulate", "record_audio", "record_iq", "transcribe", "export"]
ReceiveGain = Literal["low", "normal", "high"]
RX_GAINS = {"low": (8, 8), "normal": (16, 16), "high": (24, 24)}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Window(StrictModel):
    name: str = Field(min_length=1, max_length=64)
    start_hz: int = Field(ge=1_000_000, le=6_000_000_000)
    end_hz: int = Field(ge=1_000_000, le=6_000_000_000)
    sample_rate_sps: int = Field(default=8_000_000, ge=8_000_000, le=20_000_000)
    dwell_ms: int = Field(default=2000, ge=150, le=60_000)
    allowed_actions: list[Action] = Field(default=["observe"])

    @model_validator(mode="after")
    def check_band(self) -> "Window":
        if self.start_hz >= self.end_hz:
            raise ValueError("start_hz must be smaller than end_hz")
        if self.end_hz - self.start_hz > self.sample_rate_sps:
            raise ValueError("Split wide bands into windows no wider than the sample rate")
        if self.start_hz < self.center_hz - self.sample_rate_sps // 2:
            # Permitted analysis band can be narrower than physical sampling band.
            raise ValueError("Invalid analysis band")
        return self

    @property
    def center_hz(self) -> int:
        return (self.start_hz + self.end_hz) // 2


class AudioSettings(StrictModel):
    enabled: bool = False
    vad_engine: Literal["webrtc", "silero"] = "webrtc"
    pre_roll_ms: int = Field(default=1600, ge=0, le=3000)
    iq_history_ms: int = Field(default=1000, ge=0, le=1000)
    hang_ms: int = Field(default=6000, ge=400, le=15000)
    carrier_grace_ms: int = Field(default=10000, ge=400, le=60000)
    verify_ms: int = Field(default=1800, ge=600, le=4000)
    max_recording_seconds: int = Field(default=180, ge=10, le=600)
    max_archive_mb: int = Field(default=1024, ge=10, le=50000)
    cooldown_seconds: int = Field(default=300, ge=10, le=3600)
    cooldown_failures: int = Field(default=3, ge=1, le=10)
    channel_step_hz: int = Field(default=6250, ge=1000, le=25000)
    priority_frequencies_hz: list[int] = Field(default_factory=list, max_length=64)


class DigitalSettings(StrictModel):
    enabled: bool = False
    executable: Path | None = None
    input_mode: Literal["flat_fm", "iq"] = "flat_fm"
    tetra_enabled: bool = False
    dstar_probe_enabled: bool = False
    p25p2_probe_enabled: bool = False
    dmr_probe_enabled: bool = False
    verify_ms: int = Field(default=7000, ge=2000, le=15000)
    analog_decision_ms: int = Field(default=800, ge=300, le=2000)
    max_buffer_mb: int = Field(default=64, ge=8, le=128)


class ScanRange(StrictModel):
    start_hz: int = Field(ge=1_000_000, le=6_000_000_000)
    end_hz: int = Field(ge=1_000_000, le=6_000_000_000)
    enabled: bool = True

    @model_validator(mode="after")
    def ordered(self) -> "ScanRange":
        if self.end_hz - self.start_hz < 25_000:
            raise ValueError("Диапазон должен быть шириной не менее 0.025 МГц")
        return self


class Settings(StrictModel):
    source: Literal["mock", "hackrf"] = "mock"
    receive_gain: ReceiveGain = "normal"
    device_serial: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    scan_ranges: list[ScanRange] = Field(default_factory=list, max_length=16)
    allow_custom_ranges: bool = False
    rx_only: Literal[True] = True
    mode: Literal["watch", "sweep"] = "sweep"
    country: str | None = None
    legal_basis: str | None = None
    windows: list[Window] = Field(default_factory=list, max_length=1024)
    fft_size: int = Field(default=2048, ge=256, le=16384)
    averages: int = Field(default=8, ge=1, le=32)
    frame_period_ms: int = Field(default=200, ge=100, le=2000)
    scan_period_ms: int | None = Field(default=None, ge=25, le=2000)
    max_metadata_rows: int = Field(default=100_000, ge=100, le=1_000_000)
    metadata_full_policy: Literal["stop", "drop_new"] = "stop"
    audio: AudioSettings = Field(default_factory=AudioSettings)
    digital: DigitalSettings = Field(default_factory=DigitalSettings)

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.digital.dmr_probe_enabled and not self.digital.enabled:
            raise ValueError("DMR probe requires enabled digital reception")
        if self.digital.p25p2_probe_enabled and (
            not self.digital.enabled or self.digital.input_mode != "iq"
        ):
            raise ValueError("P25-II probe requires enabled complex IQ digital reception")
        if self.digital.dstar_probe_enabled and (
            not self.digital.enabled or self.digital.input_mode != "iq"
        ):
            raise ValueError("D-STAR probe requires enabled complex IQ digital reception")
        if self.digital.tetra_enabled and (
            not self.digital.enabled or self.digital.input_mode != "iq"
        ):
            raise ValueError("TETRA requires enabled complex IQ digital reception")
        if self.digital.enabled and not self.audio.enabled:
            raise ValueError("Digital reception requires the authorized audio recording profile")
        if self.fft_size & (self.fft_size - 1):
            raise ValueError("fft_size must be a power of two")
        if len({w.name for w in self.windows}) != len(self.windows):
            raise ValueError("Window names must be unique")
        if self.source == "hackrf" and (
            not self.country or not self.legal_basis or not self.windows
        ):
            raise ValueError("Hardware RX requires country, authorization basis and windows")
        if any(
            set(w.allowed_actions) - {"observe", "demodulate", "record_audio"} for w in self.windows
        ):
            raise ValueError("IQ recording, transcription and export are not implemented")
        if self.audio.enabled:
            if not self.country or not self.legal_basis or not self.windows:
                raise ValueError("Audio requires country, basis and explicit frequency windows")
            if not any(
                {"demodulate", "record_audio"} <= set(w.allowed_actions) for w in self.windows
            ):
                raise ValueError("Audio requires both demodulate and record_audio permissions")
        if self.source == "hackrf" and any(w.sample_rate_sps != 8_000_000 for w in self.windows):
            raise ValueError("This hardware spike supports the validated 8 MS/s configuration only")
        if self.source == "hackrf" and self.fft_size * self.averages > 131_072:
            raise ValueError("FFT batch exceeds the native transfer size")
        if self.mode == "sweep" and any(
            w.dwell_ms < 3 * self.effective_scan_period_ms + 100 for w in self.windows
        ):
            raise ValueError("Dwell must allow settling and at least three detector frames")
        return self

    @property
    def has_enabled_ranges(self) -> bool:
        return not self.scan_ranges or any(r.enabled for r in self.scan_ranges)

    @property
    def effective_scan_period_ms(self) -> int:
        return self.scan_period_ms or self.frame_period_ms

    @property
    def effective_windows(self) -> list[Window]:
        if self.windows or self.source != "mock":
            return self.windows
        return [
            Window(name="DEMO - 2 m", start_hz=144_000_000, end_hz=146_000_000),
            Window(name="DEMO - 70 cm", start_hz=431_000_000, end_hz=439_000_000),
        ]


def load_settings(path: Path) -> Settings:
    return Settings.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
