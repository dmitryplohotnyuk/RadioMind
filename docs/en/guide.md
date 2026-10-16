# Installation and use

[English](guide.md) · [Українська](../uk/guide.md) · [Русский](../ru/guide.md)

## Requirements and support

Use a complete source checkout, CPython 3.11–3.13 **64-bit**, a modern browser and
local disk space for the archive. Windows 10/11 x64 is the primary tested target;
Linux x64 setup targets Ubuntu 24.04 / Debian 12 or newer with a supported Python.
Raspberry Pi is deferred. Linux hardware throughput is not yet accepted. The
capture path uses 8 MS/s; no lower-rate Pi performance claim is made.

Run one RadioMind instance per receiver and archive. Close other SDR applications
before starting physical RX. Start with the mock demo; it never opens USB or
records real audio. Setup downloads dependencies, but capture does not upload RF
or use cloud speech services. Node.js 22 is only required for development checks.

## Windows

After installing and configuring the receiver, double-click **Start RadioMind.cmd**
in the project root. It starts the server in the background and opens the browser.
It uses `config/local.yaml`, falling back to the existing private
`config/hackrf-recorder.yaml`. Repeated clicks open the running instance without
changing its stopped/running receiver state. Closing the browser does not stop RX;
use the stop button in the interface. Startup errors remain visible in the launch
window; detailed logs are in `runtime/windows-launch-*.log`. You may create a desktop
shortcut to the CMD file; keep the file itself beside the project's `scripts` folder.

Install Python x64 and make `python` available in PowerShell. Open the source root:

```powershell
powershell -File scripts/windows/setup.ps1
powershell -File scripts/windows/start.ps1
```

Open http://127.0.0.1:8765/. Stop with Ctrl+C. Setup creates `.venv`, installs exact
locked dependencies and the editable backend; it does not install USB drivers or
start reception. Keep the entire source tree in place.

For physical analog reception, install the model and native userspace library:

```powershell
powershell -File scripts/windows/setup.ps1 -Models -HackRF
```

