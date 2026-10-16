import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from radiomind.channel_rules import ChannelRules
from radiomind.config import Settings, Window
from radiomind.conversation import Conversation
from radiomind.digital import capabilities, decoder_path, verify_decoder
from radiomind.digital_conversation import MultiModeConversation
from radiomind.dsp import Detector, compute_psd, refine_channel
from radiomind.neural_vad import load_session
from radiomind.nfm import Audio
from radiomind.policy import require_audio, require_permission
from radiomind.radio import IQ, MockSource, RxSource
from radiomind.recording import Archive
from radiomind.scheduler import Scheduler
from radiomind.storage import Store

log = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def read_decode(
    source: RxSource, conversation: Conversation, noise_power: float
) -> tuple[IQ, list[tuple[Audio, bool]], float, float]:
    """One executor handoff per transfer; state/storage consumption stays on the loop."""
    started = time.perf_counter()
    iq = source.read_full()
    read_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    frames = conversation.decode(iq, noise_power)
    return iq, frames, read_ms, (time.perf_counter() - started) * 1000


class Engine:
    def __init__(self, settings: Settings, store: Store, dll_path: Path | None = None) -> None:
        self.settings, self.store, self.dll_path = settings, store, dll_path
        self.scheduler = Scheduler(settings.effective_windows, settings.mode)
        self.source: RxSource | None = None
        self.task: asyncio.Task[None] | None = None
        self.stop_requested = False
        self.lock = asyncio.Lock()
        self.frame: dict[str, Any] | None = None
        self.error: str | None = None
        self.running = False
        self.frames = 0
        self.started_at: str | None = None
        self.source_metrics: dict[str, object] = {}
        self.archive = Archive(settings, store)
        self.rules = ChannelRules(settings, store)
        self.conversation: Conversation | None = None
        self.audio_error: str | None = None
        if self.archive.recovery_errors:
            self.error = "Digital archive recovery requires attention: " + "; ".join(
                self.archive.recovery_errors
            )
        self.reconnecting = False
        self.reconnect_attempts = 0
        self.last_rx_error: str | None = None
        self.pending_settings: Settings | None = None
        self.processing: dict[str, dict[str, float]] = {}
        self.capture_queue_peak = 0
        self.deferred_previews = 0
        self.stopped_at: str | None = None

    def measure(self, stage: str, milliseconds: float) -> None:
        metric = self.processing.setdefault(stage, {"count": 0.0, "total_ms": 0.0, "max_ms": 0.0})
        metric["count"] += 1
        metric["total_ms"] += milliseconds
        metric["max_ms"] = max(metric["max_ms"], milliseconds)

    def capture_metrics(self, source: RxSource) -> None:
        self.source_metrics = source.metrics()
        if not self.source_metrics.get("preview_only", True):
            queued = self.source_metrics.get("queued_blocks", 0)
            if isinstance(queued, int):
                self.capture_queue_peak = max(self.capture_queue_peak, queued)

    async def prepare_conversation(
        self, window: Window, frequency: int, snr_db: float, capture_start: datetime | None
    ) -> Conversation:
        arguments = (self.settings, self.archive, window, frequency, snr_db, capture_start)
        if self.settings.digital.enabled:
            # SQLite belongs to the event-loop thread, including read-only lookups.
            # Keep costly DSP/native startup in the worker with a plain-value snapshot.
            mode = self.store.digital_mode(frequency)
            return await asyncio.to_thread(MultiModeConversation, *arguments, mode=mode)
        return await asyncio.to_thread(Conversation, *arguments)

    def preview_due(self, tick: float, last_psd: float, samples: int) -> bool:
        if (
            tick - last_psd < self.settings.frame_period_ms / 1000
            or samples < self.settings.fft_size * self.settings.averages
        ):
            return False
        queued = self.source_metrics.get("queued_blocks", 0)
        if self.conversation is not None and isinstance(queued, int) and queued >= 16:
            # Catch up with accepted audio before spending time on display-only
            # FFT/event work. Never discard continuous input or change its clock.
            self.deferred_previews += 1
            return False
        return True

    def apply_pending_settings(self) -> None:
        if self.pending_settings is None:
            return
        self.settings, self.pending_settings = self.pending_settings, None
        self.scheduler = Scheduler(self.settings.effective_windows, self.settings.mode)
        self.rules.settings = self.archive.settings = self.settings
        self.frame = None

    def queue_settings(self, settings: Settings) -> None:
        self.pending_settings = settings
        if not self.running:
            self.apply_pending_settings()

    async def start(self) -> None:
        async with self.lock:
            if self.running:
                return
            self.apply_pending_settings()
            if self.archive.recovery_errors:
                self.error = "Digital archive recovery requires attention: " + "; ".join(
                    self.archive.recovery_errors
                )
                return
            if not self.settings.has_enabled_ranges:
                return
            for window in self.scheduler.windows:
                require_permission(self.settings, window, "observe")
            self.error, self.stop_requested = None, False
            self.audio_error = None
            self.reconnecting = False
            self.reconnect_attempts = 0
            self.last_rx_error = None
            self.scheduler.since = None
            self.frame = None
            self.source_metrics = {}
            self.processing = {}
            self.capture_queue_peak = 0
            self.deferred_previews = 0
            self.stopped_at = None
            self.running = True
            self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        async with self.lock:
            self.stop_requested = True
            if self.task:
                await self.task
                self.task = None

    async def _run(self) -> None:
        # Bounded retry for native RX transport failure only. Storage/permissions,
        # invalid samples and FIFO overflow must never be retried as USB errors.
        try:
            attempt = 0
            while True:
                if not self.settings.has_enabled_ranges:
                    return
                await self._capture()
                if self.pending_settings is not None and not self.stop_requested and not self.error:
                    self.apply_pending_settings()
                    self.running = True
                    attempt = 0
                    continue
                if (
                    self.stop_requested
                    or self.settings.source != "hackrf"
                    or not self.error
                    or not self.error.startswith(
                        (
                            "HackRF RX timeout",
                            "HackRF open failed",
                            "HackRF start RX failed",
                            "HackRF stop RX failed (libhackrf code -1000)",
                        )
                    )
                    or attempt == 3
                ):
                    return
                self.last_rx_error = self.error
                self.reconnect_attempts = attempt + 1
                self.running = self.reconnecting = True
                await asyncio.sleep(2**attempt)
                if self.stop_requested:
                    return
                self.error = self.audio_error = None
                self.reconnecting = False
                attempt += 1
        finally:
            self.running = self.reconnecting = False

    async def _capture(self) -> None:
        current: Window | None = None
        observation: dict[str, Any] | None = None
        active: dict[int, str] = {}
        detector = Detector()
        last_psd = 0.0
        noise_power = 1e-12
        window_frames = 0
        priorities: list[int] = []
        priority_updated = -1.0
        try:
            if (
                self.settings.digital.enabled
                and not decoder_path(self.settings.digital.executable).is_file()
            ):
                raise RuntimeError("Digital decoder not installed; run scripts/install_digital.py")
            if self.settings.digital.enabled:
                await asyncio.to_thread(
                    verify_decoder, decoder_path(self.settings.digital.executable)
                )
                if self.settings.digital.tetra_enabled:
                    from radiomind.tetra import verify_tetra

                    await asyncio.to_thread(verify_tetra)
            if self.settings.audio.enabled and self.settings.audio.vad_engine == "silero":
                await asyncio.to_thread(load_session)
            if self.settings.source == "mock":
                self.source = MockSource()
            else:
                from radiomind.hackrf import HackRFSource

                if self.dll_path is None:
                    raise RuntimeError("Provide --hackrf-library with a compatible native library")
                self.source = await asyncio.to_thread(
                    HackRFSource,
                    self.dll_path,
                    self.settings.audio.iq_history_ms if self.settings.audio.enabled else 0,
                    self.settings.device_serial,
                    self.settings.receive_gain,
                )
            source = cast(RxSource, self.source)
            self.started_at = utc_now()
            while not self.stop_requested:
                if self.pending_settings is not None and self.conversation is None:
                    break
                tick = time.monotonic()
                if tick - priority_updated >= 1:
                    priorities = self.rules.priorities()
                    self.scheduler.set_priorities(priorities)
                    priority_updated = tick
                completed_conversation = False
                window = (
                    self.conversation.window
                    if self.conversation
                    else self.scheduler.choose(tick, ready=current is None or window_frames >= 3)
                )
                if window != current:
                    if observation:
                        self.store.append("observation", utc_now(), observation)
                        observation = None
                    self.frame = None
                    await asyncio.to_thread(source.tune, window)
                    current, detector, active = window, Detector(), {}
                    window_frames = 0
                if self.conversation:
                    conversation = self.conversation
                    try:
                        block_started = time.perf_counter()
                        iq, frames, read_ms, decode_ms = await asyncio.to_thread(
                            read_decode, source, conversation, noise_power
                        )
                        self.measure("read", read_ms)
                        self.measure("decode", decode_ms)
                        self.measure(
                            "handoff",
                            (time.perf_counter() - block_started) * 1000 - read_ms - decode_ms,
                        )
                        consume_started = time.perf_counter()
                        conversation.consume(
                            frames,
                            retention=conversation.gate.retention,
                            rf_active=conversation.rf_frames,
                        )
                        self.measure("consume", (time.perf_counter() - consume_started) * 1000)
                        if (
                            self.store.channel(conversation.frequency_hz)["manual"]
                            and not conversation.done
                        ):
                            conversation.finish("owner_excluded")
                    except Exception as exc:
                        self.audio_error = str(exc)
                        conversation.finish("capture_or_storage_error", interrupted=True)
                        raise
                    if conversation.done:
                        completed_conversation = True
                        if conversation.end_reason != "owner_excluded":
                            self.rules.outcome(
                                conversation.frequency_hz,
                                conversation.speech_found,
                                protocol=getattr(conversation, "locked_protocol", None),
                            )
                        source.set_continuous(False)
                        self.conversation = None
                        if self.scheduler.mode == "sweep":
                            self.scheduler.since = 0.0
                    self.capture_metrics(source)
                    if not self.preview_due(tick, last_psd, len(iq)):
                        if self.settings.source == "mock":
                            await asyncio.sleep(len(iq) / window.sample_rate_sps)
                        continue
                    iq = iq[-self.settings.fft_size * self.settings.averages :]
                else:
                    iq = await asyncio.to_thread(
                        source.read, self.settings.fft_size * self.settings.averages
                    )
                last_psd = tick
                preview_started = time.perf_counter()
                spectrum = await asyncio.to_thread(compute_psd, iq, window, self.settings.fft_size)
                signals = detector.update(spectrum)
                if self.settings.scan_ranges:
                    signals = [
                        s
                        for s in signals
                        if any(
                            r.enabled and r.start_hz <= s["frequency_hz"] <= r.end_hz
                            for r in self.settings.scan_ranges
                        )
                    ]
                window_frames += 1
                timestamp = utc_now()
                if observation is None:
                    observation = {
                        "window": window.name,
                        "start_utc": timestamp,
                        "source": self.settings.source,
                        "frame_count": 0,
                        "continuous_capture": False,
                    }
                observation["last_frame_utc"] = timestamp
                observation["frame_count"] += 1
                self.scheduler.observed(window.name, time.monotonic())
                new_active: dict[int, str] = {}
                for signal in signals:
                    key = round(
                        signal["frequency_hz"] / (window.sample_rate_sps / self.settings.fft_size)
                    )
                    event_id = active.get(key, str(uuid4()))
                    new_active[key] = event_id
                    if key not in active:
                        self.store.append(
                            "event",
                            timestamp,
                            {
                                "event_id": event_id,
                                "receiver": self.settings.source,
                                "window": window.name,
                                "center_hz": window.center_hz,
                                "sample_rate_sps": window.sample_rate_sps,
                                "signal_class": "unknown",
                                "decode_status": "detected",
                                "recording_path": None,
                                **signal,
                            },
                        )
                active = new_active
                self.frames += 1
                self.capture_metrics(source)
                self.frame = {
                    "sequence": self.frames,
                    "timestamp": timestamp,
                    "source": self.settings.source,
                    "window": window.name,
                    "center_hz": window.center_hz,
                    "sample_rate_sps": window.sample_rate_sps,
                    "start_hz": window.start_hz,
                    "end_hz": window.end_hz,
                    "physical_start_hz": window.center_hz - window.sample_rate_sps / 2,
                    "physical_end_hz": window.center_hz + window.sample_rate_sps / 2,
                    "frequencies_hz": spectrum.frequencies.tolist(),
                    "psd_dbfs_hz": spectrum.power.round(2).tolist(),
                    "noise_floor_dbfs_hz": round(spectrum.noise_floor, 2),
                    "clipped_fraction": spectrum.clipped_fraction,
                    "signals": signals,
                    "analyzed_samples": len(iq),
                    "continuous_capture": False,
                    "dc_removal": "per_fft_block_mean",
                }
                self.measure("preview", (time.perf_counter() - preview_started) * 1000)
                if (
                    self.settings.audio.enabled
                    and self.conversation is None
                    and not completed_conversation
                    and signals
                ):
                    candidates = sorted(
                        signals,
                        key=lambda s: (
                            self.rules.key(s["frequency_hz"]) in priorities,
                            s["snr_db"],
                        ),
                        reverse=True,
                    )
                    fine = await asyncio.to_thread(
                        compute_psd,
                        iq,
                        window,
                        min(8192, self.settings.fft_size * self.settings.averages),
                    )
                    for candidate in candidates:
                        acquisition = refine_channel(
                            fine, candidate, self.settings.audio.channel_step_hz
                        )
                        frequency = int(acquisition["frequency_hz"])
                        if not self.rules.eligible(frequency):
                            continue
                        try:
                            require_audio(self.settings, window, frequency)
                        except PermissionError:
                            continue
                        noise_power = 10 ** (spectrum.noise_floor / 10) * 13000
                        source.set_continuous(True)
                        capture_start = source.metrics().get("capture_start_utc")
                        prepare_started = time.perf_counter()
                        self.conversation = await self.prepare_conversation(
                            window,
                            frequency,
                            candidate["snr_db"],
                            datetime.fromisoformat(capture_start)
                            if isinstance(capture_start, str)
                            else None,
                        )
                        self.measure("prepare", (time.perf_counter() - prepare_started) * 1000)
                        self.capture_metrics(source)
                        self.conversation.acquisition = acquisition
                        break
                if not self.conversation:
                    await asyncio.sleep(
                        max(
                            0,
                            self.settings.effective_scan_period_ms / 1000
                            - (time.monotonic() - tick),
                        )
                    )
        except Exception as exc:
            self.error = str(exc)
            if self.source:
                self.capture_metrics(self.source)
            log.error("RX processing=%s capture=%s", self.processing, self.source_metrics)
            log.exception("Receiver stopped")
        finally:
            self.stopped_at = utc_now()
            self.archive.live_audio.clear()
            try:
                if self.conversation:
                    self.conversation.finish("receiver_stopped", interrupted=bool(self.error))
                    self.conversation = None
            except Exception as exc:
                self.error = self.error or str(exc)
                log.exception("Recording finalization failed")
            try:
                if self.source:
                    await asyncio.to_thread(self.source.close)
                if observation and self.store.count < self.store.max_rows:
                    self.store.append("observation", utc_now(), observation)
            except Exception as exc:
                self.error = self.error or str(exc)
                log.exception("Receiver shutdown failed")
            self.source = None
            self.running = False
            if self.settings.source == "hackrf":
                self.source_metrics["hardware_connected"] = False

    def status(self) -> dict[str, Any]:
        current = self.frame["window"] if self.frame and self.running else None
        return {
            "running": self.running,
            "source": self.settings.source,
            "mode": self.scheduler.mode,
            "settings_pending": self.pending_settings is not None,
            "error": self.error,
            "frames": self.frames,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "processing": {
                "stages": {
                    stage: {
                        "count": int(metric["count"]),
                        "mean_ms": round(metric["total_ms"] / metric["count"], 3),
                        "max_ms": round(metric["max_ms"], 3),
                    }
                    for stage, metric in self.processing.items()
                },
                "capture_queue_peak": self.capture_queue_peak,
                "deferred_previews": self.deferred_previews,
            },
            "record_audio": self.settings.audio.enabled,
            "speech_detector": self.settings.audio.vad_engine,
            "scan_period_ms": self.settings.effective_scan_period_ms,
            "conversation": self.conversation.status() if self.conversation else {"state": "SCAN"},
            "audio_error": self.audio_error,
            "reconnecting": self.reconnecting,
            "reconnect_attempts": self.reconnect_attempts,
            "last_rx_error": self.last_rx_error,
            "archive_bytes": self.archive.used_bytes,
            "archive_limit_bytes": self.settings.audio.max_archive_mb * 1024**2,
            "record_iq": False,
            "digital": {
                "enabled": self.settings.digital.enabled,
                **capabilities(
                    self.settings.digital.executable,
                    self.settings.digital.input_mode,
                    self.settings.digital.tetra_enabled,
                ),
            },
            "metadata_rows": self.store.count,
            "metadata": {
                "limit": self.store.max_rows,
                "full_policy": self.store.metadata_full_policy,
                "skipped_since_start": dict(self.store.metadata_skipped),
                "full": self.store.count >= self.store.max_rows,
            },
            "scan_enabled": self.settings.has_enabled_ranges,
            "coverage": self.scheduler.coverage(time.monotonic(), current)
            if self.settings.has_enabled_ranges
            else [],
            "capture": self.source_metrics,
        }
