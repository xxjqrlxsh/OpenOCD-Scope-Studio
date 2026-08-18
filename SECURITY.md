# Security Policy

## Supported Version

Security fixes are currently provided for the latest `0.1.x` release only.

## Reporting

Report vulnerabilities privately through the repository's GitHub Security Advisory page. Do not include firmware, symbol files, credentials, or proprietary project files in a public issue.

## Trusted Inputs

Only open `.ocscope`, ELF, AXF, and IAR OUT files from trusted sources. A project file can select an executable and supply OpenOCD startup commands. The application displays a confirmation before loading projects that contain custom executable or command settings.
