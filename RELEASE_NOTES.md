# OpenOCD Scope Studio 0.2.1

J-Link compatibility fix for Windows 10/11 x64.

## Highlights

- Added a native SEGGER J-Link backend; no WinUSB driver replacement is required.
- Automatically uses installed `JLink_x64.dll` for `interface/jlink.cfg`.
- Verified native SWD connection and memory access on STM32F4 hardware.
- Fixed J-Link + GD32F3 OpenOCD transport by selecting SWD explicitly.
- Added the correct Cortex-M4 TAP IDs for explicit SWD and JTAG modes.
- Connection timeout errors now include actionable OpenOCD process output.
- OpenOCD-based live variable monitoring and online writes.
- Keil AXF/ELF and IAR ELF/DWARF symbol loading.
- Nested structure and array member expansion.
- Detachable real-time oscilloscope with CSV export.
- Searchable probe/target configurations and GD32F3 compatibility presets.
- Dark and light themes, project persistence, and diagnostic logs.
- Bootloader/application BIN firmware merge utility.
- Expandable structure, nested member, and array symbol trees.
- CSV table export and JSON export with complete variable metadata.
- Direct standalone EXE download in addition to the complete Windows ZIP.

## Requirements

- OpenOCD 0.12.x installed separately.
- A supported debug probe such as ST-Link, J-Link, or CMSIS-DAP.

## Verification

The release candidate passes the automated test suite, Ruff checks, a real OpenOCD Tcl RPC error-handling test, and a packaged EXE startup smoke test.

GD32 presets have been syntax-tested with OpenOCD but still require validation on each target board and probe combination.
