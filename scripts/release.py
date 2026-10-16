"""Build a source-only public snapshot. Never copy runtime data or native assets."""

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".gitignore",
    ".gitattributes",
    ".env.example",
    "LICENSE",
    "NOTICE",
    "README.md",
    "README.ru.md",
    "README.uk.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "THIRD_PARTY.md",
    "requirements.lock",
    "requirements-build.lock",
    "Start RadioMind.cmd",
}
EXACT = {
    "config/example.yaml",
    "backend/pyproject.toml",
    "docs/DEPENDENCIES.md",
    "docs/NATIVE_PACKAGES.json",
    "samples/README.md",
    "samples/public-dmr-references.json",
}
TREES = {
    "backend/radiomind": {".py"},
    "backend/tests": {".py", ".yaml"},
    "frontend": {".js", ".html", ".css", ".svg"},
    "scripts": {".py", ".cjs", ".ps1", ".sh", ".cpp", ".c", ".h"},
    "docs/en": {".md"},
    "docs/ru": {".md"},
    "docs/uk": {".md"},
    "docs/decisions": {".md"},
    "docs/assets": {".svg"},
    ".github": {".md", ".yml", ".yaml"},
}
EXCLUDED = {"scripts/compare_owner_vad.py", "scripts/audit_archive_quality.py"}
SENSITIVE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|"
    r"[A-Z]:[\\/]Users[\\/][^\s\\/]+|[A-Z]:[\\/]Workspace[\\/]",
    re.I,
)


def candidates(root: Path) -> list[Path]:
    paths = {root / name for name in ROOT_FILES | EXACT}
    for tree, extensions in TREES.items():
        paths.update(p for p in (root / tree).rglob("*") if p.suffix in extensions)
    result = []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        if relative in EXCLUDED:
            continue
        if (
            not path.is_file()
            or path.is_symlink()
            or not path.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError(f"Missing or unsafe source: {relative}")
        result.append(path)
    return result


def validate(root: Path, paths: list[Path]) -> None:
    public = {p.resolve() for p in paths}
    for path in paths:
        content = path.read_text(encoding="utf-8-sig")
        if "\x00" in content or SENSITIVE.search(content):
            raise ValueError(
                f"Review sensitive/binary content in {path.relative_to(root)}"
            )
        if path.suffix == ".md":
            for link in re.findall(r"\]\(([^)]+)\)", content):
                link = unquote(link.split("#", 1)[0])
                if not link or re.match(r"[a-z]+:", link):
                    continue
                if (path.parent / link).resolve() not in public:
                    raise ValueError(
                        f"Unpublished/broken link: {path.relative_to(root)} -> {link}"
                    )
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
        )
        extras = (
            {name for name in result.stdout.decode().split("\0") if name}
            - {p.relative_to(root).as_posix() for p in paths}
            - {"SOURCE_MANIFEST.json"}
        )
        if extras:
            raise ValueError(
                "Git candidates outside public allowlist: " + ", ".join(sorted(extras))
            )


def export(root: Path, destination: Path) -> dict[str, str]:
    paths = candidates(root)
    validate(root, paths)
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for source in paths:
        name = source.relative_to(root).as_posix()
        # Normalize source text for reproducible Windows/Linux checkout contents.
        data = source.read_text(encoding="utf-8-sig").replace("\r\n", "\n").encode()
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = hashlib.sha256(data).hexdigest()
    (destination / "SOURCE_MANIFEST.json").write_text(
        json.dumps({"algorithm": "sha256", "files": manifest}, indent=2) + "\n",
        encoding="utf-8",
    )
    archive_path = destination.with_suffix(".zip")
    with zipfile.ZipFile(
        archive_path, "x", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(
                    destination.name + "/" + path.relative_to(destination).as_posix()
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix(".zip.sha256").write_text(
        f"{digest}  {archive_path.name}\n", encoding="ascii"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="New directory below dist/ (never overwrite)"
    )
    args = parser.parse_args()
    paths = candidates(ROOT)
    validate(ROOT, paths)
    if args.output:
        destination = args.output.resolve()
        if (
            not destination.is_relative_to((ROOT / "dist").resolve())
            or destination == ROOT / "dist"
        ):
            parser.error("Output must be a new directory inside dist/")
        if destination.with_suffix(".zip").exists():
            parser.error("Archive already exists; choose a new output name")
        export(ROOT, destination)
        print(
            f"Exported {len(paths)} source files to {destination}; ZIP and SHA-256 alongside"
        )
    else:
        print(
            f"Public source checks passed: {len(paths)} files; local links and Git candidates checked"
        )


if __name__ == "__main__":
    main()
