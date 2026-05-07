# SDM120 / Victron VEConfigure prep — runs inside the Win11 VM.
# Downloads + silently installs VEConfigure 3 and the MK3-USB FTDI driver.

$ErrorActionPreference = 'Stop'
$tmp = "$env:TEMP\victron-installers"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

function DL($url, $name) {
  $out = Join-Path $tmp $name
  Write-Host "Downloading $name..."
  Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
  return $out
}

# VEConfigure 3 main app (current canonical URL as of 2026-05)
$ve = DL "https://www.victronenergy.com/Executables/VEConfig/VECSetup_A.exe" "VECSetup_A.exe"

# MK3-USB uses an FTDI chip — Victron-bundled FTDI driver
$ftdi = DL "https://www.victronenergy.com/Executables/VEConfig/CDM21216_Setup.exe" "CDM21216_Setup.exe"

Write-Host "Installing VEConfigure 3 (silent)..."
Start-Process -FilePath $ve -ArgumentList "/S" -Wait

Write-Host "Installing FTDI driver (silent)..."
Start-Process -FilePath $ftdi -ArgumentList "/quiet" -Wait

Write-Host ""
Write-Host "=== Done ==="
Write-Host "VEConfigure should appear in Start menu."
Write-Host "MK3-USB will enumerate as a COM port when plugged in."
