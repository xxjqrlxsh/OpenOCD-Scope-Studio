# OpenOCD Scope Studio 0.1.0

Initial private release for Windows 10/11 x64.

## Highlights

- OpenOCD-based live variable monitoring and online writes.
- Keil AXF/ELF and IAR ELF/DWARF symbol loading.
- Nested structure and array member expansion.
- Detachable real-time oscilloscope with CSV export.
- Searchable probe/target configurations and GD32F3 compatibility presets.
- Dark and light themes, project persistence, and diagnostic logs.
- Bootloader/application BIN firmware merge utility.

## Requirements

- OpenOCD 0.12.x installed separately.
- A supported debug probe such as ST-Link, J-Link, or CMSIS-DAP.

## Verification

The release candidate passed 22 automated tests, Ruff checks, a real OpenOCD Tcl RPC error-handling test, and a packaged EXE startup smoke test.

GD32 presets have been syntax-tested with OpenOCD but still require validation on each target board and probe combination.
