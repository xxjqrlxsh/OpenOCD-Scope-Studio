from openocd_scope.models import ConnectionConfig, ProjectConfig, Variable
from openocd_scope.storage import export_csv, load_project, save_project


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
