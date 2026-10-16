# Decision 0002: Protocol-scoped frame and privacy evidence

Date: 2026-10-15. Owner authorizes diagnosis fixes after unintelligible DMR reports.

Pinned DSD-neo v2.10.0 emits CRC-gated DMRA PI H headers with ALG/KEY/MI fields and
RC4/DES/AES family text, without the words matched by our old crypto regex. Its
Hytera PI branch emits a positive family marker only after checksum acceptance.
The previous generic frame-error diagnosis also combined unrelated probe modes.

Parse these exact PI H shapes only in a fresh (one input-second), repeated DMR
context. Require complete size/family/algorithm-consistent DMRA headers or the
positive Hytera checksum branch. Unknown/malformed/unsupported Kirisun indications
remain unresolved. Checksum/CRC/FEC failures cannot confirm crypto. Retain existing
native muting and conservative whole-candidate veto on supported crypto evidence;
there is no new key, decryption, encoder or arbitrary native option interface.

Keep bounded per-worker/per-slot DMR report counters for voice header/burst,
terminator, idle, data/control and privacy observations. Store only counts and known
algorithm family labels; never IDs, key IDs, MI values, raw payloads or raw RF logs.
Unknown slot stays unknown. Duplicated probes aggregate with max, not addition.
These are parsed log observations, not BER, verified packet counts or speech truth.
Other formats retain protocol/error counters; detailed burst parsing is DMR-only.

Save schema-versioned worker evidence in attempts and digital journal metadata.
No-PCM typed crypto evidence can be displayed as an indication without choosing a
worker or displacing analog VAD. Service-only observations do not teach a frequency,
blacklist it or change recording permissions. Display candidate-scoped errors and
DMR packet counts in all UI languages; legacy unrelated error summaries are hidden.

Validation: synthetic upstream-shaped PI positive/negative/stale/context/slot tests,
no-PCM diagnostics, delayed PCM veto and UI regressions. Repeat existing public IQ
references and full checks; results recorded separately. This does not establish that
historical calls were encrypted. Existing recordings and
exact-PCM deduplication remain untouched. Public source ZIP from the prior distribution increment remains a
previous snapshot until the next explicit export.
