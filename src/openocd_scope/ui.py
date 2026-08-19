from __future__ import annotations

import copy
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

import pyqtgraph as pg
from PySide6.QtCore import QModelIndex, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .binmerge import merge_bin_files
from .config_discovery import discover_configs, find_scripts_root
from .models import DATA_TYPES, ConnectionConfig, ProjectConfig, Variable
from .sampler import SamplerThread
from .storage import export_csv, export_json, load_project, save_project
from .symbols import Symbol, SymbolError, load_symbols, symbol_path_parts

COL_ENABLED = 0
COL_NAME = 1
COL_VALUE = 2
COL_TYPE = 3
COL_ADDRESS = 4
COL_FORMAT = 5
COL_UNIT = 6
COL_SCALE = 7
COL_OFFSET = 8
COL_COLOR = 9


class WatchTableDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index: QModelIndex):
        column = index.column()
        if column == COL_TYPE:
            editor = QComboBox(parent)
            editor.addItems(DATA_TYPES)
        elif column == COL_FORMAT:
            editor = QComboBox(parent)
            editor.addItems(["auto", "dec", "hex", "bin"])
        elif column in {COL_SCALE, COL_OFFSET}:
            editor = QDoubleSpinBox(parent)
            editor.setDecimals(8)
            editor.setRange(-1e12, 1e12)
            editor.setSingleStep(0.1)
        else:
            editor = QLineEdit(parent)
        editor.setObjectName("tableEditor")
        return editor

    def setEditorData(self, editor, index: QModelIndex) -> None:
        value = index.data(Qt.EditRole)
        if isinstance(editor, QComboBox):
            editor.setCurrentText(str(value))
        elif isinstance(editor, QDoubleSpinBox):
            try:
                editor.setValue(float(value))
            except (TypeError, ValueError):
                editor.setValue(0.0)
        else:
            editor.setText(str(value))
            editor.selectAll()

    def setModelData(self, editor, model, index: QModelIndex) -> None:
        if isinstance(editor, QComboBox):
            value = editor.currentText()
        elif isinstance(editor, QDoubleSpinBox):
            value = format(editor.value(), ".10g")
        else:
            value = editor.text()
        model.setData(index, value, Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index: QModelIndex) -> None:
        editor.setGeometry(option.rect.adjusted(3, 3, -3, -3))


class ScopeFloatingWindow(QMainWindow):
    close_requested = Signal()

    def closeEvent(self, event) -> None:
        self.close_requested.emit()
        event.ignore()


def searchable_combo(items: list[str], current: str = "") -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.addItems(items)
    combo.setCurrentText(current)
    completer = combo.completer()
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    completer.setCompletionMode(QCompleter.PopupCompletion)
    return combo


