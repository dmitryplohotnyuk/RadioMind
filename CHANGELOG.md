# Changelog

## Unreleased — public repository preparation

- Refresh English, Ukrainian and Russian entry points and validation evidence.
- Create the test runtime directory on fresh checkouts before passing it to pytest.
- Quote the pip binary-only argument in CI YAML and parse workflow YAML locally.
- Review the source-only allowlist, licenses, pinned Windows/Linux CI and export;
  retain local archives, profiles and engineering history outside public Git.

## Unreleased — Windows click-to-start

- Add `Start RadioMind.cmd`: start the configured receiver in the background and
  open its local web interface, or reuse an already running instance.
- Serialize repeated clicks, reject occupied ports and keep startup logs/errors.

## Unreleased — DMR selection and duplicate output

- Require repeated DMR call evidence in AUTO and forced mode as well as the probe,
  preserving buffered onset and a privacy-minimized selection snapshot.
- Fold narrowly matched single-slot native output mirrors for new journals only;
  preserve distinct/uncertain tracks, legacy recovery and existing archives.
- Add regression checks for both slot directions, sparse residuals, genuine dual
  calls, recovery and publication retries. Header-poor calls may remain unconfirmed.

## Unreleased — digital privacy diagnostics

- Recognize supported CRC/checksum-gated DMR privacy-header log shapes, including
  DMRA RC4/DES/AES and Hytera Enhanced; retain uncertain/corrupt-header handling.
- Persist privacy-minimized DMR voice/data/control/idle counters by worker and slot;
  report crypto-header indications even when the native decoder mutes audio.
- Scope displayed frame errors to candidate protocols and add RU/UK/EN diagnostics.
- Preserve native muting, analog selection, archive contents and exact deduplication.


## 0.7.0 — source preview (unreleased)

- Local RX-only HackRF scanner, continuous 8 MS/s capture, conversation hold,
  pre-roll, carrier squelch and persistent audio archive.
- Frequency groups, names, favorites, blacklist, deletion, device/range settings,
  reception level and independent analog live monitoring.
- Russian, Ukrainian and English UI; optional Windows RNNoise cleaned copies.
- Experimental native digital adapters, protocol evidence, crash recovery and
  confirmed DMR direct-call duplicate folding. No trunk following or encryption bypass.
- Public DMR reference regression improvements for weak input and onset; other
  formats retain the acceptance limits in the architecture document.
- GPL-3.0-only source distribution, dependency notices and public source allowlist.
- English/Russian/Ukrainian setup and user guides; pinned Windows/Linux x64 setup,
  explicit RX profile generator, read-only doctor, isolated mock smoke and CI.
- Separate synthetic test configuration from operator profiles; exclude private
  history, archives, binaries, models and real RF from source exports.
- Raspberry Pi deferred; Linux RNNoise cleanup and Linux hardware validation pending.

See [format status](docs/en/architecture.md) and [validation evidence](docs/en/validation.md).
