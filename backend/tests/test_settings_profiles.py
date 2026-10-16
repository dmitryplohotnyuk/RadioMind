import asyncio
import ctypes as ct
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from radiomind.api import create_app
from radiomind.config import Settings, load_settings
from radiomind.devices import DeviceList, enumerate_native
from radiomind.engine import Engine
from radiomind.hackrf import HackRFSource
from radiomind.policy import require_audio, require_permission
from radiomind.receiver_settings import ReceiverPreferences, apply_preferences, ranges_for
from radiomind.storage import Store


def profile():
    return load_settings(Path("backend/tests/fixtures/scanner.yaml"))


def preference(start=144000000, end=146000000, serial=None, enabled=True):
    return {
        "device_serial": serial,
        "ranges": [{"start_hz": start, "end_hz": end, "enabled": enabled}],
    }


def test_ranges_permissions_splitting_and_restart(tmp_path):
    base = profile()
    base.allow_custom_ranges = False  # Restricted launch profiles retain their envelope.
    initial = {"device_serial": None, "ranges": ranges_for(base), "receive_gain": "normal"}
    narrow = apply_preferences(base, ReceiverPreferences.model_validate(preference()))
    assert preferences_for_test(narrow) == [(144000000, 146000000)]
    for window in narrow.windows:
        require_permission(narrow, window, "observe")
    require_audio(narrow, narrow.windows[0], 145000000)
    with pytest.raises(PermissionError, match="selected scan ranges"):
        require_audio(narrow, narrow.windows[0], 143000000)
    with TestClient(create_app(base, tmp_path, autostart=False)) as client:
        assert client.get("/api/settings").json()["active"] == initial
        for invalid in [
            preference(139000000, 141000000),
            preference(169000000, 421000000),
            preference(145000000, 144000000),
            preference(145000000, 145000001),
            {"device_serial": None, "ranges": []},
            preference(serial="../bad"),
        ]:
            assert client.post("/api/settings", json=invalid).status_code == 422
        assert client.get("/api/settings").json()["active"] == initial
        assert (
            client.post(
                "/api/settings", json=initial, headers={"origin": "https://other.example"}
            ).status_code
            == 403
        )
        chosen = preference(140000000, 170000000, "0" * 31 + "1")
        result = client.post("/api/settings", json=chosen)
        assert result.status_code == 200 and not result.json()["pending"]
    with TestClient(create_app(base, tmp_path, autostart=False)) as client:
        assert client.get("/api/settings").json()["desired"] == {**chosen, "receive_gain": "normal"}
        windows = client.get("/api/status").json()["coverage"]
        assert windows[0]["start_hz"] == 140000000 and windows[-1]["end_hz"] == 170000000
        assert all(w["end_hz"] - w["start_hz"] <= 8000000 for w in windows)
        assert all(a["end_hz"] >= b["start_hz"] for a, b in zip(windows, windows[1:], strict=False))


def preferences_for_test(settings):
    return [(r.start_hz, r.end_hz) for r in settings.scan_ranges]


def test_custom_ranges_outside_original_profile_persist_and_keep_action_gates(tmp_path):
    base = profile()
    assert base.allow_custom_ranges
    chosen = preference(230000000, 260000000)
    app = create_app(base, tmp_path, autostart=False)
    with TestClient(app) as client:
        result = client.post("/api/settings", json=chosen)
        assert result.status_code == 200
        effective = app.state.engine.settings
        assert effective.rx_only and effective.audio.enabled
        assert [(w.start_hz, w.end_hz) for w in effective.windows] == [
            (230000000, 238000000),
            (236000000, 244000000),
            (242000000, 250000000),
            (248000000, 256000000),
            (252000000, 260000000),
        ]
        for window in effective.windows:
            require_permission(effective, window, "observe")
        require_audio(effective, effective.windows[0], 231000000)
        with pytest.raises(PermissionError):
            require_permission(effective, effective.windows[0], "record_iq")
        for action in ("exclude", "restore", "priority"):
            assert (
                client.post(
                    "/api/channels", json={"frequency_hz": 231000000, "action": action}
                ).status_code
                == 200
            )
        # Invalid edits never replace the successfully saved range.
        for invalid in [
            preference(999999, 9000000),
            preference(5999000000, 6000000001),
            preference(250000000, 240000000),
            preference(240000000, 240000001),
            {"ranges": [chosen["ranges"][0], {"start_hz": 250000000, "end_hz": 270000000}]},
        ]:
            assert client.post("/api/settings", json=invalid).status_code == 422
        assert client.get("/api/settings").json()["desired"]["ranges"] == chosen["ranges"]
    with TestClient(create_app(base, tmp_path, autostart=False)) as client:
        assert client.get("/api/settings").json()["active"]["ranges"] == chosen["ranges"]
        assert client.get("/api/settings").json()["allowed_ranges"] == [
            {"start_hz": 1000000, "end_hz": 6000000000}
        ]
    # The opt-in changes frequency selection, not permission to enable recording.
    observation = Settings(allow_custom_ranges=True)
    selected = apply_preferences(observation, ReceiverPreferences.model_validate(chosen))
    assert not selected.audio.enabled
    assert all(w.allowed_actions == ["observe"] for w in selected.windows)


