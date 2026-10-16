# Contributing

Read the [English](docs/en/guide.md), [Russian](docs/ru/guide.md) or
[Ukrainian](docs/uk/guide.md) guide and [architecture](docs/en/architecture.md).
Use Python 3.11–3.13 x64 and Node.js 22. Install from the lock files via the setup
script. Work on mock/synthetic inputs first; no hardware is needed for CI.

Run `.venv/Scripts/python.exe scripts/check.py` on Windows or
`.venv/bin/python scripts/check.py` on Linux. Optional model/native/media tests
may skip on a clean checkout; report skips and do not present them as passes.
Native reference tests and hardware tests are separate acceptance levels.

Keep PRs focused. Describe the problem, changed behavior, checks actually run and
remaining limitations. Update the changelog and all three guides when behavior or
installation changes. Add an architectural decision for changes to capture,
storage, dependencies or deployment. Keep UI text in all three catalogs; use the
existing localization checker. Never block capture on playback, cleanup or UI.

RadioMind is RX-only. Do not add transmission, flashing, key recovery or encryption
bypass. Do not attach real RF audio/IQ, user archives, USB serials, credentials,
private profiles or unsanitized logs to issues, PRs or CI. Synthetic tests must
state their provenance; public download links alone do not establish media rights.

New dependencies require exact versions, upstream source, license inventory and
Windows/Linux evidence. Contributions to original code use GPL-3.0-only unless a
file already declares compatible explicit licensing. Preserve third-party notices.

Before preparing a release run `python scripts/release.py`, then
`python scripts/release.py --output dist/RadioMind-source` (choose a fresh name).
Review the exported files and manifest, test installation from that directory,
and publish only the reviewed source. Never copy the development workspace whole.
Git candidates outside the public allowlist fail the release check.
