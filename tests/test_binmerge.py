import pytest

from openocd_scope.binmerge import merge_bin_data, merge_bin_files


def test_merge_bin_data_places_app_and_fills_gap():
    merged = merge_bin_data(b"\x01\x02", b"\xa0\xa1", 5)

    assert merged == b"\x01\x02\xff\xff\xff\xa0\xa1"


def test_merge_bin_data_rejects_overlap():
    with pytest.raises(ValueError, match="重叠"):
        merge_bin_data(b"1234", b"app", 3)


def test_merge_bin_files_reports_layout(tmp_path):
    bootloader = tmp_path / "bootloader.bin"
    app = tmp_path / "app.bin"
    output = tmp_path / "merged.bin"
    bootloader.write_bytes(b"BOOT")
    app.write_bytes(b"APP")

    info = merge_bin_files(str(bootloader), str(app), str(output), 0x08000000, 0x08000008)

    assert output.read_bytes() == b"BOOT\xff\xff\xff\xffAPP"
    assert info.padding_size == 4
    assert info.output_size == 11
    assert info.end_address == 0x0800000A
