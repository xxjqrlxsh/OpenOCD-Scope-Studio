import json

from openocd_scope.models import ConnectionConfig, ProjectConfig, Variable
from openocd_scope.storage import (
    deserialize_connection,
    export_csv,
    export_json,
    load_project,
    save_project,
    serialize_connection,
)


def test_project_round_trip(tmp_path):
    project = ProjectConfig(
        connection=ConnectionConfig(sample_interval_ms=20),
        symbol_file="firmware.axf",
        variables=[Variable("speed", 0x20000010, "float")],
    )
    path = tmp_path / "test.ocscope"
    save_project(str(path), project)
    restored = load_project(str(path))
    assert restored == project


def test_csv_export_has_excel_bom_and_empty_cells(tmp_path):
    path = tmp_path / "samples.csv"
    export_csv(str(path), [{"time_s": 0.1, "a": 2}], ["a", "b"])
    content = path.read_text(encoding="utf-8-sig")
    assert content.splitlines() == ["time_s,a,b", "0.100000,2,"]


def test_json_export_contains_variable_metadata_and_samples(tmp_path):
    path = tmp_path / "samples.json"
    variable = Variable("motor.speed", 0x20000010, "float", unit="rpm")

    export_json(str(path), [{"time_s": 0.1, "motor.speed": 1200.0}], [variable])

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "openocd-scope-capture"
    assert data["variables"][0]["address"] == "0x20000010"
    assert data["variables"][0]["unit"] == "rpm"
    assert data["samples"][0]["motor.speed"] == 1200.0


def test_connection_settings_round_trip_and_ignore_unknown_fields():
    config = ConnectionConfig(
        backend="jlink",
        interface_config="interface/jlink.cfg",
        target_config="target/stm32f4x.cfg",
        transport="swd",
        adapter_speed_khz=1000,
        jlink_device="Cortex-M4",
        jlink_serial=69406946,
    )
    serialized = serialize_connection(config)
    data = json.loads(serialized)
    data["future_option"] = True

    restored = deserialize_connection(json.dumps(data))

    assert restored == config


def test_invalid_connection_settings_use_defaults():
    assert deserialize_connection("not-json") == ConnectionConfig()
