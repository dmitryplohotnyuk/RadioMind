from radiomind.config import Window


class Scheduler:
    def __init__(self, windows: list[Window], mode: str = "sweep") -> None:
        if not windows or mode not in {"watch", "sweep"}:
            raise ValueError("Need windows and a supported mode")
        self.windows, self.mode = windows, mode
        self.index = 0
        self.since: float | None = None
        self.last_observed: dict[str, float] = {}
        self.priority_indices: list[int] = []
        self.priority_cursor = 0
        self.sweep_index = 0
        self.normal_visits = 1
        self.on_priority = False

    def set_priorities(self, frequencies: list[int]) -> None:
        indices = []
        for frequency in frequencies:
            candidates = [
                (min(frequency - w.start_hz, w.end_hz - frequency), i)
                for i, w in enumerate(self.windows)
                if w.start_hz + 6500 <= frequency <= w.end_hz - 6500
                and abs(frequency - w.center_hz) > 12500
            ]
            if candidates:
                index = max(candidates)[1]
                if index not in indices:
                    indices.append(index)
        self.priority_indices = indices

    def choose(self, now: float, ready: bool = True) -> Window:
        if self.since is None:
            self.since = now
        current = self.windows[self.index]
        if self.mode == "sweep" and ready and now - self.since >= current.dwell_ms / 1000:
            next_normal = (self.sweep_index + 1) % len(self.windows)
            options = [i for i in self.priority_indices if i not in {self.index, next_normal}]
            if not self.on_priority and self.normal_visits >= 3 and options:
                self.index = options[self.priority_cursor % len(options)]
                self.priority_cursor += 1
                self.normal_visits = 0
                self.on_priority = True
            else:
                self.index = self.sweep_index = next_normal
                self.normal_visits += 1
                self.on_priority = False
            self.since = now
        return self.windows[self.index]

    def observed(self, name: str, now: float) -> None:
        self.last_observed[name] = now

    def coverage(self, now: float, current: str | None) -> list[dict[str, object]]:
        return [
            {
                "name": w.name,
                "start_hz": w.start_hz,
                "end_hz": w.end_hz,
                "observing": w.name == current,
                "seconds_since_last_frame": (
                    round(max(0, now - self.last_observed[w.name]), 2)
                    if w.name in self.last_observed
                    else None
                ),
            }
            for w in self.windows
        ]
