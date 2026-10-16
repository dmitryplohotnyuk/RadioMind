# Third-party notices

The GPL-3.0-only grant in [LICENSE](LICENSE) covers RadioMind's original code.
It does not relicense dependencies. This is a **source-only** distribution: no
native executables, DLLs, models, captured RF, downloaded reference recordings or
third-party source archives are bundled.

Exact Python versions are in [requirements.lock](requirements.lock); build tools
are in [requirements-build.lock](requirements-build.lock). The component license
inventory and native source/hash references are in
[docs/DEPENDENCIES.md](docs/DEPENDENCIES.md). Package license files remain with the
installed packages. The inventory is not a replacement for those notices.

Optional downloads are explicit installer actions, not reception-time downloads:

| Component | Use | Upstream licensing / packaging status |
|---|---|---|
| libhackrf / libusb | USB receive | GPL-2.0-or-later / LGPL-2.1-or-later; separate native installation |
| Silero VAD v6.2 | Local speech detection | MIT; model and license downloaded explicitly |
| RNNoise v0.2 | Cleaned archive copy on Windows x64 | BSD-3-Clause; PyRNNoise wheel wrapper Apache-2.0 |
| DSD-neo v2.10.0 | Optional digital decoder subprocess | GPL-3.0 umbrella plus component notices; upstream THIRD_PARTY notes EDACS BCH non-commercial/commercial-permission terms. No redistribution clearance is claimed for the binary bundle |
| tetra-kit-timeslots | Experimental TMO worker | GPL-3.0 umbrella with per-file licenses; ETSI reference-codec redistribution rights need review before packaging |
| RapidJSON 1.1.0 | Optional TETRA build | MIT and component notices |
| Microsoft runtime | Windows native dependencies | Proprietary upstream terms; installer downloads, source release does not bundle it |

Read upstream notices before enabling or redistributing optional components.
The experimental TETRA adapter sources written for RadioMind are explicitly
GPL-3.0-or-later. Native decoder source/binary redistribution is outside this
release. Reference provenance files contain URLs and hashes only; a public URL
does not imply permission to redistribute the recording.
