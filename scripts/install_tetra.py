"""Build pinned receive-only TETRA worker locally; never accesses an SDR device."""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/digital/source"
REVISION = "2205072976e18b6fb15b975e734afad2477863ac"
RAPID = "f54b0e47a08782a6131cc3d60f94d038fa6e0a51"


def obtain(repo: str, revision: str, digest: str) -> Path:
    data = urllib.request.urlopen(
        f"https://codeload.github.com/{repo}/zip/{revision}", timeout=60
    ).read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError("Source archive checksum mismatch")
    destination = SOURCE / (repo.split("/")[-1] + "-" + revision)
    # Verify every file even when previously extracted; never silently overwrite.
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        for member in bundle.infolist():
            path = (SOURCE / member.filename).resolve()
            if not path.is_relative_to(SOURCE.resolve()):
                raise RuntimeError("Unsafe source archive path")
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                content = bundle.read(member)
                if path.exists() and path.read_bytes() != content:
                    raise RuntimeError(f"Existing source modified: {path}")
                path.write_bytes(content)
    return destination


def compiler_environment() -> dict[str, str]:
    if os.name != "nt":
        return dict(os.environ)
    installer = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    vswhere = installer / "Microsoft Visual Studio/Installer/vswhere.exe"
    location = subprocess.check_output(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        text=True,
    ).strip()
    devcmd = Path(location) / "Common7/Tools/VsDevCmd.bat"
    if not location or not devcmd.is_file():
        raise RuntimeError("MSVC C++ build tools are required")
    script = ROOT / "runtime/tetra-compiler-env.cmd"
    script.parent.mkdir(exist_ok=True)
    script.write_text(f'@echo off\ncall "{devcmd}" -arch=x64 >nul\nset\n')
    output = subprocess.check_output(
        ["cmd", "/d", "/c", str(script)],
        text=True,
        errors="replace",
    )
    return dict(
        line.split("=", 1)
        for line in output.splitlines()
        if "=" in line and not line.startswith("=")
    )


def patch_tree(build: Path) -> None:
    decoder = build / "decoder"
    for path in decoder.rglob("*.h"):
        text = path.read_text()
        text = re.sub(
            r"^#include <(?:unistd.h|netinet/[^>]+|arpa/[^>]+|sys/[^>]+|zlib.h)>\n",
            "",
            text,
            flags=re.M,
        )
        text = text.replace("__attribute__((packed))", "")
        path.write_text(text)
    (decoder / "wiremsg/wiremsg.cc").write_text("""#include "wiremsg.h"
using namespace Tetra;
WireMsg::WireMsg(int) {} WireMsg::~WireMsg() {}
uint8_t WireMsg::tetraChannelToGsmChannel(MacLogicalChannel) { return 0; }
void WireMsg::sendMsg(MacLogicalChannel,TetraTime,Pdu) {}
""")
    for path in decoder.rglob("*.cc"):
        text = path.read_text()
        text = text.replace('printf("* synchronization lost\\n");', "")
        text = re.sub(r"(?<![\w])printf\(", "fprintf(stderr, ", text)
        path.write_text(text)
    log = decoder / "common/log.cc"
    log.write_text(log.read_text().replace("if (level <= m_level)", "if (false)"))
    utils = decoder / "common/utils.cc"
    utils.write_text(
        "#include <iterator>\n"
        + utils.read_text()
        .replace("back_inserter(", "std::back_inserter(")
        .replace(
            "std::ptr_fun<int, int>(std::toupper)",
            "[](unsigned char c) { return std::toupper(c); }",
        )
    )
    header = decoder / "decoder.h"
    header.write_text(
        header.read_text().replace(
            "uint16_t m_rxBitsCounter;", "uint16_t m_rxBitsCounter = 0;"
        )
    )
    report = decoder / "common/report.cc"
    text = '#include "../bridge_api.h"\n' + report.read_text()
    text = re.sub(
        r"void Report::addCompressed\(.*?(?=\n/\*\*)",
        """void Report::addCompressed(std::string field, const unsigned char *data, uint16_t size) {
    unsigned char encoded[2048] = {0};
    if (size > 1380) return;
    Tetra::b64Encode(data,size,encoded);
    add(field, std::string((const char*)encoded));
}
""",
        text,
        flags=re.S,
    )
    text = text.replace(
        "write(m_socketFd, output.c_str(), output.length() * sizeof(char));",
        "rm_report(output.c_str());",
    )
    report.write_text(text)
    mac = decoder / "mac/mac.cc"
    text = '#include "../bridge_api.h"\n' + mac.read_text()
    text = text.replace(
        "m_usageMarkerEncryptionMode[idx] = 0;",
        "m_usageMarkerEncryptionMode[idx] = 255;",
    )
    anchor = "m_tetraCell->updateScramblingCode(mcc, mnc, colorCode);"
    text = text.replace(
        anchor,
        anchor
        + "\n        rm_sync(m_tetraTime.tn,m_tetraTime.fn,m_tetraTime.mn,mcc,mnc,colorCode);",
    )
    mac.write_text(text)
    # Own bridge supplies a bounded stdin interface; original networking main is excluded.
    for name in ("receiver_main.cpp", "bridge_api.h"):
        shutil.copyfile(ROOT / "scripts/native/tetra" / name, decoder / name)
    shutil.copyfile(
        ROOT / "scripts/native/tetra/codec_bridge.c", build / "codec/codec_bridge.c"
    )