@pytest.mark.parametrize(
    "start,end",
    [(1000000, 1025000), (2400000000, 2400025000), (5999975000, 6000000000), (1000000, 6000000000)],
)
def test_custom_window_edges_and_full_hardware_span(start, end):
    selected = apply_preferences(
        profile(), ReceiverPreferences.model_validate(preference(start, end))
    )
    assert 1 <= len(selected.windows) <= 1024
    assert selected.windows[0].start_hz <= start
    assert selected.windows[-1].end_hz >= end
    for window in selected.windows:
        assert 1000000 <= window.start_hz < window.end_hz <= 6000000000
        assert window.end_hz - window.start_hz == 8000000
        require_permission(selected, window, "observe")
    assert all(
        a.end_hz >= b.start_hz for a, b in zip(selected.windows, selected.windows[1:], strict=False)
    )
    if end - start == 25000:
        midpoint = (start + end) // 2
        assert abs(selected.windows[0].center_hz - midpoint) > 12500
        require_audio(selected, selected.windows[0], midpoint)
        outside = start - 100000 if start > 1000000 else end + 100000
        with pytest.raises(PermissionError):
            require_audio(selected, selected.windows[0], outside)


@pytest.mark.parametrize("enabled", [True, False])
def test_settings_wait_for_conversation_boundary(tmp_path, monkeypatch, enabled):
    async def run():
        base = Settings()
        store = Store(tmp_path / "mock.sqlite3", 10000)
        engine = Engine(base, store)
        entered, release = asyncio.Event(), asyncio.Event()
        replacement = apply_preferences(
            base, ReceiverPreferences.model_validate(preference(enabled=enabled))
        )
        calls = []

        async def capture():
            calls.append(engine.settings)
            if len(calls) == 1:
                engine.conversation = SimpleNamespace(done=False)
                entered.set()
                await release.wait()
                assert engine.settings is base
                engine.conversation = None
            else:
                engine.stop_requested = True

        monkeypatch.setattr(engine, "_capture", capture)
        try:
            await engine.start()
            await entered.wait()
            engine.queue_settings(replacement)
            assert engine.pending_settings is replacement
            assert engine.settings is base and len(calls) == 1
            release.set()
            await engine.task
            assert calls == ([base, replacement] if enabled else [base])
            assert not engine.running
            assert engine.rules.settings is replacement and engine.archive.settings is replacement
            assert engine.pending_settings is None
        finally:
            store.close()

    asyncio.run(run())


def test_frequency_names_favorites_listening_do_not_change_rf_rules(tmp_path):
    app = create_app(Settings(), tmp_path, autostart=False)
    ids = [uuid4().hex, uuid4().hex]
    with TestClient(app) as client:
        for ident, frequency in zip(ids, [145000000, 433500000], strict=False):
            app.state.store.save_recording(
                {
                    "id": ident,
                    "frequency_hz": frequency,
                    "status": "ready",
                    "start_utc": "2026-10-15T00:00:00Z",
                    "playable": False,
                }
            )
        response = client.post(
            "/api/frequency-profile",
            json={"frequency_hz": 145000000, "title": "  Диспетчер  ", "favorite": True},
        )
        assert response.status_code == 200 and response.json()["title"] == "Диспетчер"
        assert not response.json()["priority"] and not response.json()["manual"]
        assert client.get("/api/conversations?q=диспетчер").json()[0]["id"] == ids[0]
        assert len(client.get("/api/conversations?view=favorite_channels").json()) == 1
        assert client.get("/api/conversations?view=favorites").json() == []
        assert (
            client.post(
                f"/api/recordings/{ids[0]}/review", json={"title": "Вызов", "listened": True}
            ).status_code
            == 200
        )
        assert client.get("/api/conversations?q=вызов").json()[0]["id"] == ids[0]
        assert len(client.get("/api/conversations?view=unlistened").json()) == 1
        client.post("/api/channels", json={"frequency_hz": 145000000, "action": "exclude"})
        client.post("/api/frequency-profile", json={"frequency_hz": 145000000, "favorite": False})
        assert app.state.store.channel(145000000)["manual"]
        assert app.state.store.channel(145000000)["title"] == "Диспетчер"
    with TestClient(create_app(Settings(), tmp_path, autostart=False)) as client:
        row = client.get("/api/conversations?q=диспетчер").json()[0]
        assert row["listened"] and row["frequency_excluded"]
        assert row["title"] == "Вызов" and not row["frequency_favorite"]


