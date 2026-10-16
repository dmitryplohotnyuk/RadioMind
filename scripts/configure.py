"""Create a private RX profile without accessing hardware or changing an archive."""

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from radiomind.config import AudioSettings, DigitalSettings, ScanRange, Settings, Window
from radiomind.receiver_settings import ReceiverPreferences, apply_preferences


def band(value: str) -> ScanRange:
    try:
        low, high = value.split(":")
        return ScanRange(
            start_hz=int(Decimal(low) * 1_000_000),
            end_hz=int(Decimal(high) * 1_000_000),
        )
    except (ValueError, InvalidOperation, OverflowError) as error:
        raise argparse.ArgumentTypeError(
            "Use START:END in MHz, e.g. 144:146"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", required=True)
    parser.add_argument(
        "--basis", required=True, help="Your authorization basis for reception"
    )
    parser.add_argument(
        "--range", dest="ranges", action="append", type=band, required=True
    )
    parser.add_argument("--record-audio", action="store_true")
    parser.add_argument("--digital", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("config/local.yaml"))
    args = parser.parse_args()
    if not args.country.strip() or not args.basis.strip():
        parser.error("Country and authorization basis must not be blank")
    if args.digital and not args.record_audio:
        parser.error("--digital requires --record-audio")
    template = Window(
        name="template",
        start_hz=100_000_000,
        end_hz=108_000_000,
        dwell_ms=300,
        allowed_actions=(
            ["observe", "demodulate", "record_audio"]
            if args.record_audio
            else ["observe"]
        ),
    )
    base = Settings(
        source="hackrf",
        country=args.country,
        legal_basis=args.basis,
        allow_custom_ranges=True,
        windows=[template],
        scan_period_ms=50,
        metadata_full_policy="drop_new",
        max_metadata_rows=1_000_000,
        audio=AudioSettings(enabled=args.record_audio, vad_engine="silero"),
        digital=DigitalSettings(
            enabled=args.digital,
            input_mode="iq",
            dmr_probe_enabled=args.digital,
            dstar_probe_enabled=args.digital,
            p25p2_probe_enabled=args.digital,
        ),
    )
    settings = apply_preferences(base, ReceiverPreferences(ranges=args.ranges))
    if args.output.exists():
        parser.error(
            "Output already exists; choose another --output or edit it explicitly"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        yaml.safe_dump(settings.model_dump(mode="json"), stream, sort_keys=False)
    print(
        f"Created {args.output}. No RX started. Review the profile before --approve-rx."
    )


if __name__ == "__main__":
    main()
