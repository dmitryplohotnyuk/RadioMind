"""Loss-tolerant monitoring, separate from loss-sensitive recording. Owner loop only."""

import asyncio
import time
from collections import deque
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class LiveAudio:
    def __init__(self) -> None:
        self.clients = 0
        self.sequence = 0
        self.session = ""
        # Accepted pre-roll (up to 3 s) arrives in one burst, not in real time.
        # Preserve it plus catch-up margin without ever blocking archive writes.
        self.frames: deque[tuple[int, float, bytes]] = deque(maxlen=200)

    def publish(self, session: str, pcm: bytes) -> None:
        if not self.clients:
            return
        if session != self.session:
            self.frames.clear()
            self.session = session
        now = time.monotonic()
        for offset in range(0, len(pcm), 640):
            self.sequence += 1
            self.frames.append((self.sequence, now, pcm[offset : offset + 640]))

    def after(self, cursor: int) -> list[tuple[int, float, bytes]]:
        cutoff = time.monotonic() - 0.5
        return [frame for frame in self.frames if frame[0] > cursor and frame[1] >= cutoff]

    def clear(self) -> None:
        self.frames.clear()
        self.session = ""


async def monitor_socket(ws: WebSocket, engine: Any) -> None:
    origin = ws.headers.get("origin")
    if origin and origin not in {
        "http://" + ws.headers.get("host", ""),
        "https://" + ws.headers.get("host", ""),
    }:
        await ws.close(code=1008)
        return
    bus = engine.archive.live_audio
    if bus.clients >= 4:
        await ws.close(code=1013)
        return
    await ws.accept()
    bus.clients += 1
    cursor, session = bus.sequence, ""
    last_state = ""
    try:
        while True:
            frames = bus.after(cursor)
            conversation = engine.conversation
            digital = getattr(conversation, "choice", None) == "digital"
            recording = conversation is not None and conversation.writer is not None
            state = "digital" if digital else "listening" if recording else "waiting"
            if frames:
                if session != bus.session or frames[0][0] != cursor + 1:
                    await asyncio.wait_for(ws.send_json({"type": "reset"}), 0.25)
                session = bus.session
                await asyncio.wait_for(ws.send_bytes(b"".join(f[2] for f in frames)), 0.25)
                cursor = frames[-1][0]
            if state != last_state:
                await asyncio.wait_for(ws.send_json({"type": "state", "state": state}), 0.25)
                last_state = state
            # Observe disconnect even when no recording exists; no sender backlog.
            try:
                message = await asyncio.wait_for(ws.receive(), 0.04)
                if message["type"] == "websocket.disconnect":
                    break
            except TimeoutError:
                pass
    except (WebSocketDisconnect, TimeoutError, OSError):
        pass
    finally:
        bus.clients -= 1
        if not bus.clients:
            bus.clear()
        try:
            await ws.close()
        except (RuntimeError, WebSocketDisconnect, OSError):
            pass
