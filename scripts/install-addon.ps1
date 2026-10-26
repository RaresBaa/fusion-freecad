# Installs Fusion FreeCAD into FreeCAD's user Mod folder (Windows):
#  - links addon/FusionFreeCAD (a junction, so repo edits apply on FreeCAD's next start)
#  - clones the add-ons listed in addons.json at their pinned commits
#  - installs their Python packages where FreeCAD looks for them
#
# From a release zip (scripts/build-release.ps1) it copies instead: the addon, the
# add-ons bundled in addons\ (no git needed) and the MCP server, to
# %LOCALAPPDATA%\fusion-freecad\mcp-server, so the extracted folder can be deleted.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-addon.ps1 [options]
#
#   -Addons default|minimal|all|none   which add-ons (default: required + recommended;
#                                      minimal: required; all: also Ribbon and PieMenu)
#   -Update                            move already installed add-ons to the pinned commit
#   -ModDir <path>                     FreeCAD's Mod folder (default: newest user profile)
#   -FreeCADDir <path>                 FreeCAD install (default: newest in Program Files)
#   -Uninstall                         remove Fusion FreeCAD (add-ons are kept)

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
# Release zips bundle the add-ons; a git checkout clones them.
$bundled = Join-Path $repo "addons"
$release = Test-Path $bundled
# Marks folders this script copied (holds the add-on's commit), so they can be replaced.
$marker = ".fusion-freecad-rev"

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
$mcpTarget = Join-Path $env:LOCALAPPDATA "fusion-freecad\mcp-server"
if (Test-Path $target) {
    $item = Get-Item $target -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        # Removing a junction deletes the link only, never the repo files.
        $item.Delete()
        Write-Host "Removed existing link $target"
    } elseif (Test-Path (Join-Path $target $marker)) {
        Remove-Item -Recurse -Force $target
        Write-Host "Removed existing copy $target"
    } else {
        throw "$target exists and is a real folder this script didn't make. Remove it yourself first."
    }
}
if ($Uninstall) {
    if (Test-Path $mcpTarget) {
        Remove-Item -Recurse -Force $mcpTarget
        Write-Host "Removed $mcpTarget"
    }
    return
}

New-Item -ItemType Directory -Force $ModDir | Out-Null
if ($release) {
    Copy-Item -Recurse $source $target
    Set-Content -Path (Join-Path $target $marker) -Value "release" -Encoding ascii
    Write-Host "Copied Fusion FreeCAD to $target"
} else {
    New-Item -ItemType Junction -Path $target -Target $source | Out-Null
    Write-Host "Linked $target -> $source"
}

# --- add-ons ----------------------------------------------------------------------

$sets = @{
    "none" = @(); "minimal" = @("required"); "default" = @("required", "recommended");
    "all" = @("required", "recommended", "ui")
}[$Addons]
$manifest = Get-Content (Join-Path $repo "addons.json") -Raw | ConvertFrom-Json
$selected = @($manifest.addons | Where-Object { $sets -contains $_.set })
$pythonPackages = @()

function Install-Addon($addon, $dir) {
    $copy = Join-Path $bundled $addon.name
    if ($release -and (Test-Path $copy)) {
        Copy-Item -Recurse $copy $dir
        return
    }
    New-Item -ItemType Directory -Force $dir | Out-Null
    git -C $dir init --quiet
    git -C $dir remote add origin $addon.url
    git -C $dir fetch --quiet --depth 1 origin $addon.rev
    git -C $dir checkout --quiet --detach FETCH_HEAD
}

foreach ($addon in $selected) {
    $dir = Join-Path $ModDir $addon.name
    $pythonPackages += $addon.python
    if (Test-Path $dir) {
        $git = Test-Path (Join-Path $dir ".git")
        $copied = Join-Path $dir $marker
        if ($git) {
            $current = (git -C $dir rev-parse HEAD).Trim()
        } elseif (Test-Path $copied) {
            $current = (Get-Content $copied -Raw).Trim()
        } else {
            Write-Host "  $($addon.name): already installed (not by this script), skipped"
            continue
        }
        if ($current -eq $addon.rev) {
            Write-Host "  $($addon.name): up to date"
            continue
        }
        if (-not $Update) {
            Write-Host "  $($addon.name): installed at $($current.Substring(0,7)), tested with $($addon.rev.Substring(0,7)) (use -Update to switch)"
            continue
        }
        if ($git -and -not $release) {
            git -C $dir fetch --quiet --depth 1 origin $addon.rev
            git -C $dir checkout --quiet --detach FETCH_HEAD
        } else {
            Remove-Item -Recurse -Force $dir
            Install-Addon $addon $dir
        }
        Write-Host "  $($addon.name): updated to $($addon.rev.Substring(0,7))"
        continue
    }
    Install-Addon $addon $dir
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

# --- MCP server (release only; a checkout runs it from mcp-server\) -----------------

$mcpSource = Join-Path $repo "mcp-server"
if ($release) {
    if (Test-Path $mcpTarget) { Remove-Item -Recurse -Force $mcpTarget }
    New-Item -ItemType Directory -Force (Split-Path $mcpTarget -Parent) | Out-Null
    Copy-Item -Recurse $mcpSource $mcpTarget
    $mcpSource = $mcpTarget
    Write-Host "Copied the MCP server to $mcpTarget"
}

Write-Host "Done. Restart FreeCAD and pick the 'Fusion' workbench."
Write-Host "To connect Claude Code (needs uv, https://docs.astral.sh/uv/):"
Write-Host "  claude mcp add --scope user freecad -- uv --directory `"$mcpSource`" run fusion-freecad-mcp"
