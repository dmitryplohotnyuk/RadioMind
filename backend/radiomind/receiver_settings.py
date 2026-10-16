"""Persistent RX preferences with optional owner-defined hardware scan ranges."""

from pydantic import Field

from radiomind.config import ReceiveGain, ScanRange, Settings, StrictModel, Window


class ReceiverPreferences(StrictModel):
    device_serial: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    ranges: list[ScanRange] = Field(min_length=1, max_length=16)
    receive_gain: ReceiveGain | None = None


def ranges_for(settings: Settings) -> list[dict[str, int]]:
    merged: list[dict[str, int]] = []
    for window in sorted(settings.effective_windows, key=lambda w: w.start_hz):
        if merged and window.start_hz <= merged[-1]["end_hz"]:
            merged[-1]["end_hz"] = max(merged[-1]["end_hz"], window.end_hz)
        else:
            merged.append({"start_hz": window.start_hz, "end_hz": window.end_hz})
    return merged


def preferences_for(settings: Settings) -> dict[str, object]:
    return {
        "device_serial": settings.device_serial,
        "receive_gain": settings.receive_gain,
        "ranges": [r.model_dump() for r in settings.scan_ranges] or ranges_for(settings),
    }


def apply_preferences(base: Settings, prefs: ReceiverPreferences) -> Settings:
    required = {"observe"}
    if base.audio.enabled:
        required |= {"demodulate", "record_audio"}
    permitted = [w for w in base.effective_windows if required <= set(w.allowed_actions)]
    ranges = sorted(prefs.ranges, key=lambda r: r.start_hz)
    previous = 0
    for band in ranges:
        if band.start_hz < previous:
            raise ValueError("Диапазоны не должны пересекаться")
        previous = band.end_hz
        if base.allow_custom_ranges:
            continue
        cursor = band.start_hz
        for allowed in sorted(permitted, key=lambda w: w.start_hz):
            if allowed.start_hz <= cursor < allowed.end_hz:
                cursor = max(cursor, allowed.end_hz)
        if cursor < band.end_hz:
            raise ValueError("Диапазон выходит за разрешённые границы профиля приёма")
    active = [r for r in ranges if r.enabled]
    # Restricted profiles retain their physical windows. Opted-in profiles build
    # new windows below; both paths retain the exact candidate/audio range mask.
    windows = [
        w for w in permitted if any(w.start_hz < r.end_hz and w.end_hz > r.start_hz for r in active)
    ]
    if base.allow_custom_ranges:
        if not permitted:
            raise ValueError("Profile does not permit the requested RX actions")
        windows = custom_windows(active, permitted[0])
    # Keep valid dormant windows when all ranges are off. Engine.start/_run guard
    # this state before opening RX; the exact mask also rejects every channel.
    if not active:
        windows = base.effective_windows
    data = base.model_dump()
    data.update(
        device_serial=prefs.device_serial,
        receive_gain=prefs.receive_gain or base.receive_gain,
        windows=[w.model_dump() for w in windows],
        scan_ranges=[r.model_dump() for r in ranges],
    )
    return Settings.model_validate(data)


def custom_windows(ranges: list[ScanRange], template: Window) -> list[Window]:
    """Tile selected bands, retaining full-rate RX and bounded overlap at edges.

    Physical sampling can extend past narrow selections; scan_ranges remains the
    exact detection/audio mask. Shift narrow bands away from the LO DC blind spot.
    """
    width = template.sample_rate_sps
    step = width * 3 // 4
    starts: set[int] = set()
    for band in ranges:
        if band.end_hz - band.start_hz < width:
            midpoint = (band.start_hz + band.end_hz) // 2
            offset = min(width // 4, (width - (band.end_hz - band.start_hz)) // 2)
            choices = [
                max(1_000_000, min(6_000_000_000 - width, midpoint - width // 2 + shift))
                for shift in (offset, -offset)
            ]
            starts.add(max(choices, key=lambda start: abs(start + width // 2 - midpoint)))
        else:
            start = band.start_hz
            while True:
                starts.add(start)
                if start + width >= band.end_hz:
                    break
                start = min(start + step, band.end_hz - width)
    return [
        Window(
            name=f"RX {start}-{start + width}",
            start_hz=start,
            end_hz=start + width,
            sample_rate_sps=width,
            dwell_ms=template.dwell_ms,
            allowed_actions=template.allowed_actions,
        )
        for start in sorted(starts)
    ]
