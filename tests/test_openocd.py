from openocd_scope.openocd import OpenOcdError, TclRpcClient


class FakeSocket:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.sent = b""

    def sendall(self, data):
        self.sent += data

    def recv(self, _size):
        return next(self.responses)

    def close(self):
        pass


def test_tcl_rpc_uses_substitute_character_terminator():
    client = TclRpcClient()
    client._socket = FakeSocket([b"0\nOpenOCD 0.12", b".0\x1a"])
    assert client.command("version") == "OpenOCD 0.12.0"
    assert client._socket.sent.endswith(b'format "%d\\n%s" $__ocscope_status $__ocscope_result\x1a')
    assert b"catch {version}" in client._socket.sent


def test_read_bytes_parses_openocd_values():
    client = TclRpcClient()
    client._socket = FakeSocket([b"0\n0x12 52 0x56\x1a"])
    assert client.read_bytes(0x20000000, 3) == b"\x12\x34\x56"


def test_tcl_rpc_raises_for_caught_command_error():
    client = TclRpcClient()
    client._socket = FakeSocket([b"1\ninvalid command name bad_command\x1a"])

    try:
        client.command("bad_command")
    except OpenOcdError as exc:
        assert "invalid command" in str(exc)
    else:
        raise AssertionError("OpenOcdError was not raised")
