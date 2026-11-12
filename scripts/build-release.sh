#!/usr/bin/env sh
# Builds the Linux release archive, dist/fusion-freecad-<version>-linux.tar.gz. It holds
# the committed addon and MCP server (HEAD, not uncommitted edits), every add-on from
# addons.json at its pinned commit, and install.sh, which runs scripts/install-addon.sh
# in release mode (copies, no git). The release workflow runs it on every v* tag.
#
#   scripts/build-release.sh
#
# Needs git, tar and python3.
set -eu

repo=$(cd "$(dirname "$0")/.." && pwd)
version=$(python3 -c 'import sys, xml.etree.ElementTree as ET
print(ET.parse(sys.argv[1]).getroot().find("{*}version").text.strip())' \
    "$repo/addon/FusionFreeCAD/package.xml")
name="fusion-freecad-$version-linux"
dist="$repo/dist"
staging="$dist/$name"
archive="$dist/$name.tar.gz"

if [ -n "$(git -C "$repo" status --porcelain)" ]; then
    echo "Warning: uncommitted changes are not included; the archive is built from HEAD." >&2
fi
rm -rf "$staging" "$archive"
mkdir -p "$staging"

# --- our files, as committed ----------------------------------------------------

git -C "$repo" archive --format=tar HEAD \
    addon mcp-server/src mcp-server/pyproject.toml mcp-server/uv.lock mcp-server/README.md \
    scripts/install-addon.sh addons.json README.md LICENSE | tar -x -C "$staging"
chmod +x "$staging/scripts/install-addon.sh"

cat > "$staging/install.sh" <<'EOF'
#!/usr/bin/env sh
# Installs Fusion FreeCAD and its add-ons into FreeCAD. Options, e.g. --addons all,
# are passed on to scripts/install-addon.sh (--help lists them).
exec sh "$(dirname "$0")/scripts/install-addon.sh" "$@"
EOF
chmod +x "$staging/install.sh"

# --- add-ons at their pinned commits ----------------------------------------------

python3 - "$repo/addons.json" <<'EOF' | tr -d '\r' | while read -r addon url rev; do
import json, sys
for a in json.load(open(sys.argv[1]))["addons"]:
    print(a["name"], a["url"], a["rev"])
EOF
    dir="$staging/addons/$addon"
    mkdir -p "$dir"
    git -C "$dir" init --quiet
    git -C "$dir" remote add origin "$url"
    git -C "$dir" fetch --quiet --depth 1 origin "$rev" ||
        { echo "Could not fetch $addon at $rev" >&2; exit 1; }
    git -C "$dir" checkout --quiet --detach FETCH_HEAD
    rm -rf "$dir/.git"
    # install-addon.sh reads this to tell which commit a copied add-on is at.
    echo "$rev" > "$dir/.fusion-freecad-rev"
    echo "  $addon ($(printf '%.7s' "$rev"))"
done

# --- archive -----------------------------------------------------------------------

tar -czf "$archive" -C "$dist" "$name"
rm -rf "$staging"
echo "Built $archive ($(du -h "$archive" | cut -f1))"
