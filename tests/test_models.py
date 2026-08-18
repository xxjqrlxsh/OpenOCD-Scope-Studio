import math

import pytest

from openocd_scope.models import Variable


@pytest.mark.parametrize(
    ("data_type", "value"),
    [("int8", -12), ("uint16", 65000), ("int32", -123456), ("float", 12.25)],
)
def test_variable_encode_decode_round_trip(data_type, value):
    variable = Variable("test", 0x20000000, data_type, scale=2.0, offset=1.0)
    displayed = value * 2.0 + 1.0
    decoded = variable.decode(variable.encode(displayed), "little")
    assert math.isclose(decoded, displayed, rel_tol=1e-6)


def test_variable_dict_preserves_hex_address():
    variable = Variable("counter", 0x20000120, "uint32")
    restored = Variable.from_dict(variable.to_dict())
    assert restored == variable