def test_native_inventory_never_opens_and_serial_selection_never_falls_back(tmp_path, monkeypatch):
    library = tmp_path / "fake.dll"
    library.touch()
    serial = "0123456789abcdef0123456789abcdef"
    numbers = (ct.c_char_p * 2)(serial.encode(), None)
    listing = DeviceList(numbers, None, None, 2, None, 2)
    calls = []

    class Library:
        def __getattr__(self, name):
            def function(*args):
                calls.append((name, args))
                if name == "hackrf_device_list":
                    return ct.pointer(listing)
                if name == "hackrf_open_by_serial":
                    return -5
                return 0

            setattr(self, name, function)
            return function

    monkeypatch.setattr(ct, "CDLL", lambda _: Library())
    result = enumerate_native(library)
    assert result[0]["serial"] == serial and result[1]["serial"] is None
    assert [name for name, _ in calls] == [
        "hackrf_init",
        "hackrf_device_list",
        "hackrf_device_list_free",
        "hackrf_exit",
    ]
    calls.clear()
    with pytest.raises(RuntimeError, match="open failed"):
        HackRFSource(library, serial=serial)
    assert [name for name, _ in calls] == ["hackrf_init", "hackrf_open_by_serial", "hackrf_exit"]
    assert calls[1][1][0] == serial.encode()


def test_disabled_ranges_persist_and_never_open_hardware(tmp_path, monkeypatch):
    base = profile()
    chosen = {
        "ranges": [
            {"start_hz": 140000000, "end_hz": 170000000, "enabled": False},
            {"start_hz": 420000000, "end_hz": 450000000, "enabled": True},
        ]
    }
    calls = []

    async def capture(engine):
        calls.append(engine.settings)
        engine.stop_requested = True

    monkeypatch.setattr(Engine, "_capture", capture)
    with TestClient(create_app(base, tmp_path, autostart=False)) as client:
        assert client.post("/api/settings", json=chosen).status_code == 200
        coverage = client.get("/api/status").json()["coverage"]
        assert coverage and all(w["start_hz"] >= 420000000 for w in coverage)
    with TestClient(create_app(base, tmp_path, autostart=False)) as client:
        assert client.get("/api/settings").json()["active"]["ranges"] == chosen["ranges"]
        chosen["ranges"][1]["enabled"] = False
        assert client.post("/api/settings", json=chosen).status_code == 200
        assert client.get("/api/status").json()["coverage"] == []
    with TestClient(create_app(base, tmp_path, autostart=True)) as client:
        assert not client.get("/api/status").json()["running"]
        assert not client.get("/api/status").json()["scan_enabled"]
        assert client.post("/api/control", json={"action": "start"}).status_code == 200
        assert not calls
        chosen["ranges"][0]["enabled"] = True
        assert client.post("/api/settings", json=chosen).status_code == 200
        status = client.get("/api/status").json()
        assert status["scan_enabled"] and not status["running"]
        assert all(w["end_hz"] <= 170000000 for w in status["coverage"])
        assert client.post("/api/control", json={"action": "start"}).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("custom", [True, False])
def test_disabled_range_mask_inside_physical_window_and_legacy_default(custom):
    base = profile()
    base.allow_custom_ranges = custom
    prefs = ReceiverPreferences.model_validate(
        {
            "ranges": [
                {"start_hz": 144000000, "end_hz": 145000000},
                {"start_hz": 145000000, "end_hz": 146000000, "enabled": False},
            ]
        }
    )
    assert prefs.ranges[0].enabled  # Existing saved preferences remain enabled.
    selected = apply_preferences(base, prefs)
    window = next(w for w in selected.windows if w.start_hz < 144500000 < w.end_hz)
    require_audio(selected, window, 144500000)
    assert window.start_hz < 145500000 < window.end_hz
    with pytest.raises(PermissionError, match="selected scan ranges"):
        require_audio(selected, window, 145500000)
    for band in prefs.ranges:
        band.enabled = False
    disabled = apply_preferences(base, prefs)
    assert not disabled.has_enabled_ranges
    with pytest.raises(PermissionError, match="selected scan ranges"):
        require_audio(disabled, disabled.windows[0], 144500000)