class ConnectionDialog(QDialog):
    def __init__(self, config: ConnectionConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("连接与采集设置")
        self.setMinimumWidth(620)
        self.executable = QLineEdit(config.executable)
        executable_row = QWidget()
        executable_layout = QHBoxLayout(executable_row)
        executable_layout.setContentsMargins(0, 0, 0, 0)
        executable_layout.addWidget(self.executable)
        browse = QPushButton("浏览")
        browse.clicked.connect(self._browse_executable)
        executable_layout.addWidget(browse)

        self.interface = searchable_combo([], config.interface_config)
        self.target = searchable_combo([], config.target_config)
        self.transport = QComboBox()
        self.transport.addItems(["auto", "swd", "jtag"])
        self.transport.setCurrentText(config.transport)
        self.speed = QSpinBox()
        self.speed.setRange(0, 100000)
        self.speed.setSpecialValueText("OpenOCD 默认")
        self.speed.setSuffix(" kHz")
        self.speed.setValue(config.adapter_speed_khz)
        self.startup_commands = QPlainTextEdit(config.startup_commands)
        self.startup_commands.setPlaceholderText("每行一条 OpenOCD 初始化命令（可选）")
        self.startup_commands.setMaximumHeight(80)
        self.extra_args = QLineEdit(config.extra_args)
        self.host = QLineEdit(config.host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(config.tcl_port)
        self.launch = QCheckBox("由本软件启动和关闭 OpenOCD")
        self.launch.setChecked(config.launch_process)
        self.interval = QSpinBox()
        self.interval.setRange(5, 60000)
        self.interval.setSuffix(" ms")
        self.interval.setValue(config.sample_interval_ms)
        self.history = QSpinBox()
        self.history.setRange(1, 86400)
        self.history.setSuffix(" s")
        self.history.setValue(config.history_seconds)
        self.byte_order = QComboBox()
        self.byte_order.addItems(["little", "big"])
        self.byte_order.setCurrentText(config.byte_order)
        self.scan_info = QLabel()
        self.scan_info.setObjectName("muted")

        form = QFormLayout(self)
        form.setSpacing(12)
        form.addRow("OpenOCD 程序", executable_row)
        form.addRow("调试器 / Probe", self.interface)
        form.addRow("目标芯片 / Target", self.target)
        form.addRow("传输协议", self.transport)
        form.addRow("适配器速度", self.speed)
        form.addRow("启动命令", self.startup_commands)
        form.addRow("附加参数", self.extra_args)
        form.addRow("Tcl RPC", self._host_port_row())
        form.addRow("进程模式", self.launch)
        form.addRow("采样周期", self.interval)
        form.addRow("历史窗口", self.history)
        form.addRow("目标字节序", self.byte_order)
        form.addRow("配置扫描", self.scan_info)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("应用设置")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.executable.editingFinished.connect(self._scan_configs)
        self._scan_configs()

    def _host_port_row(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.host, 1)
        layout.addWidget(self.port)
        return widget

    def _browse_executable(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 OpenOCD", "", "OpenOCD (openocd.exe);;程序 (*.exe)"
        )
        if path:
            self.executable.setText(path)
            self._scan_configs()

    def _scan_configs(self) -> None:
        executable = self.executable.text().strip()
        interfaces = discover_configs(executable, "interface")
        targets = discover_configs(executable, "target")
        self._replace_items(self.interface, interfaces)
        self._replace_items(self.target, targets)
        root = find_scripts_root(executable)
        if root:
            self.scan_info.setText(f"{root}  |  {len(interfaces)} 个调试器，{len(targets)} 个目标")
        else:
            self.scan_info.setText("未找到 scripts 目录，仍可手工输入配置路径")

    @staticmethod
    def _replace_items(combo: QComboBox, items: list[str]) -> None:
        current = combo.currentText()
        combo.clear()
        combo.addItems(items)
        combo.setCurrentText(current)

    def config(self) -> ConnectionConfig:
        return ConnectionConfig(
            executable=self.executable.text().strip(),
            interface_config=self.interface.currentText().strip(),
            target_config=self.target.currentText().strip(),
            transport=self.transport.currentText(),
            adapter_speed_khz=self.speed.value(),
            startup_commands=self.startup_commands.toPlainText().strip(),
            extra_args=self.extra_args.text().strip(),
            host=self.host.text().strip(),
            tcl_port=self.port.value(),
            launch_process=self.launch.isChecked(),
            sample_interval_ms=self.interval.value(),
            history_seconds=self.history.value(),
            byte_order=self.byte_order.currentText(),
        )


class VariableDialog(QDialog):
    def __init__(self, symbols: list[Symbol], parent=None, selected: Symbol | None = None):
        super().__init__(parent)
        self.symbols = symbols
        self.setWindowTitle("添加监视变量")
        self.setMinimumWidth(460)
        self.name = searchable_combo(
            [symbol.name for symbol in symbols], selected.name if selected else ""
        )
        self.name.currentTextChanged.connect(self._symbol_changed)
        self.address = QLineEdit("0x20000000")
        self.data_type = QComboBox()
        self.data_type.addItems(DATA_TYPES)
        self.data_type.setCurrentText("float")
        self.display_format = QComboBox()
        self.display_format.addItems(["auto", "dec", "hex", "bin"])
        self.unit = QLineEdit()
        self.unit.setPlaceholderText("例如 V、rpm、°C")
        self.scale = QLineEdit("1")
        self.offset = QLineEdit("0")
        form = QFormLayout(self)
        form.addRow("符号 / 名称", self.name)
        form.addRow("内存地址", self.address)
        form.addRow("数据类型", self.data_type)
        form.addRow("显示格式", self.display_format)
        form.addRow("工程单位", self.unit)
        form.addRow("比例", self.scale)
        form.addRow("偏移", self.offset)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("添加到监视")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        if selected:
            self._symbol_changed(selected.name)
        elif symbols:
            self._symbol_changed(self.name.currentText())

    def _symbol_changed(self, name: str) -> None:
        symbol = next((item for item in self.symbols if item.name == name), None)
        if symbol:
            self.address.setText(f"0x{symbol.address:08X}")
            inferred_type = symbol.data_type or {
                1: "uint8",
                2: "uint16",
                4: "uint32",
                8: "uint64",
            }.get(symbol.size, "float")
            self.data_type.setCurrentText(inferred_type)

    def _validate(self) -> None:
        try:
            int(self.address.text(), 0)
            scale = float(self.scale.text())
            float(self.offset.text())
            if not self.name.currentText().strip():
                raise ValueError("名称不能为空")
            if scale == 0:
                raise ValueError("比例不能为 0")
        except ValueError as exc:
            QMessageBox.warning(self, "输入无效", str(exc))
            return
        self.accept()

    def variable(self, color: str) -> Variable:
        return Variable(
            name=self.name.currentText().strip(),
            address=int(self.address.text(), 0),
            data_type=self.data_type.currentText(),
            color=color,
            scale=float(self.scale.text()),
            offset=float(self.offset.text()),
            unit=self.unit.text().strip(),
            display_format=self.display_format.currentText(),
        )


class BinMergeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BIN 固件合并")
        self.setMinimumWidth(680)

        self.bootloader_path = QLineEdit()
        self.bootloader_path.setPlaceholderText("选择 Bootloader BIN 文件")
        self.app_path = QLineEdit()
        self.app_path.setPlaceholderText("选择 App BIN 文件")
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("选择合并文件保存位置")
        self.base_address = QLineEdit("0x08000000")
        self.app_address = QLineEdit("0x08020000")
        self.result = QLabel("合并布局：Bootloader @ 0x08000000，App @ 0x08020000，间隙填充 0xFF")
        self.result.setObjectName("muted")
        self.result.setWordWrap(True)

        form = QFormLayout(self)
        form.setSpacing(12)
        form.addRow("Bootloader BIN", self._path_row(self.bootloader_path, self._browse_bootloader))
        form.addRow("Bootloader 地址", self.base_address)
        form.addRow("App BIN", self._path_row(self.app_path, self._browse_app))
        form.addRow("App 地址", self.app_address)
        form.addRow("输出 BIN", self._path_row(self.output_path, self._browse_output))
        form.addRow("说明", self.result)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        merge_button = QPushButton("合并并生成 BIN")
        merge_button.setObjectName("primaryButton")
        merge_button.clicked.connect(self._merge)
        buttons.addButton(merge_button, QDialogButtonBox.AcceptRole)
        form.addRow(buttons)

    def _path_row(self, field: QLineEdit, handler) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field, 1)
        browse = QPushButton("浏览")
        browse.clicked.connect(handler)
        layout.addWidget(browse)
        return row

    def _browse_bootloader(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Bootloader BIN", "", "BIN 固件 (*.bin);;所有文件 (*)"
        )
        if not path:
            return
        self.bootloader_path.setText(path)
        if not self.output_path.text().strip():
            self.output_path.setText(str(Path(path).with_name("merged.bin")))

    def _browse_app(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 App BIN", "", "BIN 固件 (*.bin);;所有文件 (*)"
        )
        if path:
            self.app_path.setText(path)

    def _browse_output(self) -> None:
        initial = self.output_path.text().strip() or "merged.bin"
        path, _ = QFileDialog.getSaveFileName(self, "保存合并 BIN", initial, "BIN 固件 (*.bin)")
        if path:
            self.output_path.setText(path)

    @staticmethod
    def _parse_hex_address(text: str) -> int:
        value = text.strip()
        if value.lower().startswith("0x"):
            value = value[2:]
        if not value:
            raise ValueError("地址不能为空")
        address = int(value, 16)
        if not 0 <= address <= 0xFFFFFFFF:
            raise ValueError("地址必须在 0x00000000 到 0xFFFFFFFF 之间")
        return address

    def _merge(self) -> None:
        try:
            bootloader = self.bootloader_path.text().strip()
            app = self.app_path.text().strip()
            output = self.output_path.text().strip()
            if not bootloader or not app or not output:
                raise ValueError("请选择 Bootloader、App 和输出 BIN 文件")
            base_address = self._parse_hex_address(self.base_address.text())
            app_address = self._parse_hex_address(self.app_address.text())
            info = merge_bin_files(bootloader, app, output, base_address, app_address)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "合并失败", str(exc))
            return

        self.result.setText(
            f"已生成 {output}\n"
            f"App 偏移：0x{info.app_offset:X}，0xFF 填充：{info.padding_size} 字节，"
            f"文件大小：{info.output_size} 字节，结束地址：0x{info.end_address:08X}"
        )
        QMessageBox.information(
            self,
            "合并完成",
            f"已生成：\n{output}\n\n下载起始地址：0x{info.base_address:08X}",
        )