Use a compatible HackRF USB driver. Follow the
[official HackRF software guide](https://hackrf.readthedocs.io/en/latest/installing_hackrf_software.html)
for driver/library setup; these scripts do not flash firmware. Optional separate
actions: `setup.ps1 -Cleanup` installs RNNoise and `setup.ps1 -Digital` installs
DSD-neo. Read [third-party notices](../../THIRD_PARTY.md) first.

If PowerShell policy blocks scripts, use `python scripts/bootstrap.py` and
`.venv/Scripts/python.exe -m radiomind` for the demo without changing system policy.
Optional installers can also be run directly with the venv Python.

## Linux x64

On Ubuntu 24.04 / Debian 12, install system prerequisites:

```sh
sudo apt update
sudo apt install python3 python3-venv libhackrf0 hackrf
sh scripts/linux/setup.sh
sh scripts/linux/start.sh
```

If the default Python is outside 3.11–3.13, select an installed compatible version:
`PYTHON=python3.12 sh scripts/linux/setup.sh`. Use a venv; do not use system-wide
`sudo pip`. Install the speech model with `sh scripts/linux/setup.sh --models`.
For optional digital decoding add `--digital`; the pinned x64 AppImage is extracted
locally and does not require FUSE. RNNoise cleaned copies are Windows-only for now;
Linux retains capture and original audio playback.

The system HackRF package supplies USB rules. Reconnect the device after installing
rules and verify access as an ordinary user; do not run the web app as root.
System libhackrf/driver versions vary by distribution and are not pinned by pip.
Record `dpkg-query -W libhackrf0` with hardware test results.

## Configure reception

These examples are syntax examples, **not a grant to monitor a frequency**. Replace
`XX`, the authorization text and the range with your own permitted configuration.
The generator writes an ignored local file, refuses overwrite and does not start
RX. Each additional range uses another `--range START:END` argument in MHz.

Windows:

```powershell
.venv/Scripts/python.exe scripts/configure.py --country XX --basis "My RX authorization" --range 144:146 --record-audio
.venv/Scripts/python.exe scripts/doctor.py --config config/local.yaml --hackrf-library tools/hackrf/Library/bin/hackrf-0.dll
powershell -File scripts/windows/start.ps1 -Config config/local.yaml -ApproveRx
```

Linux:

```sh
.venv/bin/python scripts/configure.py --country XX --basis "My RX authorization" --range 144:146 --record-audio
RADIO_LIBRARY=$(dpkg -L libhackrf0 | sed -n '/\/libhackrf\.so\.0$/p' | head -n 1)
test -f "$RADIO_LIBRARY"
.venv/bin/python scripts/doctor.py --config config/local.yaml --hackrf-library "$RADIO_LIBRARY"
sh scripts/linux/start.sh --config config/local.yaml --approve-rx --hackrf-library "$RADIO_LIBRARY"
```

For a different distribution pass its absolute `.so` path. `doctor.py` checks
configuration/assets without opening hardware; a success is not a USB/RF test.
Add `--digital` when generating a profile only after installing DSD-neo. Existing
profiles can be edited while the app is stopped; `digital.enabled=true` needs audio
permissions. The generated profile enables IQ input and DMR/D-STAR/P25-II probes.
TETRA is a separate experimental opt-in, excluded from normal setup; see
[architecture and format status](architecture.md).

The UI saves selected USB device, gain and scan ranges in SQLite. Saved preferences
override the launch profile on subsequent runs; inspect **Settings** after editing
YAML. Range changes take effect at a conversation boundary. All ranges disabled
means reception stops. Start only with the intended ranges and permissions.

## Daily use

- **Recordings:** expand a frequency group and play a recording. Rename groups and
  recordings from their menus; mark favorite frequencies and add unwanted channels
  to the blacklist. Deleting a group deletes its recordings after confirmation.
- **Settings:** select an individual USB HackRF or automatic discovery; add, edit,
  enable or disable ranges. Save applies changes; Cancel discards the draft.
- **Listen live:** opt in to analog audio during capture. Pre-roll introduces some
  delay. Browser playback has its own queue and does not control archive recording.
- **Cleaned copy:** optional Windows RNNoise processing keeps the original. Switch
  between original and cleaned audio; improvement depends on the recording.
- **Reception level:** dB above the detector's estimated noise floor at acquisition,
  not calibrated dBm, a guaranteed SNR or a speech-quality score.
- **Diagnostics:** inspect reception errors, buffer loss and decoder attempts.
  An unknown format or a sync hint does not establish encryption or intelligibility.

Capture pauses scanning while it holds a conversation. Other frequencies can be
missed during the hold. The generator uses a 180-second recording segment limit
and a 1024 MB archive quota; review `audio` settings for longer operation. Archive
quota exhaustion stops new capture rather than silently deleting old recordings.
Text transcription, trunk following and encryption bypass are absent.

DMR needs repeated call evidence before decoded audio is accepted. Supported
privacy headers produce an encryption indication; unclear audio alone does not.
New captures fold conservatively matched duplicate slot output, preserving distinct
tracks. Short calls without sufficient headers may remain unconfirmed. These
checks do not establish intelligibility and never modify existing recordings.

## Storage, updates and remote use

`data/` stores SQLite and audio, `runtime/` diagnostics, `tools/` optional assets,
and `config/local.yaml` the initial profile. They are excluded from source export.
Use `--data-dir PATH` (Windows wrapper: `-DataDir PATH`) for persistent storage.
Keep enough disk space and back up the whole data directory while the service is
stopped. Do not copy only the SQLite main file while WAL writes are in progress.

Before an update, stop RX cleanly, back up data/config, replace source and rerun
setup. Keep dependencies and assets with the matching source version. There is no
automatic schema rollback guarantee. Never run two writers on the same archive.

The UI has no login and binds only to localhost. For a future Linux VM / Proxmox
host, pass the receiver exclusively to the guest and keep data on persistent
storage. VM/container USB throughput is not validated; no container image or LXC
recipe is supplied in this release. From your workstation use:

```sh
ssh -N -L 8765:127.0.0.1:8765 user@your-server
```

Then open the same local URL. Do not publicly expose this unauthenticated service.

## Troubleshooting and validation

No page: inspect the launch terminal; confirm port 8765 and use another port for a
second **mock** instance. No device: check the USB cable/driver/permissions and
exclusive ownership. For VM/WSL see
[HackRF troubleshooting](https://hackrf.readthedocs.io/en/stable/troubleshooting.html).
Overflows: record counters, reduce competing CPU/disk load and USB contention;
do not hide missing samples. Avoid heavy native benchmarks while collecting.

Missing model/decoder: run the explicit installer, then `doctor.py`. No recordings:
check enabled ranges, recording permissions, signal level, blacklist and quota.
Digital PCM or a detected sync alone does not prove clear voice. Report format
problems with synthetic or redistribution-authorized references, not private RF.

Run `python scripts/check.py` using the venv for lint, formatting, type, unit/API,
frontend and source-publication checks. Hardware and optional native references
are separate checks. See [validation evidence](validation.md) and
[contribution instructions](../../CONTRIBUTING.md).
