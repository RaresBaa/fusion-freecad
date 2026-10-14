#!/usr/bin/env sh
# Installs Fusion FreeCAD into FreeCAD's user Mod folder (Linux / macOS):
#  - symlinks addon/FusionFreeCAD (repo edits apply on FreeCAD's next start)
#  - clones the add-ons listed in addons.json at their pinned commits
#  - installs their Python packages where FreeCAD looks for them
# On NixOS use the flake instead (see docs/nix.md).
#
#   scripts/install-addon.sh [--addons default|minimal|all|none] [--update]
#                            [--uninstall] [MOD_DIR]
set -eu

addons=default
update=0
uninstall=0
mod_dir=
while [ $# -gt 0 ]; do
    case "$1" in
        --addons) addons=$2; shift 2 ;;
        --update) update=1; shift ;;
        --uninstall) uninstall=1; shift ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) mod_dir=$1; shift ;;
    esac
done
case "$addons" in
    none) sets="" ;;
    minimal) sets="required" ;;
    default) sets="required recommended" ;;
    all) sets="required recommended ui" ;;
    *) echo "--addons must be default, minimal, all or none" >&2; exit 2 ;;
esac

repo=$(cd "$(dirname "$0")/.." && pwd)
source="$repo/addon/FusionFreeCAD"

if [ -z "$mod_dir" ]; then
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
user_data=$(dirname "$mod_dir")

# --- Fusion FreeCAD itself -------------------------------------------------------

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

# --- add-ons ------------------------------------------------------------------------

# One "name set url rev python1,python2" line per add-on, from addons.json.
list=$(python3 - "$repo/addons.json" <<'EOF'
import json, sys
for a in json.load(open(sys.argv[1]))["addons"]:
    print(a["name"], a["set"], a["url"], a["rev"], ",".join(a["python"]) or "-")
EOF
)
list=$(echo "$list" | tr -d '\r')

echo "$list" | while read -r name set url rev py; do
    case " $sets " in *" $set "*) ;; *) continue ;; esac
    dir="$mod_dir/$name"
    short=$(printf '%.7s' "$rev")
    if [ -d "$dir" ]; then
        if [ ! -d "$dir/.git" ]; then
            echo "  $name: already installed (not a git checkout), skipped"; continue
        fi
        current=$(git -C "$dir" rev-parse HEAD)
        if [ "$current" = "$rev" ]; then echo "  $name: up to date"; continue; fi
        if [ "$update" != 1 ]; then
            echo "  $name: installed at $(printf '%.7s' "$current"), tested with $short (use --update to switch)"
            continue
        fi
        git -C "$dir" fetch --quiet --depth 1 origin "$rev"
        git -C "$dir" checkout --quiet --detach FETCH_HEAD
        echo "  $name: updated to $short"
        continue
    fi
    mkdir -p "$dir"
    git -C "$dir" init --quiet
    git -C "$dir" remote add origin "$url"
    git -C "$dir" fetch --quiet --depth 1 origin "$rev"
    git -C "$dir" checkout --quiet --detach FETCH_HEAD
    echo "  $name: installed ($short)"
done

# --- Python packages the add-ons need --------------------------------------------

python_packages=$(echo "$list" | while read -r name set url rev py; do
    case " $sets " in *" $set "*) [ "$py" != - ] && echo "$py" | tr ',' '\n' ;; esac
done | sort -u)

if [ -n "$python_packages" ]; then
    freecadcmd=$(command -v freecadcmd || command -v FreeCADCmd || true)
    if [ -z "$freecadcmd" ]; then
        echo "freecadcmd not found; if an add-on complains, install: $python_packages" >&2
    else
        # Ask FreeCAD's own Python which packages it can't import yet. The file
        # needs a .py name, or freecadcmd tries to open it as a document.
        probe_dir=$(mktemp -d)
        probe="$probe_dir/probe.py"
        cat > "$probe" <<EOF
import importlib.util, os, sys
tag = "py%d%d" % sys.version_info[:2]
print("TAG", tag)
# Count packages already installed in the target profile, not just FreeCAD's own.
sys.path.insert(0, os.path.join(r"""$user_data""", "AdditionalPythonPackages", tag))
for name in """$python_packages""".split():
    if importlib.util.find_spec(name) is None:
        print("MISSING", name)
EOF
        out=$("$freecadcmd" "$probe" 2>/dev/null | tr -d '\r' || true)
        rm -rf "$probe_dir"
        tag=$(echo "$out" | sed -n 's/^TAG //p')
        missing=$(echo "$out" | sed -n 's/^MISSING //p' | tr '\n' ' ')
        if [ -n "$missing" ] && [ -n "$tag" ]; then
            packages_dir="$user_data/AdditionalPythonPackages/$tag"
            mkdir -p "$packages_dir"
            # Wheels for FreeCAD's Python version, whatever python3 is here.
            version=$(echo "$tag" | sed 's/^py\(.\)\(.*\)$/\1.\2/')
            python3 -m pip install --quiet --upgrade --target "$packages_dir" \
                --python-version "$version" --only-binary=:all: $missing
            echo "Installed Python packages into $packages_dir: $missing"
        fi
    fi
fi

echo "Done. Restart FreeCAD and pick the 'Fusion' workbench."
