from dataclasses import dataclass

from openocd_scope.symbols import _expand_type, symbol_path_parts


@dataclass
class Attribute:
    value: object


class Die:
    def __init__(self, tag, *, attributes=None, referenced_type=None, children=None):
        self.tag = tag
        self.attributes = {name: Attribute(value) for name, value in (attributes or {}).items()}
        self.referenced_type = referenced_type
        self.children = children or []

    def get_DIE_from_attribute(self, name):
        if name != "DW_AT_type" or self.referenced_type is None:
            raise KeyError(name)
        return self.referenced_type

    def iter_children(self):
        return iter(self.children)


def base_type(size, encoding):
    return Die(
        "DW_TAG_base_type",
        attributes={"DW_AT_byte_size": size, "DW_AT_encoding": encoding},
    )


def member(name, offset, referenced_type):
    return Die(
        "DW_TAG_member",
        attributes={"DW_AT_name": name.encode(), "DW_AT_data_member_location": offset},
        referenced_type=referenced_type,
    )


def test_expands_nested_structure_members_with_inferred_types():
    int32 = base_type(4, 5)
    float32 = base_type(4, 4)
    inner = Die("DW_TAG_structure_type", children=[member("gain", 0, float32)])
    outer = Die(
        "DW_TAG_structure_type",
        children=[member("count", 0, int32), member("pid", 4, inner)],
    )

    symbols = _expand_type("motor", 0x20000000, outer, 4)

    assert [(item.name, item.address, item.data_type) for item in symbols] == [
        ("motor.count", 0x20000000, "int32"),
        ("motor.pid.gain", 0x20000004, "float"),
    ]


def test_expands_arrays_of_structures():
    uint16 = base_type(2, 7)
    channel = Die("DW_TAG_structure_type", children=[member("value", 0, uint16)])
    range_die = Die("DW_TAG_subrange_type", attributes={"DW_AT_count": 3})
    channels = Die(
        "DW_TAG_array_type",
        attributes={"DW_AT_byte_size": 6},
        referenced_type=channel,
        children=[range_die],
    )

    symbols = _expand_type("channels", 0x20000100, channels, 4)

    assert [(item.name, item.address) for item in symbols] == [
        ("channels[0].value", 0x20000100),
        ("channels[1].value", 0x20000102),
        ("channels[2].value", 0x20000104),
    ]


def test_union_members_share_the_same_address_and_bitfields_are_skipped():
    uint32 = base_type(4, 7)
    bitfield = member("flags", 0, uint32)
    bitfield.attributes["DW_AT_bit_size"] = Attribute(3)
    union = Die(
        "DW_TAG_union_type",
        children=[member("raw", 9, uint32), bitfield],
    )

    symbols = _expand_type("status", 0x20000200, union, 4)

    assert [(item.name, item.address) for item in symbols] == [("status.raw", 0x20000200)]


def test_symbol_path_parts_preserves_array_indices():
    assert symbol_path_parts("channels[12].filter.state") == [
        "channels",
        "[12]",
        "filter",
        "state",
    ]
