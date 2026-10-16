# Security and privacy

RadioMind currently has **no authentication**. It binds to `127.0.0.1`; browser
same-origin checks are not a substitute for authentication. Do not expose the
port through a public reverse proxy, public bind or router forwarding. For remote
use, keep the service on loopback and use a private SSH tunnel as documented in
the guides. Local users and programs on the host can access the archive.

Recordings, SQLite metadata, frequency names and selected devices are private
operator data. Keep `data/`, `runtime/`, local profiles and backups out of Git.
Application capture does not upload audio or contact a cloud inference service.
Explicit setup/install commands download public dependencies and models.

If you find a vulnerability, use the repository's private vulnerability reporting
channel when the maintainer enables it. Until that channel exists, do not publish
sensitive evidence in a public issue. A public issue may request a private contact
without including exploit details, logs or recordings. No reporting email or SLA
is established yet. Only the current development source is maintained.

The release checker detects common secret patterns and private paths, not every
possible secret. Manual review of the source snapshot is still required before
publication. Native decoders remain experimental and process untrusted input in
bounded subprocesses. Unknown or encrypted signals are not decoded via bypass.
