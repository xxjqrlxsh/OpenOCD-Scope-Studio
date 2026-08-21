from __future__ import annotations

import os
import threading
from pathlib import Path

import pylink

from .models import ConnectionConfig, Variable
from .openocd import OpenOcdError


def find_jlink_dll(configured: str = "") -> Path | None:
    if configured:
        path = Path(configured).expanduser()
        return path.resolve() if path.is_file() else None
    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "SEGGER",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "SEGGER",
    ]
    candidates: list[Path] = []
    for root in roots:
        if root.is_dir():
            candidates.extend(root.glob("JLink_*/JLink_x64.dll"))
            candidates.extend(root.glob("JLink_*/JLinkARM.dll"))
    return max(candidates).resolve() if candidates else None


def should_use_native_jlink(config: ConnectionConfig) -> bool:
    if config.backend == "jlink":
        return True
    if config.backend == "openocd":
        return False
    return Path(config.interface_config).name.casefold() == "jlink.cfg"


class JLinkClient:
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._jlink: pylink.JLink | None = None
        self.serial_number: int | None = None

    def connect(self) -> None:
        dll = find_jlink_dll(self.config.jlink_dll)
        if dll is None:
            raise OpenOcdError("未找到 SEGGER JLink_x64.dll，请安装 SEGGER J-Link Software。")
        try:
            library = pylink.library.Library(str(dll))
            self._jlink = pylink.JLink(lib=library)
            serial = self.config.jlink_serial or None
            self._jlink.open(serial_no=serial)
            self.serial_number = self._jlink.serial_number
            interface = (
                pylink.enums.JLinkInterfaces.JTAG
                if self.config.transport == "jtag"
                else pylink.enums.JLinkInterfaces.SWD
            )
            self._jlink.set_tif(interface)
            speed: int | str = self.config.adapter_speed_khz or "auto"
            self._jlink.connect(self.config.jlink_device, speed=speed)
            if not self._jlink.target_connected():
                raise OpenOcdError("J-Link 已打开，但未检测到目标芯片。请检查供电和 SWD 接线。")
        except Exception as exc:
            self.close()
            if isinstance(exc, OpenOcdError):
                raise
            raise OpenOcdError(f"SEGGER J-Link 连接失败: {exc}") from exc

    def close(self) -> None:
        if self._jlink is not None:
            try:
                self._jlink.close()
            finally:
                self._jlink = None

    def read_bytes(self, address: int, count: int) -> bytes:
        if self._jlink is None:
            raise OpenOcdError("J-Link is not connected")
        try:
            return bytes(self._jlink.memory_read8(address, count))
        except Exception as exc:
            raise OpenOcdError(f"J-Link 读取 0x{address:08X} 失败: {exc}") from exc

    def write_bytes(self, address: int, data: bytes) -> None:
        if self._jlink is None:
            raise OpenOcdError("J-Link is not connected")
        try:
            self._jlink.memory_write8(address, list(data))
        except Exception as exc:
            raise OpenOcdError(f"J-Link 写入 0x{address:08X} 失败: {exc}") from exc

    def read_variables(self, variables: list[Variable], byte_order: str) -> dict[str, float | int]:
        result: dict[str, float | int] = {}
        for variable in variables:
            result[variable.name] = variable.decode(
                self.read_bytes(variable.address, variable.byte_size), byte_order
            )
        return result

    def command(self, command: str) -> str:
        if self._jlink is None:
            raise OpenOcdError("J-Link is not connected")
        try:
            if command == "halt":
                self._jlink.halt()
            elif command == "resume":
                self._jlink.restart()
            elif command in {"reset", "reset run"}:
                self._jlink.reset(halt=False)
            elif command == "reset halt":
                self._jlink.reset(halt=True)
            else:
                raise OpenOcdError(f"原生 J-Link 后端不支持命令: {command}")
        except Exception as exc:
            if isinstance(exc, OpenOcdError):
                raise
            raise OpenOcdError(f"J-Link 命令失败: {exc}") from exc
        return "OK"


class JLinkSession:
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.client = JLinkClient(config)

    @property
    def description(self) -> str:
        serial = self.client.serial_number
        return f"SEGGER J-Link S/N {serial}" if serial else "SEGGER J-Link"

    def start(self, cancel_event: threading.Event | None = None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise OpenOcdError("J-Link connection cancelled")
        self.client.connect()

    def stop(self) -> None:
        self.client.close()
