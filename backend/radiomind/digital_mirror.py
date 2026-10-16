"""Conservative native DMR output mirror detection, not speech classification."""

from typing import Any

import numpy as np

from radiomind.nfm import Audio
from radiomind.pcm import pcm16


def mirrored_slot(metadata: dict[str, Any], tracks: list[tuple[int, Audio]]) -> int | None:
    """Only new journals can fold a near-exact pair with one evidenced voice slot.

    DSD copies the active BS slot into the idle output channel. Tiny residuals can
    remain at transitions. Never infer this from correlation alone or average slots.
    """
    if (
        metadata.get("protocol") != "DMR"
        or metadata.get("dmr_publication_policy") != 2
        or len(tracks) != 2
        or {s for s, _ in tracks} != {1, 2}
    ):
        return None
    evidence = metadata.get("decoder_evidence", {})
    selection = evidence.get("selection_evidence", {})
    if selection.get("protocol") != "DMR" or selection.get("dmr_call_confirmed") is not True:
        return None
    workers = evidence.get("worker_evidence", [])
    if len(workers) != 1:
        return None
    slots = workers[0].get("dmr_frames", {}).get("slots", {})
    voiced = {
        slot
        for slot, counts in slots.items()
        if counts.get("voice_burst", 0) or counts.get("voice_header", 0)
    }
    if len(voiced) != 1 or not voiced <= {"1", "2"}:
        return None
    slot = voiced.pop()
    if slots[slot].get("voice_burst", 0) < 3:
        return None
    arrays = {s: pcm16(a).astype(np.float64) for s, a in tracks}
    primary, other = arrays[int(slot)], arrays[3 - int(slot)]
    if primary.shape != other.shape or primary.size < 16000:
        return None
    residual = primary - other
    if np.count_nonzero(residual) > primary.size * 0.001:
        return None
    energy = float(np.dot(primary, primary))
    if energy <= 0 or float(np.dot(residual, residual)) > energy * 0.0001:
        return None
    return int(slot)
