#!/usr/bin/env sh
# Links addon/FusionFreeCAD into FreeCAD's user Mod folder (Linux / macOS).
# A symlink means edits in the repo take effect on FreeCAD's next start.
#
#   scripts/install-addon.sh [--uninstall] [MOD_DIR]
set -eu

uninstall=0
if [ "${1:-}" = "--uninstall" ]; then uninstall=1; shift; fi

repo=$(cd "$(dirname "$0")/.." && pwd)
source="$repo/addon/FusionFreeCAD"

if [ $# -ge 1 ]; then
    mod_dir=$1
else
    case "$(uname -s)" in
        Darwin) root="$HOME/Library/Application Support/FreeCAD" ;;
        *)      root="${XDG_DATA_HOME:-$HOME/.local/share}/FreeCAD" ;;
    esac
    # Flatpak FreeCAD keeps its data in its sandbox.
    flatpak_root="$HOME/.var/app/org.freecad.FreeCAD/data/FreeCAD"
    if [ ! -d "$root" ] && [ -d "$flatpak_root" ]; then root=$flatpak_root; fi
    # FreeCAD 1.1+ keeps user data per version (v1-1, v1-2, ...); use the newest.
    newest=$(ls -d "$root"/v* 2>/dev/null | sort | tail -n 1 || true)
    mod_dir="${newest:-$root}/Mod"
fi

target="$mod_dir/FusionFreeCAD"

if [ -L "$target" ]; then
    rm "$target"
    echo "Removed existing link $target"
elif [ -e "$target" ]; then
    echo "$target exists and is not a symlink; remove it yourself first." >&2
    exit 1
fi

[ "$uninstall" = 1 ] && exit 0

mkdir -p "$mod_dir"
ln -s "$source" "$target"
echo "Linked $target -> $source"
echo "Restart FreeCAD and pick the 'Fusion' workbench."
