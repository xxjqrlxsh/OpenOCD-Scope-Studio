from pathlib import Path

import openocd_scope.config_discovery as discovery


def test_discovers_nested_configs_relative_to_scripts(monkeypatch, tmp_path):
    scripts = tmp_path / "openocd" / "scripts"
    interface = scripts / "interface" / "ftdi"
    interface.mkdir(parents=True)
    (interface / "probe.cfg").write_text("adapter driver ftdi", encoding="utf-8")
    monkeypatch.setattr(discovery, "find_scripts_root", lambda _executable: scripts)

    assert discovery.discover_configs("openocd", "interface") == ["interface/ftdi/probe.cfg"]


def test_finds_xpack_scripts_layout(tmp_path):
    binary = tmp_path / "bin" / "openocd.exe"
    binary.parent.mkdir()
    binary.touch()
    scripts = tmp_path / "openocd" / "scripts"
    scripts.mkdir(parents=True)

    assert discovery.find_scripts_root(str(binary)) == Path(scripts).resolve()


def test_rejects_unknown_category():
    try:
        discovery.discover_configs("openocd", "invalid")
    except ValueError as exc:
        assert "invalid" in str(exc)
    else:
        raise AssertionError("ValueError was not raised")


def test_gd32_targets_are_available_without_external_scripts(monkeypatch):
    monkeypatch.setattr(discovery, "find_scripts_root", lambda _executable: None)

    targets = discovery.discover_configs("missing-openocd", "target")

    assert "builtin/gd32f30x-f303-f305-f307.cfg" in targets
    assert "builtin/gd32f3x0-f330-f350.cfg" in targets
