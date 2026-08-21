from __future__ import annotations

import shlex
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from .models import ConnectionConfig, Variable


class OpenOcdError(RuntimeError):
    pass


class TclRpcClient:
    TERMINATOR = b"\x1a"

    def __init__(self, host: str = "127.0.0.1", port: int = 6666, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: socket.socket | None = None

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def connect(self) -> None:
        self.close()
        self._socket = socket.create_connection((self.host, self.port), self.timeout)
        self._socket.settimeout(self.timeout)
        self.command("version")

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def command(self, command: str) -> str:
        sock = self._socket
        if sock is None:
            raise OpenOcdError("OpenOCD Tcl RPC is not connected")
        wrapped = (
            f"set __ocscope_status [catch {{{command}}} __ocscope_result]; "
            'format "%d\\n%s" $__ocscope_status $__ocscope_result'
        )
        try:
            sock.sendall(wrapped.encode("utf-8") + self.TERMINATOR)
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    raise OpenOcdError("OpenOCD closed the Tcl RPC connection")
                if self.TERMINATOR in chunk:
                    before, _separator, _after = chunk.partition(self.TERMINATOR)
                    chunks.append(before)
                    break
                chunks.append(chunk)
            response = b"".join(chunks).decode("utf-8", errors="replace")
        except OSError as exc:
            self.close()
            raise OpenOcdError(str(exc)) from exc
        status, separator, result = response.partition("\n")
        if not separator or status not in {"0", "1"}:
            raise OpenOcdError(f"Unexpected Tcl RPC response: {response.strip()}")
        if status == "1":
            raise OpenOcdError(result.strip() or f"OpenOCD command failed: {command}")
        return result.strip()

    def read_bytes(self, address: int, count: int) -> bytes:
        response = self.command(f"read_memory 0x{address:X} 8 {count}")
        try:
            values = [int(token, 0) for token in response.replace("{", "").replace("}", "").split()]
            return bytes(values)
        except (ValueError, OverflowError) as exc:
            raise OpenOcdError(f"Unexpected read_memory response: {response}") from exc

    def write_bytes(self, address: int, data: bytes) -> None:
        values = " ".join(str(value) for value in data)
        self.command(f"write_memory 0x{address:X} 8 {{{values}}}")

    def read_variables(self, variables: list[Variable], byte_order: str) -> dict[str, float | int]:
        result: dict[str, float | int] = {}
        for variable in variables:
            raw = self.read_bytes(variable.address, variable.byte_size)
            result[variable.name] = variable.decode(raw, byte_order)
        return result


class OpenOcdSession:
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.client = TclRpcClient(config.host, config.tcl_port)
        self.process: subprocess.Popen[str] | None = None
        self._output: deque[str] = deque(maxlen=200)
        self._output_thread: threading.Thread | None = None

    @property
    def description(self) -> str:
        return f"OpenOCD Tcl RPC {self.config.host}:{self.config.tcl_port}"

    def start(self, cancel_event: threading.Event | None = None) -> None:
        if self.config.launch_process:
            executable = str(Path(self.config.executable).expanduser())
            args = [executable]
            if self.config.interface_config:
                args.extend(["-f", self._resolve_config(self.config.interface_config)])
            transport = self._effective_transport()
            if transport is not None:
                args.extend(["-c", f"transport select {transport}"])
            if self.config.adapter_speed_khz > 0:
                args.extend(["-c", f"adapter speed {self.config.adapter_speed_khz}"])
            if self.config.target_config:
                args.extend(["-f", self._resolve_config(self.config.target_config)])
            for command in self.config.startup_commands.splitlines():
                if command.strip():
                    args.extend(["-c", command.strip()])
            args.extend(["-c", f"tcl_port {self.config.tcl_port}"])
            args.extend(shlex.split(self.config.extra_args, posix=False))
            try:
                self.process = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self._output_thread = threading.Thread(target=self._drain_output, daemon=True)
                self._output_thread.start()
            except OSError as exc:
                raise OpenOcdError(f"Cannot start OpenOCD: {exc}") from exc

        deadline = time.monotonic() + 8.0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                self.stop()
                raise OpenOcdError("OpenOCD connection cancelled")
            if self.process is not None and self.process.poll() is not None:
                raise OpenOcdError(f"OpenOCD exited early:\n{''.join(self._output)[-2000:]}")
            try:
                self.client.connect()
                return
            except (OSError, OpenOcdError) as exc:
                last_error = exc
                if cancel_event is not None:
                    cancel_event.wait(0.2)
                else:
                    time.sleep(0.2)
        self.stop()
        output = "".join(self._output).strip()
        details = f"Timed out connecting to Tcl RPC: {last_error}"
        if output:
            details += f"\n\nOpenOCD output:\n{output[-4000:]}"
        raise OpenOcdError(details)

    def _effective_transport(self) -> str | None:
        if self.config.transport != "auto":
            return self.config.transport
        if self.config.target_config.startswith("builtin/gd32f3"):
            return "swd"
        return None

    @staticmethod
    def _resolve_config(config: str) -> str:
        prefix = "builtin/"
        if not config.startswith(prefix):
            return config
        resource = Path(__file__).parent / "openocd_scripts" / config.removeprefix(prefix)
        if not resource.is_file():
            raise OpenOcdError(f"Built-in OpenOCD config not found: {config}")
        return str(resource)

    def stop(self) -> None:
        self.client.close()
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.process = None
        if self._output_thread is not None:
            self._output_thread.join(timeout=1)
            self._output_thread = None

    def _drain_output(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self._output.append(line)
