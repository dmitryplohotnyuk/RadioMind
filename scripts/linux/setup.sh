#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
"${PYTHON:-python3}" scripts/bootstrap.py
for feature in "$@"; do
    case "$feature" in
        --models) .venv/bin/python scripts/install_silero.py ;;
        --digital) .venv/bin/python scripts/install_digital.py ;;
        *) echo "Unknown option: $feature (use --models or --digital)" >&2; exit 2 ;;
    esac
done
