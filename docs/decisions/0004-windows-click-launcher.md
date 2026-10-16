# Windows double-click launcher

`Start RadioMind.cmd` calls the companion PowerShell launcher with process-scoped
execution-policy bypass. No machine policy, startup registration or dependency
installation is changed. It locates the repository relative to itself and uses
its existing `.venv`. Profile selection is `config/local.yaml`, then the legacy
private `config/hackrf-recorder.yaml`; absence is an error, not a demo fallback.
Launching a hardware profile explicitly starts authorized RX with its existing
recording permissions. Nothing in the profile is rewritten.

The launcher serializes clicks using a Windows per-port mutex, checks the local
RadioMind status and HTML title, and reuses a running instance without changing
its paused/running state. An unknown occupied port fails without starting another
receiver. New servers run hidden with separate timestamped stdout/stderr logs in
runtime; browser opening waits for readiness with a bounded timeout. Closing the
browser or launcher does not terminate reception. The UI stop button stops RX.

The existing foreground `scripts/windows/start.ps1` remains available for terminal
use. The new launcher supports explicit config/data directory/port, paused startup
and browser suppression for isolated mock checks. A server error leaves a readable
message in the CMD window; logs and configuration remain on the local computer.
