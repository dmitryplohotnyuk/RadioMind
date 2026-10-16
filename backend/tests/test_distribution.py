"""Public export must not depend on or expose an operator's workspace."""

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from radiomind.config import load_settings
from radiomind.policy import require_audio

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_tools", ROOT / "scripts/release.py")
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def test_export_omits_private_data_and_refuses_overwrite(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in release.ROOT_FILES | release.EXACT:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("public\n", encoding="utf-8")
    for name in release.IMAGES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    for name in (
        "data/private.wav",
        "runtime/private.json",
        "tools/native.dll",
        "config/local.yaml",
        "docs/PROJECT_STATE.md",
        "AGENTS.md",
        "docs/assets/private.jpg",
    ):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private", encoding="utf-8")
    target = tmp_path / "snapshot"
    manifest = release.export(source, target)
    assert set(manifest) == release.ROOT_FILES | release.EXACT | release.IMAGES.keys()
    assert json.loads((target / "SOURCE_MANIFEST.json").read_text())["files"] == manifest
    with zipfile.ZipFile(target.with_suffix(".zip")) as archive:
        assert all("private" not in name for name in archive.namelist())
        for name, digest in release.IMAGES.items():
            assert manifest[name] == digest
            assert (target / name).read_bytes() == (ROOT / name).read_bytes()
            assert archive.read("snapshot/" + name) == (ROOT / name).read_bytes()
    with pytest.raises(FileExistsError):
        release.export(source, target)


def test_changed_demo_screenshot_requires_review(tmp_path):
    name = next(iter(release.IMAGES))
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_bytes((ROOT / name).read_bytes() + b"unreviewed")
    with pytest.raises(ValueError, match="Screenshot changed"):
        release.validate(tmp_path, [path])


@pytest.mark.parametrize(
    "payload", ["-----BEGIN " + "PRIVATE KEY-----", "[private](data/private.md)"]
)
def test_export_rejects_sensitive_content_and_private_links(tmp_path, payload):
    path = tmp_path / "README.md"
    path.write_text(payload)
    with pytest.raises(ValueError):
        release.validate(tmp_path, [path])


def test_generated_profile_permissions_ranges_and_no_overwrite(tmp_path):
    output = tmp_path / "local.yaml"
    command = [
        sys.executable,
        str(ROOT / "scripts/configure.py"),
        "--country",
        "TEST",
        "--basis",
        "synthetic fixture only",
        "--range",
        "144:146",
        "--range",
        "430:440",
        "--record-audio",
        "--digital",
        "--output",
        str(output),
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
    settings = load_settings(output)
    assert settings.audio.enabled and settings.digital.dmr_probe_enabled
    assert len(settings.scan_ranges) == 2
    window = next(w for w in settings.windows if w.start_hz <= 145000000 < w.end_hz)
    require_audio(settings, window, 145000000)
    before = output.read_bytes()
    assert subprocess.run(command, cwd=ROOT, capture_output=True).returncode != 0
    assert output.read_bytes() == before
    invalid = command.copy()
    invalid.remove("--record-audio")
    assert subprocess.run(invalid, cwd=ROOT, capture_output=True).returncode != 0
