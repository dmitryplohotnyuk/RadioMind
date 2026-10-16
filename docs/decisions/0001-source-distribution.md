# Decision: source checkout distribution

Date: 2026-10-15. Status: accepted for publication preparation.

Distribute RadioMind's original source under GPL-3.0-only, preserving explicit
GPL-3.0-or-later bridge notices. Keep external decoder/model/runtime licenses
separate. Do not bundle third-party binaries or RF reference media.

The supported installation shape is a complete source checkout plus an editable
Python installation. Frontend/config/native-asset paths are relative to that tree;
a standalone Python wheel is not a complete application. Setup uses pinned
Python/runtime/build packages. OS drivers and Linux libhackrf are system-managed
and their exact installed version must be recorded for hardware validation.

Maintain private operator configuration, archives and engineering history locally.
Build public snapshots from an explicit source allowlist and verify Git candidates,
internal documentation links, common secret patterns and source hashes. Refuse to
overwrite release directories. Public tests use independent synthetic profiles.

Windows x64 has existing hardware evidence. Linux x64 receives installation/CI
recipes, with execution evidence recorded separately. Raspberry Pi is deferred.
Optional RNNoise cleanup stays Windows-only until a Linux binary and audio path
have been tested. No claim of digital clear-voice acceptance across all formats.

Retain one RX owner, bounded IPC and filesystem-backed local state, allowing a
future Linux VM deployment. No Docker image, LXC deployment or privileged USB
container is introduced in this increment. Loopback plus SSH tunneling is the
remote-access path until authentication is implemented.
