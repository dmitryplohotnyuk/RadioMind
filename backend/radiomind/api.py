import asyncio
import struct
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import psutil
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from radiomind.cleaning import Cleaner
from radiomind.config import Settings
from radiomind.deletion import ArchiveDeletion
from radiomind.engine import Engine
from radiomind.live_audio import monitor_socket
from radiomind.receiver_settings import (
    ReceiverPreferences,
    apply_preferences,
    preferences_for,
    ranges_for,
)
from radiomind.storage import Store

ROOT = Path(__file__).resolve().parents[2]


class Control(BaseModel):
    action: Literal["start", "stop", "watch", "sweep"]


class ChannelChange(BaseModel):
    frequency_hz: int = Field(ge=1_000_000, le=6_000_000_000)
    action: Literal["exclude", "restore", "priority", "normal"]


class RecordingReview(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    label: Literal["speech", "noise", "unreviewed"] | None = None
    favorite: bool | None = None
    listened: bool | None = None


class DeleteSelection(BaseModel):
    session_id: str | None = Field(default=None, max_length=32)
    frequency_hz: int | None = Field(default=None, ge=1_000_000, le=6_000_000_000)

    @model_validator(mode="after")
    def one_scope(self) -> "DeleteSelection":
        if (self.session_id is None) == (self.frequency_hz is None):
            raise ValueError("Select one conversation or frequency")
        return self


class DeleteConfirmation(BaseModel):
    token: str = Field(min_length=32, max_length=32)


class FrequencyProfile(BaseModel):
    frequency_hz: int = Field(ge=1_000_000, le=6_000_000_000)
    title: str | None = Field(default=None, max_length=100)
    favorite: bool | None = None


def create_app(
    settings: Settings,
    data_dir: Path,
    library: Path | None = None,
    autostart: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = Store(
            data_dir / f"{settings.source}.sqlite3",
            settings.max_metadata_rows,
            settings.metadata_full_policy,
        )
        saved = store.preference("receiver")
        effective = (
            apply_preferences(settings, ReceiverPreferences.model_validate(saved))
            if saved
            else settings
        )
        engine = Engine(effective, store, library)
        engine.rules.authorized_windows = settings.effective_windows
        app.state.engine, app.state.store = engine, store
        app.state.cleaner = Cleaner(engine.archive)
        app.state.deletion = ArchiveDeletion(engine, app.state.cleaner)
        app.state.process = psutil.Process()
        app.state.process.cpu_percent()
        try:
            if autostart:
                await engine.start()
            yield
        finally:
            await engine.stop()
            await app.state.cleaner.close()
            store.close()

    app = FastAPI(
        title="RadioMind", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.get("/api/settings")
    async def receiver_settings() -> dict[str, object]:
        engine = app.state.engine
        return {
            "desired": preferences_for(engine.pending_settings or engine.settings),
            "active": preferences_for(engine.settings),
            "allowed_ranges": (
                [{"start_hz": 1_000_000, "end_hz": 6_000_000_000}]
                if settings.allow_custom_ranges
                else ranges_for(settings)
            ),
            "pending": engine.pending_settings is not None,
            "source": settings.source,
        }

    @app.post("/api/settings")
    async def save_receiver_settings(preferences: ReceiverPreferences) -> dict[str, object]:
        if preferences.receive_gain is None:
            current = app.state.engine.pending_settings or app.state.engine.settings
            preferences = preferences.model_copy(update={"receive_gain": current.receive_gain})
        try:
            effective = apply_preferences(settings, preferences)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        app.state.store.save_preference("receiver", preferences.model_dump())
        app.state.engine.queue_settings(effective)
        return await receiver_settings()

    device_lock = asyncio.Lock()

    @app.get("/api/devices")
    async def usb_devices() -> dict[str, object]:
        if settings.source != "hackrf":
            return {"devices": [], "message": "Тестовый источник: выбор USB недоступен"}
        if library is None:
            raise HTTPException(409, "Библиотека HackRF не настроена")
        from radiomind.devices import list_devices

        async with device_lock:
            try:
                devices = await asyncio.to_thread(list_devices, library)
            except (RuntimeError, OSError, TimeoutError) as exc:
                raise HTTPException(409, str(exc)) from exc
        active_serial = getattr(app.state.engine.source, "device_serial", None)
        if active_serial and not any(d["serial"] == active_serial for d in devices):
            active = {
                "serial": active_serial,
                "label": f"HackRF USB · {active_serial} · сейчас используется",
            }
            if len(devices) == 1 and devices[0]["serial"] is None:
                devices = [active]
            else:
                devices.append(active)
        return {
            "devices": devices,
            "message": "" if devices else "HackRF не найден. Проверьте USB-подключение.",
        }

    @app.post("/api/frequency-profile")
    async def frequency_profile(profile: FrequencyProfile) -> dict[str, object]:
        return app.state.store.save_frequency_profile(
            profile.frequency_hz, profile.title, profile.favorite
        )

    @app.middleware("http")
    async def same_origin(request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (
            (origin is not None and origin != expected)
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "Cross-origin action rejected"}, status_code=403)
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(
            ROOT / "frontend" / "index.html",
            headers={
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self'; "
                "connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'",
                "Referrer-Policy": "no-referrer",
            },
        )

    @app.get("/app.js")
    def javascript() -> FileResponse:
        return FileResponse(ROOT / "frontend" / "app.js", media_type="text/javascript")

    @app.get("/style.css")
    def stylesheet() -> FileResponse:
        return FileResponse(ROOT / "frontend" / "style.css", media_type="text/css")

    @app.get("/messages.js")
    async def translations_script() -> FileResponse:
        return FileResponse(ROOT / "frontend/messages.js", media_type="text/javascript")

    @app.get("/i18n.js")
    async def localization_script() -> FileResponse:
        return FileResponse(ROOT / "frontend/i18n.js", media_type="text/javascript")

    @app.get("/api/status")
    async def status() -> dict[str, object]:
        process = app.state.process
        return {
            **app.state.engine.status(),
            "resources": {
                "process_cpu_percent": process.cpu_percent(),
                "rss_bytes": process.memory_info().rss,
                "disk_free_bytes": psutil.disk_usage(str(data_dir.resolve())).free,
            },
        }

    @app.get("/api/spectrum")
    async def spectrum() -> dict[str, object]:
        engine = app.state.engine
        if engine.frame is None or not engine.running:
            raise HTTPException(503, engine.error or "Waiting for a live frame")
        return engine.frame

    @app.get("/api/events")
    async def events(limit: int = Query(100, ge=1, le=200)) -> list[dict[str, object]]:
        return app.state.store.recent("event", limit)

    @app.get("/api/observations")
    async def observations(limit: int = Query(100, ge=1, le=200)) -> list[dict[str, object]]:
        return app.state.store.recent("observation", limit)

    @app.get("/api/digital-attempts")
    async def digital_attempts(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, object]]:
        return app.state.store.digital_attempts(limit)

    @app.get("/api/recordings")
    async def recordings(
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
        q: str = Query("", max_length=100),
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[dict[str, object]]:
        return app.state.store.recordings(
            limit, offset, q, since.isoformat() if since else "", until.isoformat() if until else ""
        )

    @app.get("/api/recordings/{recording_id}/audio")
    async def recording_audio(recording_id: str) -> FileResponse:
        row = app.state.store.recording(recording_id)
        if row is None or not row.get("playable"):
            raise HTTPException(404, "Recording is not available")
        try:
            path = app.state.engine.archive.path(recording_id)
        except ValueError as exc:
            raise HTTPException(404, "Invalid recording") from exc
        if not path.is_file():
            raise HTTPException(404, "Recording file is missing")
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.get("/api/conversations")
    async def conversations(
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
        q: str = Query("", max_length=100),
        since: datetime | None = None,
        until: datetime | None = None,
        view: Literal["all", "unlistened", "favorites", "favorite_channels"] = "all",
    ) -> list[dict[str, object]]:
        rows = app.state.store.conversations(
            limit,
            offset,
            q,
            since.isoformat() if since else "",
            until.isoformat() if until else "",
            view,
        )
        for row in rows:
            row["clean_status"] = app.state.cleaner.status(row["id"])
        return rows

    @app.post("/api/conversations/{session_id}/clean")
    async def clean_conversation(session_id: str) -> dict[str, str]:
        try:
            return {"status": app.state.cleaner.start(session_id)}
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/archive/delete-preview")
    async def delete_preview(selection: DeleteSelection) -> dict[str, object]:
        try:
            return app.state.deletion.preview(selection.session_id, selection.frequency_hz)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/archive/delete")
    async def delete_archive(confirmation: DeleteConfirmation) -> dict[str, object]:
        try:
            return app.state.deletion.commit(confirmation.token)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/conversations/{session_id}/audio")
    async def conversation_audio(
        session_id: str, variant: Literal["original", "cleaned"] = "original"
    ) -> Response:
        if variant == "cleaned":
            if not app.state.store.session_parts(session_id):
                raise HTTPException(404, "Conversation not found")
            try:
                path = app.state.cleaner.playback_path(session_id)
            except ValueError as exc:
                raise HTTPException(404, "Invalid conversation") from exc
            if not path.is_file():
                raise HTTPException(404, "Очищенная копия ещё не готова")
            return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})
        parts = app.state.store.session_parts(session_id)
        paths = []
        size = 0
        for part in parts:
            if not part.get("playable"):
                continue
            try:
                path = app.state.engine.archive.path(part["id"])
            except ValueError as exc:
                raise HTTPException(404, "Invalid recording") from exc
            if not path.is_file():
                raise HTTPException(404, "Conversation part is missing")
            # Only finalized application PCM16 mono WAV files, never partial files.
            with path.open("rb") as handle:
                header = handle.read(44)
            if len(header) != 44 or header[:4] != b"RIFF" or header[36:40] != b"data":
                raise HTTPException(409, "Invalid WAV part")
            length = struct.unpack_from("<I", header, 40)[0]
            if length + 44 != path.stat().st_size:
                raise HTTPException(409, "Incomplete WAV part")
            paths.append((path, length))
            size += length
        if not paths:
            raise HTTPException(404, "No completed conversation parts yet")
        if size > 0xFFFFFFFF - 36:
            raise HTTPException(409, "Conversation exceeds WAV size limit; use individual parts")
        wav_header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            size + 36,
            b"WAVE",
            b"fmt ",
            16,
            1,
            1,
            16000,
            32000,
            2,
            16,
            b"data",
            size,
        )

        def stream_parts() -> Iterator[bytes]:
            yield wav_header
            for path, length in paths:
                with path.open("rb") as handle:
                    handle.seek(44)
                    remaining = length
                    while remaining:
                        chunk = handle.read(min(65536, remaining))
                        if not chunk:
                            raise RuntimeError("Conversation part changed during playback")
                        remaining -= len(chunk)
                        yield chunk

        return StreamingResponse(
            stream_parts(),
            media_type="audio/wav",
            headers={"Cache-Control": "no-store", "Content-Length": str(size + 44)},
        )

    @app.post("/api/recordings/{recording_id}/review")
    async def review_recording(recording_id: str, review: RecordingReview) -> dict[str, object]:
        row = app.state.store.recording(recording_id)
        if row is None:
            raise HTTPException(404, "Recording not found")
        if review.title is not None:
            row["title"] = review.title.strip()
        if review.label is not None:
            row["review_label"] = review.label
            row["review_source"] = "owner"
            row["reviewed_utc"] = datetime.now(UTC).isoformat()
        if review.favorite is not None:
            row["favorite"] = review.favorite
        if review.listened is not None:
            parts = app.state.store.session_parts(row.get("session_id", recording_id))
            if review.listened and any(p["status"] == "recording" for p in parts):
                raise HTTPException(409, "Conversation is still being recorded")
            row["listened"] = review.listened
            row["listened_utc"] = datetime.now(UTC).isoformat() if review.listened else None
        app.state.store.save_recording(row)
        if review.label is not None and row.get("protocol"):
            app.state.store.review_digital_hint(row["frequency_hz"], row["protocol"])
        return row

    @app.get("/api/channels")
    async def channels() -> list[dict[str, object]]:
        return app.state.store.channels()

    @app.post("/api/channels")
    async def channel_change(change: ChannelChange) -> dict[str, object]:
        engine = app.state.engine
        try:
            frequency = engine.rules.change(change.frequency_hz, change.action)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return app.state.store.channel(frequency)

    @app.post("/api/control")
    async def control(command: Control) -> dict[str, object]:
        engine = app.state.engine
        if command.action == "stop":
            await engine.stop()
        elif command.action in {"watch", "sweep"}:
            engine.scheduler.mode = command.action
        else:
            await engine.start()
        return engine.status()

    @app.get("/live-audio.js")
    async def live_audio_script() -> FileResponse:
        return FileResponse(ROOT / "frontend/live-audio.js", media_type="text/javascript")

    @app.websocket("/ws/audio")
    async def live_audio(ws: WebSocket) -> None:
        await monitor_socket(ws, app.state.engine)

    @app.websocket("/ws")
    async def stream(ws: WebSocket) -> None:
        origin = ws.headers.get("origin")
        if origin and origin not in {
            "http://" + ws.headers.get("host", ""),
            "https://" + ws.headers.get("host", ""),
        }:
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            sequence = -1
            while True:
                engine = app.state.engine
                if engine.running and engine.frame and engine.frame["sequence"] != sequence:
                    sequence = engine.frame["sequence"]
                    await ws.send_json(engine.frame)
                await asyncio.sleep(settings.frame_period_ms / 1000)
        except (WebSocketDisconnect, TimeoutError):
            return

    return app
