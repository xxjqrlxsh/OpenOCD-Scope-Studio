# OpenOCD Scope Studio

基于 OpenOCD 的可调式嵌入式变量监视、实时波形与数据导出桌面软件。首版面向 Windows，兼容 OpenOCD 支持的 ST-Link、J-Link、CMSIS-DAP 等调试器。

## 当前功能

- 启动本机 OpenOCD，或连接已运行的 Tcl RPC 服务
- 自动定位 OpenOCD `scripts`，提供可搜索的调试器和目标芯片下拉选择
- 内置 GD32F303/F305/F307 与 GD32F330/F350 兼容目标预设
- 支持传输协议、适配器速度和自定义启动命令
- 加载 Keil `AXF/ELF` 与 IAR `ELF/DWARF OUT` 全局变量符号
- 递归展开 DWARF 结构体、嵌套结构体、联合体和数组成员，例如 `motor.pid.kp`
- FreeMASTER 风格工作区：符号浏览器、变量监视、实时示波器和事件诊断
- 符号搜索和双击添加变量，支持显示格式、工程单位、比例与偏移
- 手工输入绝对地址，支持无符号文件调试
- `int8/16/32/64`、`uint8/16/32/64`、`float`、`double` 及大小端
- 可调采样周期、历史时长、比例和偏移
- 多变量实时曲线、暂停、清空、变量在线改值
- 实时采样率、样本数、错误数和通道当前/最小/最大值统计
- 目标复位、暂停和继续运行控制
- Bootloader 与 App BIN 固件合并，支持地址布局和 0xFF 间隙填充
- 保存/加载项目配置，导出 Excel 友好的 UTF-8 CSV
- 图形化合并 Bootloader 与 App BIN，自动检查重叠并用 `0xFF` 填充分区空白
- UI 与采样线程分离，OpenOCD 通信不会阻塞界面

> IAR 的私有 UBROF 文件不能由通用 ELF 解析器读取。请在 IAR 链接器选项中输出 ELF/DWARF 格式，或使用手工地址。

## 安装运行

支持 Windows 10/11 x64。需要 Python 3.10+ 和 OpenOCD 0.12.x：

```powershell
python -m pip install -e .
python -m openocd_scope
```

也可以直接运行已构建的 Windows 程序：

```text
dist\OpenOCD-Scope.exe
```

重新生成单文件 EXE：

```powershell
powershell -ExecutionPolicy Bypass -File .\build-exe.ps1
```

EXE 包含应用运行环境，但不重复打包 OpenOCD。请先安装 OpenOCD 并确保命令行能运行
`openocd --version`，或在软件“连接设置”中选择 `openocd.exe` 的完整路径。

开发与测试：

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```

## 快速使用

1. 在顶部连接区搜索并选择调试器和目标芯片，例如 `interface/stlink.cfg` 与 `target/stm32f4x.cfg`。若没有选项，在“高级设置”中指定 `openocd.exe`。
2. 加载 Keil/IAR 生成的符号文件。
3. 在左侧符号浏览器搜索并双击变量，或手工添加地址。带 DWARF 调试信息时会展开结构体和数组并自动识别基础类型；只有普通符号表时，同尺寸整数和浮点仍需按源代码选择。
4. 连接目标后开始采样。双击颜色单元格可改曲线颜色，选中变量后可在线写值。
5. 使用“保存项目”和“导出 CSV”保留配置或数据。

若由 Keil/IAR 占用同一个硬件调试器，OpenOCD 无法同时打开设备。可停止 IDE 调试后连接，或让 IDE 通过 OpenOCD GDB Server 调试。AXF/OUT 仅用于符号解析，不要求 IDE 正在运行。

## 项目结构

- `src/openocd_scope/openocd.py`：OpenOCD 进程和 Tcl RPC 协议
- `src/openocd_scope/symbols.py`：AXF/ELF/OUT 符号解析
- `src/openocd_scope/sampler.py`：后台采样与安全写值
- `src/openocd_scope/ui.py`：PySide6 主界面和交互
- `src/openocd_scope/storage.py`：项目和 CSV 存储
- `src/openocd_scope/binmerge.py`：Bootloader/App BIN 固件合并

## 后续增强方向

- 连续地址合并读取，提高多变量采样率
- GDB/MI 表达式模式，支持结构体成员、指针和 C 表达式
- 触发器、游标测量、统计值、告警与数据回放
- SWO/RTT 高速采样和插件式协议后端

## 安全与许可证

`.ocscope` 项目可以指定 OpenOCD 程序、参数和启动命令，只应加载可信来源的项目文件。安全报告方式见 `SECURITY.md`。

本项目采用 GPL-3.0-only，完整条款见 `LICENSE`。Windows 发行包包含的依赖及许可证见 `THIRD_PARTY_NOTICES.md`。

本项目是独立实现，仅参考 LinkScope 的产品功能和交互思路，不复制其 GPL 源代码。
