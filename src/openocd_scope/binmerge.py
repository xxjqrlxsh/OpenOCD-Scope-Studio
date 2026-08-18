from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BinMergeInfo:
    base_address: int
    app_address: int
    bootloader_size: int
    app_size: int

    @property
    def app_offset(self) -> int:
        return self.app_address - self.base_address

    @property
    def padding_size(self) -> int:
        return self.app_offset - self.bootloader_size

    @property
    def output_size(self) -> int:
        return self.app_offset + self.app_size

    @property
    def end_address(self) -> int:
        return self.base_address + self.output_size - 1


def merge_bin_data(bootloader: bytes, app: bytes, app_offset: int) -> bytes:
    if app_offset < 0:
        raise ValueError("App 地址不能小于 Bootloader 地址")
    if len(bootloader) > app_offset:
        raise ValueError(
            f"Bootloader 大小 0x{len(bootloader):X} 超过 App 偏移 0x{app_offset:X}，固件会重叠"
        )

    merged = bytearray(b"\xff") * (app_offset + len(app))
    merged[: len(bootloader)] = bootloader
    merged[app_offset:] = app
    return bytes(merged)


def merge_bin_files(
    bootloader_path: str,
    app_path: str,
    output_path: str,
    base_address: int = 0x08000000,
    app_address: int = 0x08020000,
) -> BinMergeInfo:
    if app_address < base_address:
        raise ValueError("App 地址不能小于 Bootloader 地址")

    bootloader_file = Path(bootloader_path).resolve()
    app_file = Path(app_path).resolve()
    output_file = Path(output_path).resolve()
    if output_file in {bootloader_file, app_file}:
        raise ValueError("输出文件不能覆盖 Bootloader 或 App 原文件")

    bootloader = bootloader_file.read_bytes()
    app = app_file.read_bytes()
    info = BinMergeInfo(base_address, app_address, len(bootloader), len(app))
    output_file.write_bytes(merge_bin_data(bootloader, app, info.app_offset))
    return info
