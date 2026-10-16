# Decision: reviewed demo screenshots in source exports

Date: 2026-10-16.

Documentation shows the real browser UI backed by `scripts/demo.py`: a fresh
temporary mock archive, invented metadata and locally generated silent WAV files.
The demo never opens a receiver or reads an existing archive. Only the browser
JPEG screenshots are committed, not the temporary database or WAV files.

English screenshots are shared by the three documentation translations and labelled
as illustrative. They do not establish reception, decoding or audio quality.
The source export permits two exact image paths with reviewed SHA-256 hashes.
It copies those images byte-for-byte and includes their hashes in the manifest;
the text-secret and link checks still apply to every source document. Other binary
files remain outside the source allowlist. Updating an image requires visual review
and updating its explicit hash; a checksum alone cannot detect sensitive pixels.

Recreate after installing the project: run `python scripts/demo.py`, open
http://127.0.0.1:8766/, select English, expand the first frequency group, and capture
the archive and Settings pages. Stop with Ctrl+C. Each run uses a fresh temporary
directory below runtime; the demo cannot select the operator's data directory.
