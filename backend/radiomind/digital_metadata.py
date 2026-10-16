"""Privacy-minimized observations of pinned DSD-neo log syntax, not RF truth."""

import re
from typing import Any

INVALID = re.compile(r"CRC\s+ERR|FEC\s+ERR|G24\s+ERR|CACH/EMB\s+ERR|Checksum\s+Err", re.I)
SLOT = re.compile(r"\[SLOT([12])\]|\b(?:Slot|SLOT)\s+([12])\b")
BURST = re.compile(
    r"\|\s*(VLC|TLC|CSBK|MBCH|MBCC|DATA|R12[UC]|R34[UC]|R_1[UC]|UDT[UC]|USBD|IDLE|PI)\b"
)
PI = re.compile(
    r"\bSlot ([12]) DMR PI H- ALG ID: ([0-9A-F]{2}); KEY ID: [0-9A-F]{2}; "
    r"MI\((32|40)\): ([0-9A-F]+);\s*(.*)$"
)
FAMILIES = {1: "RC4", 2: "DES", 4: "AES-128", 5: "AES-256"}


class DMRMetadata:
    def __init__(self) -> None:
        self.slot = "unknown"
        self.slots: dict[str, dict[str, int]] = {}
        self.algorithms: dict[str, dict[str, int]] = {}

    def reset_context(self) -> None:
        self.slot = "unknown"

    def count(self, kind: str) -> None:
        counts = self.slots.setdefault(self.slot, {})
        counts[kind] = counts.get(kind, 0) + 1

    def observe(self, line: str, *, invalid: bool) -> bool:
        """Caller requires fresh, repeated DMR context; never retain IDs/MI/payload."""
        slot = SLOT.search(line)
        if slot:
            self.slot = slot[1] or slot[2]
        if invalid:
            self.count("invalid")
            return False
        burst = BURST.search(line)
        if burst:
            name = burst[1]
            kind = {
                "VLC": "voice_header",
                "TLC": "terminator",
                "IDLE": "idle",
                "PI": "privacy_header",
                "CSBK": "control",
                "MBCH": "control",
                "MBCC": "control",
            }.get(name, "data")
            self.count(kind)
        if re.search(r"\|\s*VC(?:[1-6]\*?|\*)\b|\|\s*VC\*(?:\s|$)", line):
            self.count("voice_burst")
        match = PI.search(line)
        if not match:
            if "DMR PI H-" in line:
                self.count("pi_observed")
                self.count("pi_unresolved")
            return False
        self.slot = match[1]
        self.count("pi_observed")
        algorithm, width, mi, family = int(match[2], 16), int(match[3]), match[4], match[5].strip()
        label = None
        # These messages are emitted by CRC/checksum-gated upstream branches.
        # Unknown algorithms or incomplete/mismatched messages remain uncertain.
        if len(mi) == width // 4:
            expected = FAMILIES.get(algorithm & 7)
            if algorithm in {1, 2, 4, 5, 0x21, 0x22, 0x24, 0x25} and width == 32:
                if family in {f"DMRA {expected};", f"DMRA Compatible {expected};"}:
                    label = expected
            if width == 40 and family.strip() == "Hytera Enhanced;":
                label = "Hytera Enhanced"
            # Kirisun also prints SO-dependent variants; do not infer its privacy
            # bit from ALG alone. Preserve uncertain evidence for future support.
        if label is None:
            self.count("pi_unresolved")
            return False
        self.count("crypto_header")
        algorithms = self.algorithms.setdefault(self.slot, {})
        algorithms[label] = algorithms.get(label, 0) + 1
        return True

    def snapshot(self) -> dict[str, Any]:
        return {
            "slots": {s: dict(c) for s, c in self.slots.items()},
            "algorithms": {s: dict(c) for s, c in self.algorithms.items()},
        }


def worker_summary(status: dict[str, Any]) -> dict[str, Any]:
    transport = status.get("transport", {})
    return {
        key: status.get(key, {})
        for key in ("protocol", "sync_counts", "invalid_counts", "dmr_frames")
    } | {
        "mode": transport.get("mode", "unknown") if isinstance(transport, dict) else "multi",
        "dmr_call_confirmed": status.get("dmr_call_confirmed", False),
    }


def frame_summary(workers: list[dict[str, Any]]) -> dict[str, int]:
    """Max across duplicate probes, sum across slots; not a frame-error rate."""
    result: dict[str, int] = {}
    for worker in workers:
        counts: dict[str, int] = {}
        for slot in worker.get("dmr_frames", {}).get("slots", {}).values():
            for key, value in slot.items():
                counts[key] = counts.get(key, 0) + value
        for key, value in counts.items():
            result[key] = max(result.get(key, 0), value)
    return result
