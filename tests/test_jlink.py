from openocd_scope.jlink import should_use_native_jlink
from openocd_scope.models import ConnectionConfig


def test_auto_backend_uses_native_driver_for_jlink_interface():
    config = ConnectionConfig(backend="auto", interface_config="interface/jlink.cfg")

    assert should_use_native_jlink(config)


def test_openocd_backend_can_be_forced_for_jlink_interface():
    config = ConnectionConfig(backend="openocd", interface_config="interface/jlink.cfg")

    assert not should_use_native_jlink(config)


def test_non_jlink_probe_keeps_openocd_backend():
    config = ConnectionConfig(backend="auto", interface_config="interface/stlink.cfg")

    assert not should_use_native_jlink(config)
