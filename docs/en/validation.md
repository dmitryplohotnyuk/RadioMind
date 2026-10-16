# Validation record

Publication checks: 2026-10-16, Windows x64, CPython 3.13.1.

| Check | Actual result |
|---|---|
| Working-tree unit/API/regression suite | 298 passed, 0 skipped, 58.78 s |
| Fresh source-copy suite, no optional models/native assets/media | 287 passed, 11 skipped, 38.92 s; existing locked venv, imports from exported backend |
| Ruff lint / format | Passed; 59 backend files |
| mypy | Passed, 33 application modules |
| Frontend checks | Passed: 283 localization keys, grouping/player, connection and live audio |
| Fresh Windows installation (2026-10-15) | New venv from both lock files, editable backend, pip check passed; not repeated on 2026-10-16 |
| Isolated mock HTTP service | Frontend and running mock status passed in working tree and fresh copy |
| PowerShell / POSIX shell scripts | Parser / bash syntax checks passed; shell syntax is not Linux execution |
| Public source review | 143 files: allowlist, Git candidates, private-path/secret patterns and local document links passed |
| Linux x64 / CPython 3.12 packages | All pinned wheels resolved and downloaded; not executed |
| GitHub CI | Windows/Linux Python 3.11–3.13 recipes prepared; not run on GitHub yet |

The clean-copy check exposed a missing runtime directory on a fresh checkout;
the check runner now creates it before pytest. The complete rerun passed.
Windows double-click launch was also checked for missing profiles, occupied ports,
concurrent clicks, paths with spaces and preserving an already paused service.

The 11 clean-copy skips concern absent optional model/native/synthetic speech
assets, not successful acceptance of those features. One upstream Starlette/AnyIO
BlockingPortal deprecation warning remains in both suites.

No installed Linux guest was available. Linux USB throughput, native Linux cleanup,
VM/container deployment and Raspberry Pi are not accepted. Pi is deferred by scope.
Hardware acquisition was not restarted or retuned for these checks. Native digital
reference tests are separate from generic CI; no new clear-voice acceptance is claimed.

The export contains source files plus SOURCE_MANIFEST.json. The ZIP has a separate
SHA-256 file; no RF audio/IQ, databases, local profiles, native binaries or models
are distributed. Pattern scanning is supplemented by an explicit allowlist, but
cannot guarantee detection of every possible secret.
