from __future__ import annotations

import struct
from dataclasses import asdict, dataclass, field
from typing import Any

DATA_TYPES: dict[str, tuple[str, int]] = {
    "int8": ("b", 1),
    "uint8": ("B", 1),
    "int16": ("h", 2),
    "uint16": ("H", 2),
    "int32": ("i", 4),
    "uint32": ("I", 4),
    "int64": ("q", 8),
    "uint64": ("Q", 8),
    "float": ("f", 4),
    "double": ("d", 8),
}


@dataclass
class Variable:
    name: str
    address: int
    data_type: str = "float"
    color: str = "#4cc9f0"
    enabled: bool = True
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    display_format: str = "auto"

    @property
    def byte_size(self) -> int:
        return DATA_TYPES[self.data_type][1]

    def decode(self, data: bytes, byte_order: str = "little") -> float | int:
        prefix = "<" if byte_order == "little" else ">"
        value = struct.unpack(prefix + DATA_TYPES[self.data_type][0], data)[0]
        return value * self.scale + self.offset

    def encode(self, displayed_value: float, byte_order: str = "little") -> bytes:
        raw_value = (displayed_value - self.offset) / self.scale
        code = DATA_TYPES[self.data_type][0]
        if code not in {"f", "d"}:
            raw_value = int(raw_value)
        prefix = "<" if byte_order == "little" else ">"
        return struct.pack(prefix + code, raw_value)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["address"] = f"0x{self.address:08X}"
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Variable:
        values = dict(data)
        address = values.get("address", 0)
        values["address"] = int(address, 0) if isinstance(address, str) else int(address)
        return cls(**values)


@dataclass
class ConnectionConfig:
    executable: str = "openocd"
    interface_config: str = "interface/stlink.cfg"
    target_config: str = "target/stm32f4x.cfg"
    transport: str = "auto"
    adapter_speed_khz: int = 2000
    startup_commands: str = ""
    extra_args: str = ""
    host: str = "127.0.0.1"
    tcl_port: int = 6666
    launch_process: bool = True
    sample_interval_ms: int = 50
    history_seconds: int = 60
    byte_order: str = "little"


@dataclass
class ProjectConfig:
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    symbol_file: str = ""
    variables: list[Variable] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection": asdict(self.connection),
            "symbol_file": self.symbol_file,
            "variables": [variable.to_dict() for variable in self.variables],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectConfig:
        return cls(
            connection=ConnectionConfig(**data.get("connection", {})),
            symbol_file=data.get("symbol_file", ""),
            variables=[Variable.from_dict(item) for item in data.get("variables", [])],
        )
