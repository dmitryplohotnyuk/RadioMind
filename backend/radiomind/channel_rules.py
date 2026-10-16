import time
from datetime import UTC, datetime
from typing import Literal

from radiomind.config import Settings
from radiomind.storage import Store


class ChannelRules:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings, self.store = settings, store
        self.authorized_windows = settings.effective_windows
        self.retry_after: dict[int, float] = {}

    def key(self, frequency: float) -> int:
        step = self.settings.audio.channel_step_hz
        return round(frequency / step) * step

    def priorities(self) -> list[int]:
        frequencies = set(self.settings.audio.priority_frequencies_hz)
        for row in self.store.channels():
            if row["manual"]:
                frequencies.discard(row["frequency_hz"])
            elif row["priority"]:
                frequencies.add(row["frequency_hz"])
        return sorted(frequencies)

    def eligible(self, frequency: int, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        row = self.store.channel(frequency)
        if row["manual"] or self.retry_after.get(frequency, 0) > now:
            return False
        priority = row["priority"] or frequency in self.settings.audio.priority_frequencies_hz
        return bool(priority or row["expires"] <= now)

    def outcome(
        self, frequency: int, speech: bool, now: float | None = None, *, protocol: str | None = None
    ) -> None:
        now = time.time() if now is None else now
        row = self.store.channel(frequency)
        rejected = self.store.digital_rejected(frequency, protocol)
        speech = speech and not rejected
        if len(self.retry_after) >= 10000:
            self.retry_after = {k: v for k, v in self.retry_after.items() if v > now}
        self.retry_after[frequency] = now + 5
        if speech:
            row.update(failures=0, expires=0, reason="speech_candidate")
        else:
            row["failures"] += 1
            row["reason"] = "owner_rejected_digital" if rejected else "speech_not_confirmed"
            if (
                row["failures"] >= self.settings.audio.cooldown_failures
                and not row["priority"]
                and frequency not in self.settings.audio.priority_frequencies_hz
            ):
                multiplier = min(
                    12, 2 ** min(4, row["failures"] // self.settings.audio.cooldown_failures - 1)
                )
                row["expires"] = now + min(3600, self.settings.audio.cooldown_seconds * multiplier)
        self.store.save_channel(row)

    def change(
        self, frequency: int, action: Literal["exclude", "restore", "priority", "normal"]
    ) -> int:
        frequency = self.key(frequency)
        windows = (
            self.settings.effective_windows if action == "priority" else self.authorized_windows
        )
        custom_metadata = (
            self.settings.allow_custom_ranges
            and action != "priority"
            and 1_000_000 <= frequency <= 6_000_000_000
        )
        if not custom_metadata and not any(w.start_hz <= frequency <= w.end_hz for w in windows):
            raise ValueError("Frequency is outside configured windows")
        row = self.store.channel(frequency)
        if action == "exclude":
            row.update(manual=1, reason="owner_excluded")
        elif action == "restore":
            row.update(manual=0, failures=0, expires=0, reason="owner_restored")
            self.retry_after.pop(frequency, None)
        elif action == "priority":
            row.update(priority=1, manual=0, expires=0, reason="owner_priority")
        else:
            row.update(priority=0)
        self.store.append(
            "audit", datetime.now(UTC).isoformat(), {"action": action, "frequency_hz": frequency}
        )
        self.store.save_channel(row)
        return frequency
