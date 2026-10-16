# Architecture and format status

RadioMind consists of one Python/FastAPI service and a static browser UI. Native
libhackrf has a single owner. Continuous 8 MS/s IQ enters bounded buffers; scanning
selects a candidate and holds that frequency while a conversation is captured.
The scanner resumes after the hold finishes. One receiver cannot hear frequencies
outside its current window, and pre-roll cannot recover RF received before tuning.

Analog NFM uses channelization, carrier squelch and local speech detection. A
CTCSS subtone does not require a matching code to hear audio; DCS field acceptance
is still pending. Pre-roll preserves buffered onset, and hang time retains pauses.
Long captures can be split at the configured duration limit. Loss/overflow is
reported; a synthetic fixture never establishes USB or antenna performance.

SQLite holds metadata and receiver preferences; WAV files hold audio. Recordings
are grouped by exact frequency. Source data is separate from program files.
Cleanup writes a separate copy; live browser monitoring has independent bounded
queues and may drop stale audio without blocking archive writes. Digital live
monitoring is not implemented. ASR/transcription is not included.

Optional DSD-neo receives channelized IQ or discriminator samples in a separate
local process. Discovery can run fixed probes alongside AUTO, then keeps one
selected decoder. Confirmation, PCM, protocol identity and intelligible speech
are distinct evidence. Encryption indications veto publication; there is no
decryption/key/bypass interface. Trunk following is not implemented.

DMR selection requires repeated call evidence in AUTO, fixed and probe modes;
nonzero PCM alone is insufficient. Supported, checksum-gated privacy headers
produce an encryption indication, not a claim about every unclear recording.
Conservatively matched native slot mirrors are folded for new journals; distinct
tracks and existing archives are preserved. Short or damaged calls lacking headers
can remain unconfirmed. See the [privacy evidence decision](../decisions/0002-digital-privacy-evidence.md)
and [call selection decision](../decisions/0003-dmr-call-selection-and-output-mirrors.md).

| Format | Integration and evidence |
|---|---|
| Analog NFM | Implemented; existing Windows field use and synthetic squelch/pre-roll tests |
| DMR | AUTO/fixed probe, two-slot archive, public recorded reference regression; live clear-voice acceptance pending |
| M17, NXDN48/96, D-STAR, YSF, P25-I C4FM/CQPSK | Native synthetic pipeline-to-archive checks; live voice acceptance pending |
| dPMR | Signaling and filler PCM evidence; intelligible speech not validated |
| P25-II | Short fixture discovery; control/signaling only, no accepted voice decoding |
| TETRA TMO downlink | Optional experimental worker; no complete clear-voice acceptance |
| TETRA DMO/uplink, trunk following | Not implemented |

Source layout:

```text
backend/radiomind/       capture, DSP, API, archive, adapters
backend/tests/          unit/integration tests and synthetic configuration
frontend/               static UI, RU/UK/EN catalogs
config/example.yaml     safe mock default
scripts/                setup, checks, explicit optional installers, export
docs/en, docs/ru, docs/uk/ installation and user documentation
docs/decisions/         public architectural decisions
samples/                provenance only, no captured media
data/, runtime/, tools/ local state/assets; ignored and never exported
```

See the [source distribution decision](../decisions/0001-source-distribution.md)
and [component inventory](../DEPENDENCIES.md). A future Proxmox deployment should
use a Linux VM with exclusive USB access and persistent data storage. This is an
architectural direction, not a tested VM/container deliverable.
