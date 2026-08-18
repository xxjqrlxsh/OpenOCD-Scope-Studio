[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$Bootloader,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$App,

    [string]$Output = ".\merged.bin",

    [uint32]$AppOffset = 0x20000,

    [uint32]$BaseAddress = 0x08000000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$bootData = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Bootloader).Path)
$appData = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $App).Path)

if ($bootData.Length -gt $AppOffset) {
    throw ("Bootloader is 0x{0:X} bytes and overlaps the App offset 0x{1:X}." -f $bootData.Length, $AppOffset)
}

$outputLength = [int64]$AppOffset + $appData.Length
if ($outputLength -gt [int]::MaxValue) {
    throw "The merged BIN is too large to create in memory."
}

$mergedData = [byte[]]::new([int]$outputLength)
[Array]::Copy($bootData, 0, $mergedData, 0, $bootData.Length)

for ($index = $bootData.Length; $index -lt $AppOffset; $index++) {
    $mergedData[$index] = 0xFF
}

[Array]::Copy($appData, 0, $mergedData, $AppOffset, $appData.Length)

$outputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
$outputDirectory = [IO.Path]::GetDirectoryName($outputPath)
if (-not [IO.Directory]::Exists($outputDirectory)) {
    throw "Output directory does not exist: $outputDirectory"
}

[IO.File]::WriteAllBytes($outputPath, $mergedData)

$appAddress = [uint64]$BaseAddress + $AppOffset
$paddingLength = [int64]$AppOffset - $bootData.Length

Write-Host ("Created:      {0}" -f $outputPath)
Write-Host ("Bootloader:   0x{0:X8}, {1} bytes" -f $BaseAddress, $bootData.Length)
Write-Host ("App:          0x{0:X8}, {1} bytes" -f $appAddress, $appData.Length)
Write-Host ("0xFF padding: {0} bytes" -f $paddingLength)
Write-Host ("Output size:  {0} bytes (0x{0:X})" -f $mergedData.Length)
