# Installs Fusion FreeCAD into FreeCAD's user Mod folder (Windows):
#  - links addon/FusionFreeCAD (a junction, so repo edits apply on FreeCAD's next start)
#  - clones the add-ons listed in addons.json at their pinned commits
#  - installs their Python packages where FreeCAD looks for them
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-addon.ps1 [options]
#
#   -Addons default|minimal|all|none   which add-ons (default: required + recommended;
#                                      minimal: required; all: also Ribbon and PieMenu)
#   -Update                            move already installed add-ons to the pinned commit
#   -ModDir <path>                     FreeCAD's Mod folder (default: newest user profile)
#   -FreeCADDir <path>                 FreeCAD install (default: newest in Program Files)
#   -Uninstall                         remove the Fusion FreeCAD link (add-ons are kept)

param(
    [ValidateSet("default", "minimal", "all", "none")]
    [string]$Addons = "default",
    [switch]$Update,
    [string]$ModDir,
    [string]$FreeCADDir,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$source = Join-Path $repo "addon\FusionFreeCAD"

if (-not $ModDir) {
    # FreeCAD 1.1+ keeps user data per version (v1-1, v1-2, ...); use the newest.
    $root = Join-Path $env:APPDATA "FreeCAD"
    $versioned = Get-ChildItem $root -Directory -Filter "v*" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    $base = if ($versioned) { $versioned.FullName } else { $root }
    $ModDir = Join-Path $base "Mod"
}
$userData = Split-Path $ModDir -Parent

# --- Fusion FreeCAD itself -----------------------------------------------------

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

# --- add-ons ----------------------------------------------------------------------

$sets = @{
    "none" = @(); "minimal" = @("required"); "default" = @("required", "recommended");
    "all" = @("required", "recommended", "ui")
}[$Addons]
$manifest = Get-Content (Join-Path $repo "addons.json") -Raw | ConvertFrom-Json
$selected = @($manifest.addons | Where-Object { $sets -contains $_.set })
$pythonPackages = @()

foreach ($addon in $selected) {
    $dir = Join-Path $ModDir $addon.name
    $pythonPackages += $addon.python
    if (Test-Path $dir) {
        if (-not (Test-Path (Join-Path $dir ".git"))) {
            Write-Host "  $($addon.name): already installed (not a git checkout), skipped"
            continue
        }
        $current = (git -C $dir rev-parse HEAD).Trim()
        if ($current -eq $addon.rev) {
            Write-Host "  $($addon.name): up to date"
            continue
        }
        if (-not $Update) {
            Write-Host "  $($addon.name): installed at $($current.Substring(0,7)), tested with $($addon.rev.Substring(0,7)) (use -Update to switch)"
            continue
        }
        git -C $dir fetch --quiet --depth 1 origin $addon.rev
        git -C $dir checkout --quiet --detach FETCH_HEAD
        Write-Host "  $($addon.name): updated to $($addon.rev.Substring(0,7))"
        continue
    }
    New-Item -ItemType Directory -Force $dir | Out-Null
    git -C $dir init --quiet
    git -C $dir remote add origin $addon.url
    git -C $dir fetch --quiet --depth 1 origin $addon.rev
    git -C $dir checkout --quiet --detach FETCH_HEAD
    Write-Host "  $($addon.name): installed ($($addon.rev.Substring(0,7)))"
}

# --- Python packages the add-ons need -------------------------------------------

$pythonPackages = @($pythonPackages | Where-Object { $_ } | Sort-Object -Unique)
if ($pythonPackages.Count -gt 0) {
    if (-not $FreeCADDir) {
        $FreeCADDir = Get-ChildItem (Join-Path $env:ProgramFiles "FreeCAD*") -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
    $python = if ($FreeCADDir) { Join-Path $FreeCADDir "bin\python.exe" } else { $null }
    if (-not $python -or -not (Test-Path $python)) {
        Write-Warning "FreeCAD's python.exe not found; install these with the Addon Manager: $($pythonPackages -join ', ')"
    } else {
        $tag = (& $python -c "import sys; print('py%d%d' % sys.version_info[:2])").Trim()
        $packagesDir = Join-Path $userData "AdditionalPythonPackages\$tag"
        # Only install what FreeCAD doesn't already have (bundled or installed earlier).
        $env:PYTHONPATH = $packagesDir
        $missing = @($pythonPackages | Where-Object {
            & $python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$_') else 1)"
            $LASTEXITCODE -ne 0 })
        Remove-Item Env:PYTHONPATH
        if ($missing.Count -gt 0) {
            New-Item -ItemType Directory -Force $packagesDir | Out-Null
            & $python -m pip install --quiet --upgrade --target $packagesDir @missing
            Write-Host "Installed Python packages into ${packagesDir}: $($missing -join ', ')"
        }
    }
}

Write-Host "Done. Restart FreeCAD and pick the 'Fusion' workbench."
