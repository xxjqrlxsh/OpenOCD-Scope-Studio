from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from elftools.dwarf.dwarf_expr import DWARFExprParser
from elftools.elf.elffile import ELFFile


class SymbolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Symbol:
    name: str
    address: int
    size: int
    data_type: str | None = None


def symbol_path_parts(name: str) -> list[str]:
    return re.findall(r"[^.\[\]]+|\[[^\]]+\]", name)


def _attribute(die: Any, name: str, default: Any = None) -> Any:
    attribute = die.attributes.get(name)
    return attribute.value if attribute is not None else default


def _name(die: Any) -> str:
    value = _attribute(die, "DW_AT_name", b"")
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _referenced_type(die: Any) -> Any | None:
    try:
        return die.get_DIE_from_attribute("DW_AT_type")
    except (KeyError, AttributeError):
        return None


def _unwrap_type(die: Any | None) -> Any | None:
    wrappers = {
        "DW_TAG_typedef",
        "DW_TAG_const_type",
        "DW_TAG_volatile_type",
        "DW_TAG_restrict_type",
        "DW_TAG_atomic_type",
    }
    while die is not None and die.tag in wrappers:
        die = _referenced_type(die)
    return die


def _byte_size(die: Any | None, default: int = 0) -> int:
    die = _unwrap_type(die)
    if die is None:
        return default
    size = _attribute(die, "DW_AT_byte_size")
    if size is not None:
        return int(size)
    if die.tag in {"DW_TAG_structure_type", "DW_TAG_class_type", "DW_TAG_union_type"}:
        extent = 0
        for member in die.iter_children():
            if member.tag != "DW_TAG_member":
                continue
            location = _attribute(member, "DW_AT_data_member_location", 0)
            offset = 0 if die.tag == "DW_TAG_union_type" else location
            if isinstance(offset, int):
                extent = max(extent, offset + _byte_size(_referenced_type(member)))
        return extent or default
    if die.tag == "DW_TAG_array_type":
        count = 1
        for dimension in _array_counts(die):
            count *= dimension
        return _byte_size(_referenced_type(die)) * count
    referenced = _referenced_type(die)
    return _byte_size(referenced, default) if referenced is not None else default


def _scalar_type(die: Any | None, pointer_size: int) -> str | None:
    die = _unwrap_type(die)
    if die is None:
        return None
    size = _byte_size(die, pointer_size if die.tag == "DW_TAG_pointer_type" else 0)
    if die.tag == "DW_TAG_pointer_type":
        return f"uint{size * 8}" if size in {1, 2, 4, 8} else None
    if die.tag == "DW_TAG_enumeration_type":
        underlying = _scalar_type(_referenced_type(die), pointer_size)
        return underlying or (f"uint{size * 8}" if size in {1, 2, 4, 8} else None)
    if die.tag != "DW_TAG_base_type" or size not in {1, 2, 4, 8}:
        return None

    # DWARF standard DW_ATE values: float=4, signed=5, signed_char=6,
    # unsigned=7, unsigned_char=8, boolean=2, address=1.
    encoding = int(_attribute(die, "DW_AT_encoding", 0))
    if encoding == 4:
        return "float" if size == 4 else "double" if size == 8 else None
    if encoding in {5, 6}:
        return f"int{size * 8}"
    if encoding in {1, 2, 7, 8}:
        return f"uint{size * 8}"
    return None


def _member_offset(member: Any, expr_parser: DWARFExprParser | None = None) -> int | None:
    value = _attribute(member, "DW_AT_data_member_location")
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)):
        value = bytes(value)
    if not isinstance(value, (bytes, bytearray)) or expr_parser is None:
        return None
    try:
        operations = expr_parser.parse_expr(value)
    except Exception:  # noqa: BLE001 - vendor DWARF expressions vary
        return None
    offset = 0
    for operation in operations:
        if operation.op_name not in {"DW_OP_plus_uconst", "DW_OP_constu", "DW_OP_consts"}:
            return None
        offset += int(operation.args[0])
    return offset


def _array_counts(die: Any) -> list[int]:
    counts: list[int] = []
    for child in die.iter_children():
        if child.tag != "DW_TAG_subrange_type":
            continue
        count = _attribute(child, "DW_AT_count")
        if count is None:
            upper = _attribute(child, "DW_AT_upper_bound")
            lower = _attribute(child, "DW_AT_lower_bound", 0)
            count = int(upper) - int(lower) + 1 if upper is not None else 0
        counts.append(max(0, int(count)))
    return counts or [0]


def _variable_address(die: Any, expr_parser: DWARFExprParser) -> int | None:
    location = _attribute(die, "DW_AT_location")
    if isinstance(location, (list, tuple)):
        location = bytes(location)
    if not isinstance(location, (bytes, bytearray)):
        return None
    try:
        operations = expr_parser.parse_expr(location)
    except Exception:  # noqa: BLE001 - vendor DWARF expressions vary
        return None
    if len(operations) == 1 and operations[0].op_name == "DW_OP_addr":
        return int(operations[0].args[0])
    return None


