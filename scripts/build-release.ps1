# Builds the Windows release zip, dist\fusion-freecad-<version>-windows.zip, to upload
# to a GitHub release by hand. It holds the committed addon and MCP server (HEAD, not
# uncommitted edits), every add-on from addons.json at its pinned commit, and
# Install.cmd, which runs scripts\install-addon.ps1 in release mode (copies, no git).
#
#   powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
#
# Needs git and Windows 10's tar.

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")

$version = ([xml](Get-Content (Join-Path $repo "addon\FusionFreeCAD\package.xml") -Raw)).package.version
$name = "fusion-freecad-$version-windows"
$dist = Join-Path $repo "dist"
$staging = Join-Path $dist $name
$zip = Join-Path $dist "$name.zip"

if (git -C $repo status --porcelain) {
    Write-Warning "Uncommitted changes are not included; the zip is built from HEAD."
}
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
if (Test-Path $zip) { Remove-Item -Force $zip }
New-Item -ItemType Directory -Force $staging | Out-Null

# --- our files, as committed ----------------------------------------------------

$tarball = Join-Path $dist "$name.tar"
git -C $repo archive --format=tar -o $tarball HEAD `
    addon mcp-server/src mcp-server/pyproject.toml mcp-server/uv.lock mcp-server/README.md `
    scripts/install-addon.ps1 addons.json README.md
if ($LASTEXITCODE -ne 0) { throw "git archive failed" }
tar -x -f $tarball -C $staging
Remove-Item $tarball

Set-Content -Path (Join-Path $staging "Install.cmd") -Encoding ascii -Value @'
@echo off
rem Installs Fusion FreeCAD and its add-ons into FreeCAD. Options, e.g. -Addons all,
rem are passed on to scripts\install-addon.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-addon.ps1" %*
pause
'@

# --- add-ons at their pinned commits ----------------------------------------------

$manifest = Get-Content (Join-Path $repo "addons.json") -Raw | ConvertFrom-Json
foreach ($addon in $manifest.addons) {
    $dir = Join-Path $staging "addons\$($addon.name)"
    New-Item -ItemType Directory -Force $dir | Out-Null
    git -C $dir init --quiet
    git -C $dir remote add origin $addon.url
    git -C $dir fetch --quiet --depth 1 origin $addon.rev
    if ($LASTEXITCODE -ne 0) { throw "Could not fetch $($addon.name) at $($addon.rev)" }
    git -C $dir checkout --quiet --detach FETCH_HEAD
    Remove-Item -Recurse -Force (Join-Path $dir ".git")
    # install-addon.ps1 reads this to tell which commit a copied add-on is at.
    Set-Content -Path (Join-Path $dir ".fusion-freecad-rev") -Value $addon.rev -Encoding ascii
    Write-Host "  $($addon.name) ($($addon.rev.Substring(0,7)))"
}

# --- zip ---------------------------------------------------------------------------

tar -a -c -f $zip -C $dist $name
if ($LASTEXITCODE -ne 0) { throw "tar failed" }
Remove-Item -Recurse -Force $staging
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Built $zip ($size MB)"
