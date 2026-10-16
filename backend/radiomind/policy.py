from radiomind.config import Action, Settings, Window


def require_permission(settings: Settings, window: Window, action: Action) -> None:
    """Deny by default. Synthetic fixtures never authorize a physical receiver."""
    if action not in {"observe", "demodulate", "record_audio"}:
        raise PermissionError("IQ recording, ASR and export are not implemented")
    if action not in window.allowed_actions:
        raise PermissionError("Action is not allowed for this window")
    if settings.source == "hackrf":
        if window not in settings.windows or not settings.country or not settings.legal_basis:
            raise PermissionError("Hardware window is not explicitly authorized")
        if window.end_hz - window.start_hz != window.sample_rate_sps:
            raise PermissionError(
                "Hardware spike requires the entire physical sampling band inside the allowlist; "
                "narrow-window capture needs a separate reviewed configuration"
            )


def require_audio(settings: Settings, window: Window, frequency_hz: int) -> None:
    if not settings.audio.enabled or not settings.country or not settings.legal_basis:
        raise PermissionError("Audio recording is not authorized in this profile")
    if window not in settings.windows:
        raise PermissionError("Unknown recording window")
    require_permission(settings, window, "demodulate")
    require_permission(settings, window, "record_audio")
    if not window.start_hz + 6250 <= frequency_hz <= window.end_hz - 6250:
        raise PermissionError("Entire NFM channel must lie inside an authorized window")
    if settings.scan_ranges and not any(
        r.enabled and r.start_hz + 6250 <= frequency_hz <= r.end_hz - 6250
        for r in settings.scan_ranges
    ):
        raise PermissionError("Channel is outside the selected scan ranges")
