# Changelog

## 0.2.1 - 2026-08-20

- Added a native SEGGER J-Link backend that works with the standard Windows driver.
- Automatically selects the native backend for `interface/jlink.cfg`.
- Fixed J-Link connections to built-in GD32F3 targets when OpenOCD is forced.
- Added transport-specific SWD and JTAG TAP IDs for GD32F303/F305/F307.
- Added complete OpenOCD process output to connection timeout errors.

## 0.2.0 - 2026-08-18

- Replaced the flat symbol list with expandable structure and array trees.
- Added JSON capture export with variable types, addresses, units, and scaling metadata.
- Kept Excel-compatible CSV export for tabular analysis.
- Added direct EXE assets to automated GitHub releases.

## 0.1.0 - 2026-08-18

- Added OpenOCD Tcl RPC sampling and target control.
- Added Keil AXF/ELF and IAR ELF/DWARF symbol loading.
- Added nested structure, union, and array member expansion.
- Added variable watch, online writes, CSV export, and project files.
- Added real-time and detachable oscilloscope views.
- Added dark/light themes and searchable OpenOCD configurations.
- Added GD32F303/F305/F307 and GD32F330/F350 compatibility presets.
- Added Bootloader and application BIN firmware merging.
