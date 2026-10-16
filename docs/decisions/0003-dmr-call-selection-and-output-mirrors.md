# DMR call selection and native output mirrors

All DMR workers, including AUTO and explicitly selected DMR, require repeated
non-error call-address evidence before their PCM can select the digital path.
Nonzero audio and synchronization alone do not establish a valid voice call.
Pending PCM remains bounded and is preserved on confirmation. Other formats may
still win discovery; a DMR candidate does not suppress analog speech. Store a
privacy-minimized selection snapshot without addresses or raw decoder logs.
Track repetition independently per TDMA slot, so alternating conversations cannot
reset each other's evidence or count as repetition across slots. Even configurations
with all probes disabled use the same dispatch admission policy.

Pinned DSD-neo 2.10.0 can copy an active BS voice slot into both UDP output
channels. These channels therefore are not always independent TDMA conversations.
For new journals marked dmr_publication_policy=2, publication can retain only the
evidenced slot when all of the following hold:

- DMR call confirmation was present at selection; exactly one worker remains.
- Only one known slot has voice header/burst evidence, with at least three bursts.
- Both tracks have equal lengths of at least one second.
- At least 99.9% of final PCM samples match exactly and the residual RMS is at
  most 1% of the retained track's RMS.

This is conservative mirror detection, not proof of slot provenance or clear
speech. It retains the chosen track byte-for-byte and never averages channels.
Store `single_slot_mirror` in recording metadata. Distinct audio, unknown/dual voice
evidence and old journals preserve both tracks; existing recordings are untouched.
The previous exact direct-mode folding remains supported independently.

The thresholds tolerate tiny native transition residuals while preserving distinct
conversation fragments. Missing/incorrect decoder evidence is still a limitation;
an explicitly framed native slot transport would provide stronger provenance.
Near-identical simultaneous transmissions cannot always be distinguished without it.
Stricter call confirmation can reject short/damaged calls with missing headers.

Tests cover AUTO/forced/probe selection and retained onset, slot 2, residual/energy
limits, genuine dual-slot evidence, legacy behavior, recovery and publication retry.
Public reference replays check PCM onset and length. Synthetic and adapter checks
are not hardware or intelligibility acceptance. No RF tuning, crypto bypass, ASR,
native binary replacement or retrospective archive changes are part of this change.
