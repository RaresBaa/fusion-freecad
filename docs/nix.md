# NixOS

> **Status:** tested on NixOS (x86_64, nixos-unstable 2026-10, FreeCAD 1.1.4): the
> packages, the Home Manager module, the dev shell and the MCP bridge work. aarch64 is
> untested. See [Known issues](#known-issues).

The flake provides:

| Output | What |
|---|---|
| `homeManagerModules.default` | Links Fusion FreeCAD and the add-ons into FreeCAD's user Mod folder, installs FreeCAD (with the add-ons' Python packages) and the MCP server |
| `packages.<system>.mcp-server` (also `default`, `apps.default`) | The `fusion-freecad-mcp` command |
| `packages.<system>.mods`, `mods-all` | All Mod folders in one directory (default / all add-on sets) |
| `packages.<system>.freecad`, `freecad-all` | FreeCAD with everything built in, via nixpkgs' `freecad.customize` (only if your nixpkgs has it) |
| `devShells.<system>.default` | uv, Python, FreeCAD, git, for working on this repo |

Add-ons are flake inputs pinned to the same commits as [`addons.json`](../addons.json),
so `flake.lock` records their hashes the first time you use the flake.

## Home Manager (recommended)

```nix
# flake.nix of your system/home configuration
{
  inputs.fusion-freecad.url = "git+ssh://git@github.com/RaresBaa/fusion-freecad";
  # (private repo; switch to github:RaresBaa/fusion-freecad if it becomes public)

  outputs = { home-manager, fusion-freecad, ... }: {
    homeConfigurations.me = home-manager.lib.homeManagerConfiguration {
      # ...
      modules = [
        fusion-freecad.homeManagerModules.default
        {
          programs.fusion-freecad = {
            enable = true;
            addons = "default";        # "minimal", "default" or "all"
            # installFreeCAD = false;  # if you install FreeCAD another way
          };
        }
      ];
    };
  };
}
```

This creates links like `~/.local/share/FreeCAD/v1-1/Mod/FusionFreeCAD` and
`.../Mod/fasteners`. If a future FreeCAD moves its data folder, set
`programs.fusion-freecad.freecadDataDir` (default `"FreeCAD/v1-1"`).

The links point into the read-only Nix store, so don't install or update these add-ons
with FreeCAD's Addon Manager; change the flake instead.

## FreeCAD with everything built in

```sh
nix run .#freecad       # default add-on set
nix run .#freecad-all   # also FreeCAD Ribbon and PieMenu (they change the whole interface)
```

This uses nixpkgs' `freecad.customize { modules; pythons; }`. If your nixpkgs doesn't
have it, the `freecad` package is simply absent; use the Home Manager module instead.

The flake patches FreeCAD Ribbon for nixpkgs' FreeCAD, which reports its git revision as
"Unknown" (Ribbon raised at startup, after hiding the classic toolbars) and whose add-on
files are read-only (Ribbon copied its layout with their mode and couldn't save it).

## Connecting Claude Code

```sh
claude mcp add --scope user freecad -- fusion-freecad-mcp     # with the HM module
claude mcp add --scope user freecad -- nix run /path/to/fusion-freecad#mcp-server
```

The repo's `.mcp.json` runs the server with `uv`, which is only on `PATH` inside
`nix develop`. To use this checkout outside it, override it for yourself:
`claude mcp add --scope local freecad -- nix run /path/to/fusion-freecad#mcp-server`.

The MCP server works with the `mcp` Python package from nixpkgs whether it is 1.x or 2.x.

## Working on the repo

```sh
nix develop
cd mcp-server && uv sync && uv run pytest
```

The dev shell sets `UV_PYTHON` to nixpkgs' Python and turns off uv's Python downloads,
which don't run on NixOS. The integration tests find `freecadcmd` on `PATH`.

To run FreeCAD on your working copy, set `programs.fusion-freecad.linkFusionAddon =
false;` (Home Manager keeps providing the add-ons) and link the checkout with
`scripts/install-addon.sh --addons none`.

## Known issues

- **Touching solids can crash FreeCAD.** nixpkgs builds FreeCAD 1.1.4 against OCCT
  7.9.3, whose point-in-solid classification segfaults when a point lies on a solid's
  boundary: `distToShape` or `isInside` between solids that touch or overlap. The
  `interference` tool works around it; `rib`, `measure` between touching bodies and
  press-pull can still crash, and `uv run pytest` fails from `test_rib` on (FreeCAD dies,
  so later tests fail too). The official FreeCAD builds aren't affected.
- **FreeCAD Ribbon's first start can hang** (`freecad-all` only). It loads every workbench
  to build its data, and BIM's first-use Welcome dialog opens behind its progress window
  and doesn't take input. Before the first `freecad-all` start, open the BIM workbench
  once in `nix run .#freecad` and close its Welcome.
- **Screenshots** were captured mid-animation after a view change (a cut-off sliver of
  the model). Fixed in the bridge; this was not Nix-specific.
