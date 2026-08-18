from pathlib import Path

from openocd_scope.openocd import OpenOcdSession


def test_resolves_gd32_builtin_config():
    resolved = OpenOcdSession._resolve_config("builtin/gd32f30x-f303-f305-f307.cfg")
    content = Path(resolved).read_text(encoding="utf-8")

    assert "set CPUTAPID 0x2ba01477" in content
    assert "source [find target/stm32f1x.cfg]" in content


def test_keeps_standard_openocd_config_name():
    assert OpenOcdSession._resolve_config("target/stm32f1x.cfg") == "target/stm32f1x.cfg"
