# NixOS

> **Status: untested.** The flake was written on Windows without Nix available. It has
> been syntax-checked, not evaluated or built. Please report what breaks.

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
    homeConfigurations.rares = home-manager.lib.homeManagerConfiguration {
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
nix run .#freecad
```

This uses nixpkgs' `freecad.customize { modules; pythons; }`. If your nixpkgs doesn't
have it, the `freecad` package is simply absent; use the Home Manager module instead.

## Connecting Claude Code

```sh
claude mcp add --scope user freecad -- fusion-freecad-mcp     # with the HM module
claude mcp add --scope user freecad -- nix run /path/to/fusion-freecad#mcp-server
```

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

## What to check when testing

1. `nix flake check` evaluates.
2. `nix build .#mcp-server` builds and `result/bin/fusion-freecad-mcp` starts (it waits
   on stdin; Ctrl+C).
3. With the Home Manager module: FreeCAD shows the Fusion workbench and its add-on
   toolbars, and *Fusion → Start MCP bridge* works.
4. SheetMetal's unfold works (it needs `networkx` in FreeCAD's Python).
5. Optional: `nix run .#freecad`.
