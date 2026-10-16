"""Read-only USB inventory in an isolated process; never opens or tunes a device."""

import ctypes as ct
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class DeviceList(ct.Structure):
    _fields_ = [
        ("serial_numbers", ct.POINTER(ct.c_char_p)),
        ("usb_board_ids", ct.POINTER(ct.c_int)),
        ("usb_device_index", ct.POINTER(ct.c_int)),
        ("devicecount", ct.c_int),
        ("usb_devices", ct.POINTER(ct.c_void_p)),
        ("usb_devicecount", ct.c_int),
    ]


def enumerate_native(library: Path) -> list[dict[str, Any]]:
    path = library.resolve(strict=True)
    directory = os.add_dll_directory(str(path.parent)) if os.name == "nt" else None
    try:
        lib = ct.CDLL(str(path))
        lib.hackrf_init.argtypes, lib.hackrf_init.restype = [], ct.c_int
        lib.hackrf_exit.argtypes, lib.hackrf_exit.restype = [], ct.c_int
        lib.hackrf_device_list.argtypes = []
        lib.hackrf_device_list.restype = ct.POINTER(DeviceList)
        lib.hackrf_device_list_free.argtypes = [ct.POINTER(DeviceList)]
        lib.hackrf_device_list_free.restype = None
        if lib.hackrf_init() != 0:
            raise RuntimeError("Не удалось прочитать список USB-устройств")
        listing = None
        try:
            listing = lib.hackrf_device_list()
            if not listing:
                raise RuntimeError("HackRF не вернул список устройств")
            result = []
            for index in range(min(max(listing.contents.devicecount, 0), 64)):
                raw = listing.contents.serial_numbers[index]
                serial = raw.decode("ascii").lower() if raw else None
                result.append(
                    {
                        "serial": serial,
                        "label": f"HackRF USB · {serial or 'серийный номер недоступен'}",
                    }
                )
            return result
        finally:
            if listing:
                lib.hackrf_device_list_free(listing)
            lib.hackrf_exit()
    finally:
        if directory:
            directory.close()


def list_devices(library: Path) -> list[dict[str, Any]]:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "radiomind.devices", str(library.resolve())],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Поиск HackRF занял слишком много времени. Повторите попытку.") from exc
    if completed.returncode:
        raise RuntimeError("Не удалось найти HackRF. Проверьте USB и библиотеку приёмника.")
    return list(json.loads(completed.stdout))


if __name__ == "__main__":
    print(json.dumps(enumerate_native(Path(sys.argv[1]))))