class MainWindow(QMainWindow):
    COLORS: ClassVar[list[str]] = ["#27c2ff", "#ff5c8a", "#ffc857", "#62d394", "#a78bfa", "#ff8c42"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenOCD Scope Studio")
        self.resize(1460, 880)
        self.setMinimumSize(1050, 650)
        self.project = ProjectConfig()
        self.symbols: list[Symbol] = []
        self.samples: deque[dict[str, float | int]] = deque()
        self.sample_arrivals: deque[float] = deque()
        self.worker: SamplerThread | None = None
        self.curves: dict[str, pg.PlotDataItem] = {}
        self._updating_table = False
        self._last_plot_update = 0.0
        self._paused = False
        self._error_count = 0
        self.floating_scope: ScopeFloatingWindow | None = None
        self.settings = QSettings("OpenOCD Scope", "Studio")
        self.theme = str(self.settings.value("theme", "dark"))
        if self.theme not in {"dark", "light"}:
            self.theme = "dark"
        self._build_ui()
        self._apply_theme(self.theme)
        self._scan_quick_configs()
        self.metrics_timer = QTimer(self)
        self.metrics_timer.timeout.connect(self._update_metrics)
        self.metrics_timer.start(1000)

    def _build_ui(self) -> None:
        self._build_menu()
        self._build_toolbar()
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(self._build_connection_bar())
        self.workspace = QTabWidget()
        self.workspace.setDocumentMode(True)
        self.workspace.addTab(self._build_watch_page(), "变量监视")
        self.scope_page = self._build_scope_page()
        self.workspace.addTab(self.scope_page, "实时示波器")
        layout.addWidget(self.workspace, 1)
        self.setCentralWidget(root)
        self._build_symbol_dock()
        self._build_log_dock()
        self._build_status_bar()

    def _build_menu(self) -> None:
        project_menu = self.menuBar().addMenu("项目")
        for title, handler in (
            ("打开项目", self.open_project),
            ("保存项目", self.save_project),
            ("导出采样数据", self.export_data),
        ):
            project_menu.addAction(title).triggered.connect(handler)
        target_menu = self.menuBar().addMenu("目标")
        for title, command in (
            ("复位并运行", "reset run"),
            ("暂停目标", "halt"),
            ("继续运行", "resume"),
        ):
            target_menu.addAction(title).triggered.connect(
                lambda _checked=False, value=command: self.send_target_command(value)
            )
        view_menu = self.menuBar().addMenu("视图")
        view_menu.addAction("符号浏览器").triggered.connect(
            lambda: self.symbol_dock.setVisible(True)
        )
        view_menu.addAction("事件日志").triggered.connect(lambda: self.log_dock.setVisible(True))
        view_menu.addSeparator()
        self.theme_action = view_menu.addAction("")
        self.theme_action.triggered.connect(self.toggle_theme)
        tools_menu = self.menuBar().addMenu("工具")
        tools_menu.addAction("BIN 固件合并").triggered.connect(self.show_bin_merger)
        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction("关于与许可证").triggered.connect(self.show_about)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("快捷操作")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(toolbar)
        for title, handler in (
            ("打开项目", self.open_project),
            ("保存项目", self.save_project),
            ("加载符号", self.open_symbol_file),
            ("添加变量", self.add_variable),
            ("导出数据", self.export_data),
        ):
            action = QAction(title, self)
            action.triggered.connect(handler)
            toolbar.addAction(action)
        toolbar.addSeparator()
        for title, command in (("复位", "reset run"), ("停止核", "halt"), ("运行核", "resume")):
            action = QAction(title, self)
            action.triggered.connect(
                lambda _checked=False, value=command: self.send_target_command(value)
            )
            toolbar.addAction(action)
        toolbar.addSeparator()
        self.toolbar_theme_action = QAction("", self)
        self.toolbar_theme_action.triggered.connect(self.toggle_theme)
        toolbar.addAction(self.toolbar_theme_action)
        self._update_theme_action_text()

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 OpenOCD Scope Studio",
            "<h3>OpenOCD Scope Studio 0.2.0</h3>"
            "<p>OpenOCD 变量监视、实时示波器与数据导出工具。</p>"
            "<p>Copyright (C) 2026 OpenOCD Scope Studio contributors</p>"
            "<p>本程序采用 GPL-3.0-only，按现状提供且不附带任何担保。"
            "你可以依照 GPL-3.0 复制、修改和再分发。</p>"
            '<p><a href="https://github.com/xxjqrlxsh/OpenOCD-Scope-Studio">项目与完整源码</a></p>',
        )

    def show_bin_merger(self) -> None:
        BinMergeDialog(self).exec()

    def _build_connection_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("connectionCard")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 12, 18, 12)
        title_box = QVBoxLayout()
        title = QLabel("TARGET CONNECTION")
        title.setObjectName("eyebrow")
        self.connection_summary = QLabel("选择调试器和目标芯片")
        self.connection_summary.setObjectName("connectionSummary")
        title_box.addWidget(title)
        title_box.addWidget(self.connection_summary)
        layout.addLayout(title_box)
        layout.addSpacing(24)
        self.quick_interface = searchable_combo([], self.project.connection.interface_config)
        self.quick_interface.setMinimumWidth(190)
        self.quick_target = searchable_combo([], self.project.connection.target_config)
        self.quick_target.setMinimumWidth(220)
        self.quick_interval = QSpinBox()
        self.quick_interval.setRange(5, 60000)
        self.quick_interval.setValue(self.project.connection.sample_interval_ms)
        self.quick_interval.setSuffix(" ms")
        layout.addWidget(self._labeled_control("调试器", self.quick_interface))
        layout.addWidget(self._labeled_control("目标芯片", self.quick_target))
        layout.addWidget(self._labeled_control("采样周期", self.quick_interval))
        settings = QPushButton("高级设置")
        settings.clicked.connect(self.configure_connection)
        self.connect_button = QPushButton("连接目标")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self._toggle_connection)
        layout.addWidget(settings)
        layout.addWidget(self.connect_button)
        self.quick_interface.currentTextChanged.connect(self._quick_config_changed)
        self.quick_target.currentTextChanged.connect(self._quick_config_changed)
        self.quick_interval.valueChanged.connect(self._quick_config_changed)
        return frame

    @staticmethod
    def _labeled_control(label: str, control: QWidget) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        caption = QLabel(label)
        caption.setObjectName("fieldLabel")
        layout.addWidget(caption)
        layout.addWidget(control)
        return widget

    def _build_watch_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        header = QHBoxLayout()
        heading = QLabel("实时变量监视")
        heading.setObjectName("pageTitle")
        self.watch_hint = QLabel("从左侧符号浏览器双击变量，或按地址手工添加")
        self.watch_hint.setObjectName("muted")
        header.addWidget(heading)
        header.addWidget(self.watch_hint)
        header.addStretch()
        add = QPushButton("添加变量")
        add.clicked.connect(self.add_variable)
        remove = QPushButton("删除")
        remove.clicked.connect(self.remove_variable)
        write = QPushButton("写入值")
        write.clicked.connect(self.write_value)
        header.addWidget(add)
        header.addWidget(remove)
        header.addWidget(write)
        layout.addLayout(header)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["采样", "变量", "当前值", "类型", "地址", "格式", "单位", "比例", "偏移", "图线"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setItemDelegate(WatchTableDelegate(self.table))
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_VALUE, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._table_changed)
        self.table.cellDoubleClicked.connect(self._cell_double_clicked)
        layout.addWidget(self.table)
        return page

    def _build_scope_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        controls = QHBoxLayout()
        heading = QLabel("Host-polled Oscilloscope")
        heading.setObjectName("pageTitle")
        controls.addWidget(heading)
        controls.addStretch()
        self.pause_button = QPushButton("暂停采样")
        self.pause_button.clicked.connect(self.toggle_pause)
        clear = QPushButton("清空波形")
        clear.clicked.connect(self.clear_data)
        self.scope_float_button = QPushButton("浮动窗口")
        self.scope_float_button.clicked.connect(self.toggle_scope_floating)
        self.autoscale = QCheckBox("Y 轴自动缩放")
        self.autoscale.setChecked(True)
        controls.addWidget(self.autoscale)
        controls.addWidget(self.pause_button)
        controls.addWidget(clear)
        controls.addWidget(self.scope_float_button)
        layout.addLayout(controls)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "时间", units="s")
        self.plot.setLabel("left", "工程值")
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.addLegend(offset=(12, 12))
        layout.addWidget(self.plot, 1)
        self.stats_table = QTableWidget(0, 5)
        self.stats_table.setHorizontalHeaderLabels(["通道", "当前值", "最小值", "最大值", "单位"])
        self.stats_table.setMaximumHeight(150)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.stats_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.stats_table)
        return page

    def _build_symbol_dock(self) -> None:
        self.symbol_dock = QDockWidget("符号浏览器", self)
        self.symbol_dock.setObjectName("symbolDock")
        self.symbol_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        body = QWidget()
        layout = QVBoxLayout(body)
        self.symbol_search = QLineEdit()
        self.symbol_search.setPlaceholderText("搜索 ELF / AXF 全局变量...")
        self.symbol_search.setClearButtonEnabled(True)
        self.symbol_search.textChanged.connect(self._filter_symbols)
        self.symbol_tree = QTreeWidget()
        self.symbol_tree.setHeaderLabels(["符号", "类型", "地址"])
        self.symbol_tree.setAlternatingRowColors(True)
        self.symbol_tree.setUniformRowHeights(True)
        self.symbol_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.symbol_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.symbol_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.symbol_tree.itemDoubleClicked.connect(self._add_symbol_item)
        self.symbol_count = QLabel("尚未加载符号文件")
        self.symbol_count.setObjectName("muted")
        load = QPushButton("加载 Keil / IAR 符号文件")
        load.clicked.connect(self.open_symbol_file)
        layout.addWidget(self.symbol_search)
        layout.addWidget(self.symbol_tree, 1)
        layout.addWidget(self.symbol_count)
        layout.addWidget(load)
        self.symbol_dock.setWidget(body)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.symbol_dock)

    def toggle_scope_floating(self) -> None:
        if self.floating_scope is not None:
            self._restore_scope_page()
            return
        index = self.workspace.indexOf(self.scope_page)
        if index >= 0:
            self.workspace.removeTab(index)
        window = ScopeFloatingWindow()
        window.setWindowTitle("OpenOCD Scope Studio · 实时示波器")
        window.setStyleSheet(self.styleSheet())
        window.setCentralWidget(self.scope_page)
        self.scope_page.setVisible(True)
        window.close_requested.connect(self._restore_scope_page)
        self.floating_scope = window
        self.scope_float_button.setText("返回主窗口")
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            width = min(1440, int(available.width() * 0.9))
            height = min(900, int(available.height() * 0.88))
            window.resize(width, height)
            window.move(
                available.x() + (available.width() - width) // 2,
                available.y() + (available.height() - height) // 2,
            )
        window.show()
        self.scope_page.show()
        window.raise_()
        window.activateWindow()
        self._log("INFO", "实时示波器已切换到浮动窗口")

    def _restore_scope_page(self) -> None:
        window = self.floating_scope
        if window is None:
            return
        window.close_requested.disconnect(self._restore_scope_page)
        window.takeCentralWidget()
        window.hide()
        window.deleteLater()
        self.floating_scope = None
        self.workspace.addTab(self.scope_page, "实时示波器")
        self.workspace.setCurrentWidget(self.scope_page)
        self.scope_page.show()
        self.scope_float_button.setText("浮动窗口")
        self._log("INFO", "实时示波器已返回主窗口")

    def _build_log_dock(self) -> None:
        self.log_dock = QDockWidget("事件与诊断", self)
        self.log_dock.setObjectName("logDock")
        self.log_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_dock.setWidget(self.log_view)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        self.log_dock.setMaximumHeight(190)
        self._log("INFO", "OpenOCD Scope Studio 已就绪")

    def _build_status_bar(self) -> None:
        status = QStatusBar()
        self.setStatusBar(status)
        self.status_connection = QLabel("未连接")
        self.status_rate = QLabel("0.0 Sa/s")
        self.status_samples = QLabel("0 samples")
        self.status_errors = QLabel("0 errors")
        status.addWidget(self.status_connection)
        status.addPermanentWidget(self.status_rate)
        status.addPermanentWidget(self.status_samples)
        status.addPermanentWidget(self.status_errors)

    def toggle_theme(self) -> None:
        self._apply_theme("light" if self.theme == "dark" else "dark")

    def _apply_theme(self, theme: str) -> None:
        self.theme = theme
        self.settings.setValue("theme", theme)
        if theme == "dark":
            background = "#0b1220"
            foreground = "#a9b8cc"
            style = (
                "QMainWindow,QWidget{background:#0b1220;color:#dce7f5;font-family:'Segoe UI';font-size:13px;}"
                "QMenuBar,QMenu,QToolBar,QStatusBar{background:#111b2e;color:#dce7f5;border:0;}"
                "QMenuBar{padding:4px;}QToolBar{padding:7px 12px;spacing:5px;border-bottom:1px solid #22314a;}"
                "QToolButton,QPushButton{background:#17243a;color:#dce7f5;border:1px solid #2a3b57;border-radius:6px;padding:7px 12px;}"
                "QToolButton:hover,QPushButton:hover{background:#203451;border-color:#3b82f6;}"
                "QPushButton#primaryButton{background:#1677ff;border-color:#338cff;color:white;font-weight:600;padding:9px 18px;}"
                "QPushButton#primaryButton:hover{background:#2b88ff;}"
                "QFrame#connectionCard{background:#111b2e;border:1px solid #253651;border-radius:10px;}"
                "QLabel#eyebrow{color:#4da3ff;font-size:10px;font-weight:700;letter-spacing:1px;}"
                "QLabel#connectionSummary,QLabel#pageTitle{font-size:17px;font-weight:600;color:#f4f8ff;}"
                "QLabel#fieldLabel,QLabel#muted{color:#7f91aa;font-size:11px;}"
                "QLineEdit,QComboBox,QSpinBox,QPlainTextEdit{background:#0e1728;border:1px solid #2a3b57;border-radius:6px;padding:7px;color:#e7effa;selection-background-color:#1677ff;}"
                "QTableWidget QLineEdit#tableEditor,QTableWidget QComboBox#tableEditor,QTableWidget QDoubleSpinBox#tableEditor{background:#101f35;color:#ffffff;border:1px solid #3b8cff;border-radius:5px;padding:2px 6px;margin:0;selection-color:#ffffff;selection-background-color:#256fbd;}"
                "QLineEdit:focus,QComboBox:focus,QSpinBox:focus{border-color:#338cff;}"
                "QComboBox QAbstractItemView{background:#142137;border:1px solid #304463;selection-background-color:#245fa8;}"
                "QTabWidget::pane{border:1px solid #22314a;border-radius:8px;background:#0e1728;}"
                "QTabBar::tab{background:#101a2c;color:#8395ad;padding:10px 20px;border:0;}"
                "QTabBar::tab:selected{background:#16243a;color:#ffffff;border-bottom:2px solid #2684ff;}"
                "QTableWidget,QTreeWidget{background:#0e1728;alternate-background-color:#111d30;border:1px solid #22314a;border-radius:7px;gridline-color:#1d2b42;outline:0;}"
                "QTableWidget::item,QTreeWidget::item{padding:7px;}QTableWidget::item:selected,QTreeWidget::item:selected{background:#183b66;color:white;}"
                "QHeaderView::section{background:#16243a;color:#91a5bf;padding:8px;border:0;border-right:1px solid #22314a;font-weight:600;}"
                "QDockWidget{color:#dce7f5;font-weight:600;}QDockWidget::title{background:#111b2e;padding:8px;border-bottom:1px solid #22314a;}"
                "QSplitter::handle{background:#22314a;}QScrollBar{background:#0e1728;width:10px;height:10px;}QScrollBar::handle{background:#334760;border-radius:5px;}"
            )
        else:
            background = "#f6f8fb"
            foreground = "#334155"
            style = (
                "QMainWindow,QWidget{background:#f6f8fb;color:#263548;font-family:'Segoe UI';font-size:13px;}"
                "QMenuBar,QMenu,QToolBar,QStatusBar{background:#ffffff;color:#263548;border:0;}"
                "QMenuBar{padding:4px;}QToolBar{padding:7px 12px;spacing:5px;border-bottom:1px solid #dbe3ee;}"
                "QToolButton,QPushButton{background:#ffffff;color:#263548;border:1px solid #cbd6e4;border-radius:6px;padding:7px 12px;}"
                "QToolButton:hover,QPushButton:hover{background:#edf4ff;border-color:#3b82f6;color:#155ec4;}"
                "QPushButton#primaryButton{background:#1677ff;border-color:#1677ff;color:white;font-weight:600;padding:9px 18px;}"
                "QPushButton#primaryButton:hover{background:#0969da;}"
                "QFrame#connectionCard{background:#ffffff;border:1px solid #d9e2ee;border-radius:10px;}"
                "QLabel#eyebrow{color:#1677ff;font-size:10px;font-weight:700;letter-spacing:1px;}"
                "QLabel#connectionSummary,QLabel#pageTitle{font-size:17px;font-weight:600;color:#152238;}"
                "QLabel#fieldLabel,QLabel#muted{color:#708198;font-size:11px;}"
                "QLineEdit,QComboBox,QSpinBox,QPlainTextEdit{background:#ffffff;border:1px solid #cbd6e4;border-radius:6px;padding:7px;color:#1f2d3d;selection-color:#ffffff;selection-background-color:#1677ff;}"
                "QTableWidget QLineEdit#tableEditor,QTableWidget QComboBox#tableEditor,QTableWidget QDoubleSpinBox#tableEditor{background:#ffffff;color:#172033;border:1px solid #1677ff;border-radius:5px;padding:2px 6px;margin:0;selection-color:#ffffff;selection-background-color:#1677ff;}"
                "QLineEdit:focus,QComboBox:focus,QSpinBox:focus{border-color:#1677ff;}"
                "QComboBox QAbstractItemView{background:#ffffff;border:1px solid #cbd6e4;selection-background-color:#dbeafe;selection-color:#172033;}"
                "QTabWidget::pane{border:1px solid #dbe3ee;border-radius:8px;background:#ffffff;}"
                "QTabBar::tab{background:#edf1f6;color:#64748b;padding:10px 20px;border:0;}"
                "QTabBar::tab:selected{background:#ffffff;color:#172033;border-bottom:2px solid #1677ff;}"
                "QTableWidget,QTreeWidget{background:#ffffff;alternate-background-color:#f7f9fc;border:1px solid #dbe3ee;border-radius:7px;gridline-color:#e4eaf2;outline:0;}"
                "QTableWidget::item,QTreeWidget::item{padding:7px;}QTableWidget::item:selected,QTreeWidget::item:selected{background:#dbeafe;color:#172033;}"
                "QHeaderView::section{background:#edf2f7;color:#52657d;padding:8px;border:0;border-right:1px solid #dbe3ee;font-weight:600;}"
                "QDockWidget{color:#263548;font-weight:600;}QDockWidget::title{background:#ffffff;padding:8px;border-bottom:1px solid #dbe3ee;}"
                "QSplitter::handle{background:#dbe3ee;}QScrollBar{background:#f3f6fa;width:10px;height:10px;}QScrollBar::handle{background:#b8c5d5;border-radius:5px;}"
            )
        pg.setConfigOption("background", background)
        pg.setConfigOption("foreground", foreground)
        self.setStyleSheet(style)
        if self.floating_scope is not None:
            self.floating_scope.setStyleSheet(style)
        self.plot.setBackground(background)
        for axis_name in ("bottom", "left"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(foreground)
            axis.setTextPen(foreground)
        value_color = QColor("#16835f" if theme == "light" else "#52d6a4")
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_VALUE)
            if item:
                item.setForeground(value_color)
        self._update_theme_action_text()

    def _update_theme_action_text(self) -> None:
        text = "切换浅色主题" if self.theme == "dark" else "切换深色主题"
        if hasattr(self, "theme_action"):
            self.theme_action.setText(text)
        if hasattr(self, "toolbar_theme_action"):
            self.toolbar_theme_action.setText("浅色主题" if self.theme == "dark" else "深色主题")

    def _scan_quick_configs(self) -> None:
        interfaces = discover_configs(self.project.connection.executable, "interface")
        targets = discover_configs(self.project.connection.executable, "target")
        self._set_combo_items(
            self.quick_interface, interfaces, self.project.connection.interface_config
        )
        self._set_combo_items(self.quick_target, targets, self.project.connection.target_config)
        self._update_connection_summary(len(interfaces), len(targets))

    @staticmethod
    def _set_combo_items(combo: QComboBox, items: list[str], current: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        combo.setCurrentText(current)
        combo.blockSignals(False)

    def _update_connection_summary(self, interfaces: int = 0, targets: int = 0) -> None:
        root = find_scripts_root(self.project.connection.executable)
        if root:
            self.connection_summary.setText(
                f"OpenOCD 配置已就绪 · {interfaces} probes · {targets} targets"
            )
        else:
            self.connection_summary.setText("未发现 OpenOCD scripts，请检查高级设置")

    def _quick_config_changed(self) -> None:
        self.project.connection.interface_config = self.quick_interface.currentText().strip()
        self.project.connection.target_config = self.quick_target.currentText().strip()
        self.project.connection.sample_interval_ms = self.quick_interval.value()

    def configure_connection(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "连接设置", "请先断开当前目标，再修改连接设置。")
            return
        dialog = ConnectionDialog(self.project.connection, self)
        if dialog.exec():
            self.project.connection = dialog.config()
            self._sync_quick_controls()
            self._log("INFO", "连接与采集设置已更新")

    def _sync_quick_controls(self) -> None:
        self.quick_interval.blockSignals(True)
        self.quick_interval.setValue(self.project.connection.sample_interval_ms)
        self.quick_interval.blockSignals(False)
        self._scan_quick_configs()

    def open_symbol_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "加载 Keil/IAR 符号文件", "", "符号文件 (*.axf *.elf *.out);;所有文件 (*)"
        )
        if not path:
            return
        try:
            self.symbols = load_symbols(path)
        except SymbolError as exc:
            self._log("ERROR", str(exc))
            QMessageBox.critical(self, "符号加载失败", str(exc))
            return
        self.project.symbol_file = path
        self._filter_symbols()
        self.symbol_count.setText(f"{Path(path).name} · {len(self.symbols)} 个全局变量")
        self._log("INFO", f"加载符号文件 {path}，发现 {len(self.symbols)} 个变量")

    def _filter_symbols(self) -> None:
        query = self.symbol_search.text().strip().casefold()
        self.symbol_tree.clear()
        nodes: dict[str, QTreeWidgetItem] = {}
        shown = 0
        for symbol in self.symbols:
            type_label = symbol.data_type or f"{symbol.size} byte object"
            if query and query not in symbol.name.casefold() and query not in type_label.casefold():
                continue
            parent: QTreeWidgetItem | None = None
            path = ""
            for part in symbol_path_parts(symbol.name):
                path = (
                    f"{path}{part}" if part.startswith("[") else f"{path}.{part}" if path else part
                )
                item = nodes.get(path)
                if item is None:
                    item = QTreeWidgetItem(parent or self.symbol_tree, [part, "", ""])
                    nodes[path] = item
                parent = item
            if parent is None:
                continue
            item = parent
            item.setText(1, type_label)
            item.setText(2, f"0x{symbol.address:08X}")
            item.setData(0, Qt.UserRole, symbol)
            shown += 1
            if shown >= 3000:
                break

        for item in nodes.values():
            symbol = item.data(0, Qt.UserRole)
            if item.childCount() and isinstance(symbol, Symbol) and symbol.data_type is None:
                item.setData(0, Qt.UserRole, None)
            if item.childCount():
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
        if query:
            self.symbol_tree.expandAll()
        else:
            self.symbol_tree.expandToDepth(0)

    def _add_symbol_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        symbol = item.data(0, Qt.UserRole)
        if not isinstance(symbol, Symbol):
            item.setExpanded(not item.isExpanded())
            return
        self._show_variable_dialog(symbol)

    def add_variable(self) -> None:
        self._show_variable_dialog()

    def _show_variable_dialog(self, selected: Symbol | None = None) -> None:
        dialog = VariableDialog(self.symbols, self, selected)
        if dialog.exec():
            variable = dialog.variable(self.COLORS[len(self.project.variables) % len(self.COLORS)])
            if any(item.name == variable.name for item in self.project.variables):
                QMessageBox.warning(self, "变量重复", "变量名称必须唯一")
                return
            self.project.variables.append(variable)
            self._refresh_table()
            self._sync_worker_variables()
            self.workspace.setCurrentIndex(0)
            self._log("INFO", f"添加变量 {variable.name} @ 0x{variable.address:08X}")

    def remove_variable(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        variable = self.project.variables.pop(row)
        self._refresh_table()
        self._sync_worker_variables()
        self._log("INFO", f"移除变量 {variable.name}")

    def _toggle_connection(self) -> None:
        if self.worker and self.worker.isRunning():
            self.disconnect_target()
        else:
            self.connect_target()

    def connect_target(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self._quick_config_changed()
        self.worker = SamplerThread(
            copy.deepcopy(self.project.connection), copy.deepcopy(self.project.variables), self
        )
        self.worker.sample_ready.connect(self._sample_received)
        self.worker.connected.connect(self._connected)
        self.worker.failed.connect(self._connection_failed)
        self.worker.command_result.connect(self._command_result)
        self.worker.stopped.connect(self._disconnected)
        self.status_connection.setText("正在连接")
        self.connect_button.setText("正在连接...")
        self.connect_button.setEnabled(False)
        self._log(
            "INFO",
            f"连接 {self.project.connection.interface_config} + {self.project.connection.target_config}",
        )
        self.worker.start()

    def disconnect_target(self) -> None:
        worker = self.worker
        if worker:
            worker.stop()
            if not worker.wait(6000):
                self._log("WARN", "正在等待采样线程安全退出...")
                worker.wait()
        self.worker = None
        self._disconnected()

    def _connected(self, endpoint: str) -> None:
        self.connect_button.setEnabled(True)
        self.connect_button.setText("断开连接")
        self.status_connection.setText("已连接")
        self._paused = False
        self.pause_button.setText("暂停采样")
        self._log("SUCCESS", f"OpenOCD Tcl RPC 已连接: {endpoint}")

    def _disconnected(self) -> None:
        self.connect_button.setEnabled(True)
        self.connect_button.setText("连接目标")
        self.status_connection.setText("未连接")

    def _connection_failed(self, message: str) -> None:
        self._error_count += 1
        self._log("ERROR", message)
        self.connect_button.setEnabled(True)
        self.connect_button.setText("连接目标")
        self.status_connection.setText("连接失败")
        QMessageBox.critical(self, "OpenOCD 错误", message)

    def send_target_command(self, command: str) -> None:
        if not self.worker or not self.worker.isRunning():
            self._log("WARN", f"目标未连接，无法执行: {command}")
            return
        self.worker.send_command(command)
        self._log("CMD", command)

    def _command_result(self, command: str, response: str) -> None:
        self._log("REPLY", f"{command}: {response or 'OK'}")

    def toggle_pause(self) -> None:
        if not self.worker:
            return
        self._paused = not self._paused
        self.worker.set_paused(self._paused)
        self.pause_button.setText("继续采样" if self._paused else "暂停采样")
        self.status_connection.setText("采样暂停" if self._paused else "已连接")
        self._log("INFO", "采样已暂停" if self._paused else "采样已继续")

    def write_value(self) -> None:
        row = self.table.currentRow()
        if row < 0 or not self.worker:
            QMessageBox.information(self, "写入值", "请连接目标并选中一个变量")
            return
        from PySide6.QtWidgets import QInputDialog

        variable = self.project.variables[row]
        value, accepted = QInputDialog.getDouble(
            self, "在线修改变量", f"{variable.name} ({variable.unit})", decimals=8
        )
        if accepted:
            self.worker.write_value(copy.deepcopy(variable), value)
            self._log("WRITE", f"{variable.name} = {value}")

    def clear_data(self) -> None:
        self.samples.clear()
        self.sample_arrivals.clear()
        for curve in self.curves.values():
            curve.setData([], [])
        self._update_stats()

    def export_data(self) -> None:
        if not self.samples:
            QMessageBox.information(self, "导出采样数据", "当前没有采样数据")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出采样数据",
            "samples.csv",
            "CSV 表格 (*.csv);;JSON 数据与元信息 (*.json)",
        )
        if not path:
            return
        if selected_filter.startswith("JSON") or Path(path).suffix.casefold() == ".json":
            if not Path(path).suffix:
                path += ".json"
            export_json(path, list(self.samples), self.project.variables)
            export_format = "JSON"
        else:
            if not Path(path).suffix:
                path += ".csv"
            export_csv(path, list(self.samples), [item.name for item in self.project.variables])
            export_format = "CSV"
        self._log("INFO", f"导出 {len(self.samples)} 行 {export_format} 数据到 {path}")

    def save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存项目", "project.ocscope", "Scope 项目 (*.ocscope)"
        )
        if path:
            save_project(path, self.project)
            self._log("INFO", f"项目已保存: {path}")

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开项目", "", "Scope 项目 (*.ocscope)")
        if not path:
            return
        try:
            project = load_project(path)
            symbols = load_symbols(project.symbol_file) if project.symbol_file else []
        except Exception as exc:  # noqa: BLE001 - project files are an external input boundary
            QMessageBox.critical(self, "项目加载失败", str(exc))
            return
        connection = project.connection
        if (
            connection.executable != "openocd"
            or connection.startup_commands
            or connection.extra_args
        ):
            answer = QMessageBox.warning(
                self,
                "项目包含可执行连接设置",
                "该项目可启动指定程序并向 OpenOCD 发送自定义命令。只应打开可信来源的项目。\n\n"
                f"程序: {connection.executable}\n"
                f"附加参数: {connection.extra_args or '无'}\n"
                f"启动命令: {connection.startup_commands or '无'}\n\n"
                "是否继续加载？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        if self.worker and self.worker.isRunning():
            self.disconnect_target()
        self.project = project
        self.symbols = symbols
        self.clear_data()
        self._sync_quick_controls()
        self._filter_symbols()
        self.symbol_count.setText(
            f"{Path(project.symbol_file).name} · {len(symbols)} 个全局变量"
            if project.symbol_file
            else "项目未设置符号文件"
        )
        self._refresh_table()
        self._log("INFO", f"项目已打开: {path}")

    def _refresh_table(self) -> None:
        self._updating_table = True
        self.table.setRowCount(len(self.project.variables))
        for row, variable in enumerate(self.project.variables):
            enabled = QTableWidgetItem()
            enabled.setFlags((enabled.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            enabled.setCheckState(Qt.Checked if variable.enabled else Qt.Unchecked)
            self.table.setItem(row, COL_ENABLED, enabled)
            values = [
                (COL_NAME, variable.name),
                (COL_VALUE, "—"),
                (COL_TYPE, variable.data_type),
                (COL_ADDRESS, f"0x{variable.address:08X}"),
                (COL_FORMAT, variable.display_format),
                (COL_UNIT, variable.unit),
                (COL_SCALE, str(variable.scale)),
                (COL_OFFSET, str(variable.offset)),
                (COL_COLOR, variable.color),
            ]
            for column, text in values:
                item = QTableWidgetItem(text)
                if column == COL_VALUE:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setForeground(QColor("#16835f" if self.theme == "light" else "#52d6a4"))
                if column == COL_COLOR:
                    item.setBackground(QColor(variable.color))
                    item.setForeground(QColor(variable.color))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
        self._updating_table = False
        self.watch_hint.setText(f"{len(self.project.variables)} 个变量 · 双击图线色块可更换颜色")
        self._rebuild_curves()

    def _table_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.row() >= len(self.project.variables):
            return
        variable = self.project.variables[item.row()]
        try:
            if item.column() == COL_ENABLED:
                variable.enabled = item.checkState() == Qt.Checked
            elif item.column() == COL_NAME:
                name = item.text().strip()
                if not name:
                    raise ValueError("变量名称不能为空")
                if any(
                    index != item.row() and other.name == name
                    for index, other in enumerate(self.project.variables)
                ):
                    raise ValueError("变量名称必须唯一")
                variable.name = name
            elif item.column() == COL_ADDRESS:
                variable.address = int(item.text(), 0)
            elif item.column() == COL_TYPE and item.text() in DATA_TYPES:
                variable.data_type = item.text()
            elif item.column() == COL_FORMAT and item.text() in {"auto", "dec", "hex", "bin"}:
                variable.display_format = item.text()
            elif item.column() == COL_UNIT:
                variable.unit = item.text().strip()
            elif item.column() == COL_SCALE:
                variable.scale = float(item.text())
                if variable.scale == 0:
                    raise ValueError("比例不能为 0")
            elif item.column() == COL_OFFSET:
                variable.offset = float(item.text())
        except ValueError as exc:
            QMessageBox.warning(self, "输入无效", str(exc))
            self._refresh_table()
            return
        self._rebuild_curves()
        self._sync_worker_variables()

    def _cell_double_clicked(self, row: int, column: int) -> None:
        if column != COL_COLOR:
            return
        variable = self.project.variables[row]
        color = QColorDialog.getColor(QColor(variable.color), self)
        if color.isValid():
            variable.color = color.name()
            self._refresh_table()

    def _sample_received(self, timestamp: float, values: dict[str, float | int]) -> None:
        self.samples.append({"time_s": timestamp, **values})
        now = time.monotonic()
        self.sample_arrivals.append(now)
        max_samples = max(
            1,
            self.project.connection.history_seconds
            * 1000
            // self.project.connection.sample_interval_ms,
        )
        while len(self.samples) > max_samples:
            self.samples.popleft()
        name_to_row = {item.name: index for index, item in enumerate(self.project.variables)}
        for name, value in values.items():
            if name in name_to_row:
                variable = self.project.variables[name_to_row[name]]
                self.table.item(name_to_row[name], COL_VALUE).setText(
                    self._format_value(value, variable)
                )
        if now - self._last_plot_update >= 0.033:
            self._update_plot()
            self._update_stats()
            self._last_plot_update = now

    @staticmethod
    def _format_value(value: float, variable: Variable) -> str:
        if variable.display_format == "hex":
            return f"0x{int(value):X}"
        if variable.display_format == "bin":
            return f"0b{int(value):b}"
        if variable.display_format == "dec":
            return str(int(value))
        return f"{value:.8g}"

    def _rebuild_curves(self) -> None:
        self.plot.clear()
        self.plot.addLegend(offset=(12, 12))
        self.curves = {}
        for variable in self.project.variables:
            if variable.enabled:
                self.curves[variable.name] = self.plot.plot(
                    [], [], pen=pg.mkPen(variable.color, width=2), name=variable.name
                )
        self._update_plot()
        self._update_stats()

    def _update_plot(self) -> None:
        rows = list(self.samples)
        latest = float(rows[-1]["time_s"]) if rows else 0.0
        for name, curve in self.curves.items():
            points = [(float(row["time_s"]), float(row[name])) for row in rows if name in row]
            if points:
                x, y = zip(*points)
                curve.setData(x, y)
        if rows:
            history = self.project.connection.history_seconds
            self.plot.setXRange(max(0, latest - history), max(history, latest), padding=0)
        if self.autoscale.isChecked():
            self.plot.enableAutoRange(axis="y", enable=True)

    def _update_stats(self) -> None:
        rows = list(self.samples)
        enabled = [item for item in self.project.variables if item.enabled]
        self.stats_table.setRowCount(len(enabled))
        for row_index, variable in enumerate(enabled):
            values = [float(row[variable.name]) for row in rows if variable.name in row]
            texts = [
                variable.name,
                f"{values[-1]:.8g}" if values else "—",
                f"{min(values):.8g}" if values else "—",
                f"{max(values):.8g}" if values else "—",
                variable.unit,
            ]
            for column, text in enumerate(texts):
                self.stats_table.setItem(row_index, column, QTableWidgetItem(text))

    def _update_metrics(self) -> None:
        now = time.monotonic()
        while self.sample_arrivals and self.sample_arrivals[0] < now - 1.0:
            self.sample_arrivals.popleft()
        self.status_rate.setText(f"{len(self.sample_arrivals):.1f} Sa/s")
        self.status_samples.setText(f"{len(self.samples)} samples")
        self.status_errors.setText(f"{self._error_count} errors")

    def _sync_worker_variables(self) -> None:
        if self.worker:
            self.worker.set_variables(copy.deepcopy(self.project.variables))

    def _log(self, level: str, message: str) -> None:
        timestamp = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S.%f")[:-3]
        self.log_view.appendPlainText(f"{timestamp}  {level:<7}  {message}")

    def closeEvent(self, event) -> None:
        if self.floating_scope is not None:
            self._restore_scope_page()
        self.disconnect_target()
        event.accept()
