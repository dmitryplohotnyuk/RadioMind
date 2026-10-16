import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient
from test_digital import FakeDecoder
from test_scan_archive import audio_settings

from radiomind.api import create_app


@pytest.mark.parametrize("input_mode", ["flat_fm", "iq"])
def test_decoder_startup_snapshots_mode_on_owner_while_archive_http_remains_live(
    tmp_path, monkeypatch, input_mode
):
    settings = audio_settings()
    settings.digital.enabled = True
    settings.digital.input_mode = input_mode
    created = []

    class SlowDecoder(FakeDecoder):
        def __init__(self, executable, mode="auto", **kwargs):
            created.append((threading.get_ident(), mode))
            time.sleep(0.005)  # Simulate native startup off the event loop.
            super().__init__(executable, mode)

    monkeypatch.setattr("radiomind.digital_conversation.DigitalDispatch", SlowDecoder)
    app = create_app(settings, tmp_path, autostart=False)
    with TestClient(app) as client:
        owner = client.portal.call(threading.get_ident)
        store = app.state.store
        client.portal.call(store.remember_digital, 145000000, "NXDN48")
        client.portal.call(
            store.save_recording,
            {
                "id": "a" * 32,
                "frequency_hz": 145000000,
                "title": "Речь",
                "start_utc": "2026-10-15T10:00:00Z",
                "status": "ready",
                "playable": False,
            },
        )
        lookup = store.digital_mode
        lookups = []

        def owner_lookup(frequency):
            # Fail immediately BEFORE SQLite if the old worker access returns;
            # a regression must not deadlock/hang the test runner itself.
            ident = threading.get_ident()
            assert ident == owner, "SQLite lookup escaped its owner thread"
            lookups.append(ident)
            return lookup(frequency)

        monkeypatch.setattr(store, "digital_mode", owner_lookup)

        async def start_decoders():
            for _ in range(40):
                conv = await app.state.engine.prepare_conversation(
                    settings.windows[0], 145000000, 20, None
                )
                assert conv.digital.mode == "NXDN48"
                conv.digital.close()
                await asyncio.sleep(0)

        task = client.portal.start_task_soon(start_decoders)
        for _ in range(30):
            # Nonempty Unicode search executes the Python casefold SQL callback.
            response = client.get("/api/conversations", params={"q": "РЕЧЬ"})
            assert response.status_code == 200 and len(response.json()) == 1
            assert client.get("/api/status").status_code == 200
        task.result(timeout=10)
        assert len(lookups) == len(created) == 40
        assert all(ident != owner and mode == "NXDN48" for ident, mode in created)
