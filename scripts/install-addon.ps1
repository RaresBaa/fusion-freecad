# Links addon/FusionFreeCAD into FreeCAD's user Mod folder (Windows).
# A directory junction means edits in the repo take effect on FreeCAD's next start.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-addon.ps1 [-ModDir <path>] [-Uninstall]

param(
    [string]$ModDir,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$source = Resolve-Path (Join-Path $PSScriptRoot "..\addon\FusionFreeCAD")

if (-not $ModDir) {
    # FreeCAD 1.1+ keeps user data per version (v1-1, v1-2, ...); use the newest.
    $root = Join-Path $env:APPDATA "FreeCAD"
    $versioned = Get-ChildItem $root -Directory -Filter "v*" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    $base = if ($versioned) { $versioned.FullName } else { $root }
    $ModDir = Join-Path $base "Mod"
}

$target = Join-Path $ModDir "FusionFreeCAD"

if (Test-Path $target) {
    $item = Get-Item $target -Force
    if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "$target exists and is a real folder, not a link. Remove it yourself first."
    }
    # Removing a junction deletes the link only, never the repo files.
    $item.Delete()
    Write-Host "Removed existing link $target"
}

if ($Uninstall) { return }

New-Item -ItemType Directory -Force $ModDir | Out-Null
New-Item -ItemType Junction -Path $target -Target $source | Out-Null
Write-Host "Linked $target -> $source"
Write-Host "Restart FreeCAD and pick the 'Fusion' workbench."
