from __future__ import annotations

import os
import shutil
from pathlib import Path

BUILTIN_CONFIGS = {
    "target": [
        "builtin/gd32f30x-f303-f305-f307.cfg",
        "builtin/gd32f3x0-f330-f350.cfg",
    ]
}


def resolve_executable(executable: str) -> Path | None:
    expanded = Path(executable).expanduser()
    if expanded.is_file():
        return expanded.resolve()
    located = shutil.which(executable)
    return Path(located).resolve() if located else None


def find_scripts_root(executable: str) -> Path | None:
    configured = os.environ.get("OPENOCD_SCRIPTS")
    if configured:
        root = Path(configured).expanduser()
        if root.is_dir():
            return root.resolve()

    binary = resolve_executable(executable)
    if binary is None:
        return None
    candidates = [
        binary.parent / "scripts",
        binary.parent.parent / "scripts",
        binary.parent.parent / "openocd" / "scripts",
        binary.parent.parent / "share" / "openocd" / "scripts",
    ]
    return next((path.resolve() for path in candidates if path.is_dir()), None)


def discover_configs(executable: str, category: str) -> list[str]:
    if category not in {"interface", "target", "board"}:
        raise ValueError(f"Unsupported OpenOCD config category: {category}")
    root = find_scripts_root(executable)
    folder = root / category if root else None
    if folder is None or not folder.is_dir():
        return list(BUILTIN_CONFIGS.get(category, []))
    configs = [path.relative_to(root).as_posix() for path in folder.rglob("*.cfg")]
    configs.extend(BUILTIN_CONFIGS.get(category, []))
    return sorted(configs, key=str.casefold)