def main() -> None:
    output = ROOT / "tools/digital/tetra"
    if output.exists():
        raise RuntimeError(
            "TETRA installation exists; preserve it and review before replacement"
        )
    tetra = obtain(
        "adryd325/tetra-kit-timeslots",
        REVISION,
        "8cd1fdcb76bbaf2face60be00d074e224959ccb7a197f14c52285853d3ddc81b",
    )
    rapid = obtain(
        "Tencent/rapidjson",
        RAPID,
        "00b9094db76b70eee42145c0be434a10369eb1c7e3f846093a45a8a8ee0a0b6e",
    )
    build = ROOT / "tools/digital" / ("tetra-build-" + uuid4().hex)
    shutil.copytree(tetra, build)
    patch_tree(build)
    binary = build / "bin"
    binary.mkdir()
    env = compiler_environment()
    codec = [
        "codec_bridge.c",
        "cdec_tet.c",
        "sub_cd.c",
        "sdec_tet.c",
        "sub_sc_d.c",
        "sub_dsp.c",
        "fbas_tet.c",
        "fexp_tet.c",
        "fmat_tet.c",
        "tetra_op.c",
    ]
    codec = [str(build / "codec" / name) for name in codec]
    sources = [str(p) for p in (build / "decoder").rglob("*.cc") if p.name != "main.cc"]
    sources.append(str(build / "decoder/receiver_main.cpp"))
    if os.name == "nt":
        lib, exe = binary / "codec-1.dll", binary / "tetra-rx.exe"
        commands = [
            [
                "cl",
                "/nologo",
                "/O2",
                "/LD",
                "/MT",
                "/std:c11",
                "/D_CRT_SECURE_NO_WARNINGS",
                *codec,
                f"/Fe:{lib}",
            ],
            [
                "cl",
                "/nologo",
                "/O2",
                "/EHsc",
                "/MT",
                "/std:c++14",
                "/permissive-",
                "/DNOMINMAX",
                "/D_CRT_SECURE_NO_WARNINGS",
                f"/I{rapid / 'include'}",
                *sources,
                f"/Fe:{exe}",
            ],
        ]
    else:
        lib, exe = binary / "codec-1.so", binary / "tetra-rx"
        commands = [
            ["cc", "-O2", "-std=c11", "-shared", "-fPIC", *codec, "-o", str(lib)],
            [
                "c++",
                "-O2",
                "-std=c++14",
                f"-I{rapid / 'include'}",
                *sources,
                "-ldl",
                "-o",
                str(exe),
            ],
        ]
    for command in commands:
        search_path = next((v for k, v in env.items() if k.casefold() == "path"), "")
        compiler = shutil.which(command[0], path=search_path)
        if not compiler:
            raise RuntimeError(f"Compiler unavailable: {command[0]}")
        command[0] = compiler
        result = subprocess.run(
            command,
            cwd=build,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
        )
        (
            build
            / ("codec-build.log" if command is commands[0] else "receiver-build.log")
        ).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(
                f"TETRA build failed; logs: {build}\n{result.stdout[-3000:]}"
            )
    for slot in range(2, 5):
        shutil.copyfile(lib, binary / f"codec-{slot}{lib.suffix}")
    subprocess.run([str(exe)], input=b"", cwd=binary, check=True, timeout=10)
    shutil.copyfile(tetra / "LICENSE", binary / "LICENSE-tetra-kit")
    shutil.copyfile(rapid / "license.txt", binary / "LICENSE-rapidjson")
    manifest = {
        "revision": REVISION,
        "rapidjson": RAPID,
        "rx_only": True,
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in binary.iterdir()
            if p.is_file()
        },
    }
    (binary / "radiomind-manifest.json").write_text(json.dumps(manifest, indent=2))
    binary.rename(output)
    print(
        json.dumps(
            {"installed": str(output), "revision": REVISION, "build": str(build)}
        )
    )


if __name__ == "__main__":
    main()