def _expand_type(
    name: str,
    address: int,
    die: Any | None,
    pointer_size: int,
    expr_parser: DWARFExprParser | None = None,
    *,
    depth: int = 0,
    max_array_items: int = 256,
) -> list[Symbol]:
    die = _unwrap_type(die)
    if die is None or depth > 12:
        return []
    scalar = _scalar_type(die, pointer_size)
    if scalar:
        return [Symbol(name, address, _byte_size(die), scalar)]

    if die.tag in {"DW_TAG_structure_type", "DW_TAG_class_type", "DW_TAG_union_type"}:
        result: list[Symbol] = []
        for member in die.iter_children():
            if member.tag != "DW_TAG_member" or "DW_AT_bit_size" in member.attributes:
                continue
            offset = 0 if die.tag == "DW_TAG_union_type" else _member_offset(member, expr_parser)
            if offset is None:
                continue
            member_name = _name(member)
            child_name = f"{name}.{member_name}" if member_name else name
            result.extend(
                _expand_type(
                    child_name,
                    address + offset,
                    _referenced_type(member),
                    pointer_size,
                    expr_parser,
                    depth=depth + 1,
                    max_array_items=max_array_items,
                )
            )
        return result

    if die.tag == "DW_TAG_array_type":
        element_type = _referenced_type(die)
        element_size = _byte_size(element_type)
        if element_size <= 0:
            return []
        counts = _array_counts(die)
        result: list[Symbol] = []

        def expand_dimension(prefix: str, base: int, dimension: int, stride: int) -> None:
            if len(result) >= max_array_items:
                return
            count = counts[dimension]
            next_stride = stride // max(1, count)
            for index in range(count):
                indexed_name = f"{prefix}[{index}]"
                indexed_address = base + index * next_stride
                if dimension + 1 == len(counts):
                    result.extend(
                        _expand_type(
                            indexed_name,
                            indexed_address,
                            element_type,
                            pointer_size,
                            expr_parser,
                            depth=depth + 1,
                            max_array_items=max_array_items - len(result),
                        )
                    )
                else:
                    expand_dimension(indexed_name, indexed_address, dimension + 1, next_stride)
                if len(result) >= max_array_items:
                    return

        total_size = element_size
        for count in counts:
            total_size *= count
        expand_dimension(name, address, 0, total_size)
        return result
    return []


def _load_dwarf_members(elf: ELFFile, base_symbols: list[Symbol]) -> list[Symbol]:
    if not elf.has_dwarf_info():
        return []
    dwarf = elf.get_dwarf_info()
    by_name: dict[str, list[Symbol]] = {}
    for symbol in base_symbols:
        by_name.setdefault(symbol.name, []).append(symbol)
    result: dict[tuple[str, int], Symbol] = {}
    pointer_size = elf.elfclass // 8
    for compile_unit in dwarf.iter_CUs():
        expr_parser = DWARFExprParser(compile_unit.structs)
        for die in compile_unit.iter_DIEs():
            if die.tag != "DW_TAG_variable" or _attribute(die, "DW_AT_declaration", False):
                continue
            candidates = by_name.get(_name(die), [])
            if not candidates:
                continue
            variable_address = _variable_address(die, expr_parser)
            if variable_address is not None:
                candidates = [item for item in candidates if item.address == variable_address]
            if not candidates:
                continue
            variable_type = _referenced_type(die)
            for base in candidates:
                members = _expand_type(
                    base.name, base.address, variable_type, pointer_size, expr_parser
                )
                for member in members:
                    result[(member.name, member.address)] = member
    return list(result.values())


def load_symbols(path: str) -> list[Symbol]:
    file_path = Path(path)
    try:
        with file_path.open("rb") as stream:
            elf = ELFFile(stream)
            symbols: dict[tuple[str, int], Symbol] = {}
            for section_name in (".symtab", ".dynsym"):
                section = elf.get_section_by_name(section_name)
                if section is None:
                    continue
                for item in section.iter_symbols():
                    info = item["st_info"]
                    address = int(item["st_value"])
                    if info["type"] != "STT_OBJECT" or not item.name or address == 0:
                        continue
                    symbol = Symbol(item.name, address, int(item["st_size"]))
                    symbols[(symbol.name, symbol.address)] = symbol
            for member in _load_dwarf_members(elf, list(symbols.values())):
                symbols[(member.name, member.address)] = member
    except Exception as exc:
        raise SymbolError(
            "无法解析符号文件。Keil AXF 通常是 ELF；IAR 请启用 ELF/DWARF 输出，"
            "私有 UBROF 格式暂不支持。"
        ) from exc
    return sorted(symbols.values(), key=lambda item: item.name.casefold())
