# Python dependency licenses

Versions are pinned in requirements.lock. This inventory is package metadata, not a redistribution legal audit. Native libraries are listed in NATIVE_PACKAGES.json. RadioMind code is GPL-3.0-only, except files explicitly marked GPL-3.0-or-later. Upstream components retain their own licenses. See [third-party notices](../THIRD_PARTY.md).

| Package | Version | Declared license |
|---|---|---|
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD License |
| fastapi | 0.115.12 | MIT License |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| mypy | 1.15.0 | MIT |
| mypy_extensions | 1.1.0 | MIT |
| numpy | 2.2.5 | Copyright (c) 2005-2024, NumPy Developers. |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pluggy | 1.6.0 | MIT |
| psutil | 7.0.0 | BSD-3-Clause |
| pydantic | 2.11.4 | MIT |
| pydantic_core | 2.33.2 | MIT |
| pytest | 8.3.5 | MIT |
| PyYAML | 6.0.2 | MIT |
| ruff | 0.11.8 | MIT |
| starlette | 0.46.2 | BSD-3-Clause |
| types-psutil | 7.0.0.20250401 | Apache-2.0 |
| types-PyYAML | 6.0.12.20250402 | Apache-2.0 |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| uvicorn | 0.34.2 | BSD-3-Clause |
| websockets | 15.0.1 | BSD-3-Clause |
| zstandard | 0.23.0 | BSD |
| scipy | 1.15.3 | BSD-3-Clause; bundled numerical-library notices included in wheel |
| webrtcvad-wheels | 2.0.14 | MIT wrapper; bundled WebRTC code BSD-style notices |
| onnxruntime | 1.23.2 | MIT; CPU provider only, telemetry disabled |
| coloredlogs | 15.0.1 | MIT |
| flatbuffers | 25.12.19 | Apache-2.0 |
| protobuf | 7.36.2 | BSD-3-Clause |
| sympy | 1.14.0 | BSD |
| humanfriendly | 10.0 | MIT |
| mpmath | 1.3.0 | BSD |
| pyreadline3 | 3.5.6 | BSD; Windows only |

Silero VAD v6.2 model: MIT, official source
https://github.com/snakers4/silero-vad/tree/v6.2 . The model is downloaded explicitly
by scripts/install_silero.py, never automatically during reception. SHA-256:
`1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3`.
Size 2,327,524 bytes; local tools/silero-vad/LICENSE accompanies the asset. No
PyTorch/torchaudio or ASR dependency. The NumPy wrapper follows the published
512-sample + 64-context/state model interface without importing upstream I/O code.

Optional RNNoise cleanup: native RNNoise v0.2, BSD-3-Clause (tools/rnnoise/COPYING),
distributed in PyRNNoise 0.4.5 Windows x64 wheel. Wrapper Apache-2.0 notice retained
as tools/rnnoise/WRAPPER-LICENSE; wrapper and its Python dependencies not installed.
Installer: scripts/install_rnnoise.py, only public assets downloaded, no RF uploads.
Sources: https://github.com/xiph/rnnoise/tree/v0.2 and
https://pypi.org/project/pyrnnoise/0.4.5/ .
Wheel SHA-256: `f46015e5a58212d2883bf8e5a2cafb3c6b115176d8039f8340132cb24866b7da`.
DLL SHA-256: `06770aeb8855ef942b5dcdb436f84dfdd5867b716ba4b4c8a2c66ade03197f31`.
The runtime verifies the DLL hash before use. Linux cleanup is not enabled; original
archive playback and capture remain available with the documented Linux setup.


Digital decoder: DSD-neo v2.10.0 (binary reports ff5843f), separate process, GPL-3.0
project license plus per-file notices (ISC and upstream-derived components).
Installer: scripts/install_digital.py; Windows archive SHA-256
`4cc5e752e17ca659fc615f5b5441e82e81e5cb361e2ce4d8b857fa90863fee66`; Linux x86_64
AppImage `492f0980c8d0891dd18e4283c745eefc2d7aaadeeb68cae4a31cc70e57dc0fdf`.
Windows executable SHA-256 `f3217e79a8a403f303e2330e8c7f737e1f24b779b38e7aff808de7622ac64428`.
Installer retains upstream LICENSE, COPYRIGHT, THIRD_PARTY.md and bundled library
notices under tools/digital/dsd-neo/share/doc/dsd-neo. Runtime verifies the installed
manifest before RX. Windows binary reports MBElib-neo 2.1.0; Codec2 is bundled.
Do not infer all component licenses from the project's top-level GPL label: upstream
THIRD_PARTY notes an EDACS BCH non-commercial/commercial-permission notice and
unclear public RF-fixture rights. No binaries/fixtures are added to source commits
or redistributed here. Exact source and redistribution review are prerequisites
to packaging a public distribution. Primary release:
https://github.com/arancormonk/dsd-neo/releases/tag/v2.10.0 .

Optional TETRA native receiver (no new Python packages):

- tetra-kit-timeslots revision `2205072976e18b6fb15b975e734afad2477863ac`, source ZIP
  SHA-256 `8cd1fdcb76bbaf2face60be00d074e224959ccb7a197f14c52285853d3ddc81b`.
  https://github.com/adryd325/tetra-kit-timeslots/tree/2205072976e18b6fb15b975e734afad2477863ac
- Project GPL-3.0, MAC files GPL-3.0-or-later; Viterbi component Apache-2.0 and base64
  MIT notices remain in the pinned source. ETSI reference speech/channel codec
  files carry reference notices without a separate explicit file license grant;
  do not infer redistribution clearance from the repository umbrella license.
  Local-only build; no bundled source/binaries/fixtures committed or published.
- RapidJSON 1.1.0 revision `f54b0e47a08782a6131cc3d60f94d038fa6e0a51`, MIT and
  component notices in license.txt. ZIP SHA-256
  `00b9094db76b70eee42145c0be434a10369eb1c7e3f846093a45a8a8ee0a0b6e`.
- `scripts/install_tetra.py` verifies archives and existing source files, builds
  only decoder sources with MSVC x64 /MT on Windows or cc/c++ on Linux, and retains
  notices/source/build logs. No zlib, GNU Radio or native network service required.
  Bridge sources under scripts/native/tetra are GPL-3.0-or-later.
- Windows build executed with Visual Studio 2022 C++ tools. Linux build recipe is
  supplied but untested. Installer refuses to overwrite an existing installation.
  Runtime verifies executable and four codec libraries against the local manifest.
  Current executable SHA-256
  `ac174ab80a3f6f9967dc3f9389f7a6beb18306101660571665ee2b2c4fa2971d`;
  codec DLL `93563575e66fd635d50a4e149a0a0d2f395c9bf8643839dc243b219139fb8bb9`.

Install TETRA explicitly with `python scripts/install_tetra.py` using the project venv.
It is experimental and excluded from default installation. A native compiler is
required; Linux build and intelligible TETRA voice remain unaccepted.

Build tooling: pip 25.1.1 (MIT), setuptools 80.9.0 (MIT), wheel 0.45.1 (MIT), pinned
in requirements-build.lock. Node.js 22 is used for development checks only; no
JavaScript runtime dependency, CDN or npm installation is needed for the UI.

Development CI uses official actions/checkout, actions/setup-python and
actions/setup-node (MIT); exact upstream commits are pinned in the workflow.
