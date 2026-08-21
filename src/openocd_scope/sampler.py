from __future__ import annotations

import queue
import threading
import time

from PySide6.QtCore import QThread, Signal

from .jlink import JLinkSession, should_use_native_jlink
from .models import ConnectionConfig, Variable
from .openocd import OpenOcdSession


class SamplerThread(QThread):
    sample_ready = Signal(float, dict)
    connected = Signal(str)
    failed = Signal(str)
    stopped = Signal()
    command_result = Signal(str, str)

    def __init__(self, config: ConnectionConfig, variables: list[Variable], parent=None):
        super().__init__(parent)
        self.config = config
        self._variables = variables
        self._variables_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._writes: queue.Queue[tuple[Variable, float]] = queue.Queue()
        self._commands: queue.Queue[str] = queue.Queue()
        self._session: OpenOcdSession | JLinkSession | None = None

    def set_variables(self, variables: list[Variable]) -> None:
        with self._variables_lock:
            self._variables = variables

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    def write_value(self, variable: Variable, value: float) -> None:
        self._writes.put((variable, value))

    def send_command(self, command: str) -> None:
        self._commands.put(command)

    def stop(self) -> None:
        self._stop_event.set()
        if isinstance(self._session, OpenOcdSession):
            self._session.client.close()

    def run(self) -> None:
        session = (
            JLinkSession(self.config)
            if should_use_native_jlink(self.config)
            else OpenOcdSession(self.config)
        )
        self._session = session
        try:
            session.start(self._stop_event)
            self.connected.emit(session.description)
            started_at = time.perf_counter()
            next_sample = started_at
            while not self._stop_event.is_set():
                self._process_writes(session)
                self._process_commands(session)
                if self._paused.is_set():
                    self.msleep(20)
                    next_sample = time.perf_counter()
                    continue

                now = time.perf_counter()
                if now < next_sample:
                    self.msleep(max(1, int((next_sample - now) * 1000)))
                    continue
                with self._variables_lock:
                    variables = [item for item in self._variables if item.enabled]
                if variables:
                    values = session.client.read_variables(variables, self.config.byte_order)
                    self.sample_ready.emit(now - started_at, values)
                next_sample = max(next_sample + self.config.sample_interval_ms / 1000, now)
        except Exception as exc:  # noqa: BLE001 - report all worker failures to the UI
            if not self._stop_event.is_set():
                self.failed.emit(str(exc))
        finally:
            session.stop()
            self._session = None
            self.stopped.emit()

    def _process_writes(self, session: OpenOcdSession | JLinkSession) -> None:
        while True:
            try:
                variable, value = self._writes.get_nowait()
            except queue.Empty:
                return
            session.client.write_bytes(
                variable.address,
                variable.encode(value, self.config.byte_order),
            )

    def _process_commands(self, session: OpenOcdSession | JLinkSession) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            response = session.client.command(command)
            self.command_result.emit(command, response)
