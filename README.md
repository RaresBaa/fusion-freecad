# fusion-freecad

A FreeCAD addon that brings a Fusion 360-style workflow to FreeCAD on Linux and
Windows, plus an MCP server so AI agents such as Claude Code can model parts in a
live FreeCAD session.

An independent project, not affiliated with or endorsed by Autodesk. Fusion 360 is a
trademark of Autodesk, Inc.; it's named here only to describe the workflow.

Status: early. Working today:

- **MCP bridge**: agents can sketch, extrude, cut, revolve, loft, sweep, drill holes,
  pattern, mirror, shell, fillet, measure, drive the model from parameters, roll the
  timeline back, take screenshots and export (STEP, STL, DXF...), in a live FreeCAD.
- **Fusion workbench**: Fusion-style toolbars in one workspace.
- **Timeline** at the bottom: drag the orange marker to roll back, drag features to
  reorder them, double-click to edit, right-click to suppress or delete. Each
  feature's sketch is folded into it, so long histories stay short.
- **Press/Pull** (Q): pick a face, drag the arrow or type a distance; positive adds,
  negative cuts. On a
  hole, boss or fillet it changes the radius.
- **Combine and Split Body** (Modify): join, cut or intersect bodies; split one along a
  face or plane (select it, then Split Body) into new bodies that still follow the
  original.
- **Change Parameters** (Modify): one table of named values (`width`, `wall`...) that
  sketch dimensions and features use as `Parameters.width`; edit one and the model follows.
- **Fusion keys**: E extrude, F fillet, H hole, Q press/pull, S search at the mouse; in sketches R rectangle,
  D dimension, X construction, O offset. Optionally L line, C circle, P project (*Fusion* menu).
  They're only active while you're in the Fusion workbench.
- **Add-ons built in**: screws and nuts (Fasteners), sheet metal with flat patterns,
  gears, threads, 3D-printing helpers, live measurements and tool search, installed
  automatically and tested together. See [docs/addons.md](docs/addons.md).

What's next is on the [roadmap](docs/roadmap.md).

## What's here

| Path | What it is |
|---|---|
| `addon/FusionFreeCAD/` | The FreeCAD addon: the **Fusion** workbench and the RPC bridge that runs inside FreeCAD |
| `mcp-server/` | `fusion-freecad-mcp`, the MCP server agents talk to; it forwards calls to the bridge |
| `addons.json` | The add-ons we integrate with, pinned to tested commits |
| `scripts/` | Install scripts, and `check-addons.py` to test the add-on integrations |
| `flake.nix` | NixOS / Home Manager packaging ([docs/nix.md](docs/nix.md), untested) |
| `docs/` | [Architecture](docs/architecture.md), [MCP tools](docs/mcp-tools.md), [add-ons](docs/addons.md), [Nix](docs/nix.md), [development](docs/development.md), [roadmap](docs/roadmap.md) |

## Quick start

Requires FreeCAD 1.0 or newer (developed on 1.1) and [uv](https://docs.astral.sh/uv/).

1. **Install the addon** (links it into FreeCAD's Mod folder, so repo edits apply on
   restart, and installs the [add-ons](docs/addons.md) it uses at tested versions;
   `-Addons minimal|all|none` / `--addons ...` to choose). On NixOS see [docs/nix.md](docs/nix.md).

   On Windows without git, download `fusion-freecad-<version>-windows.zip` from the
   GitHub releases, extract it and double-click `Install.cmd`. It copies everything
   (add-ons included) into FreeCAD and prints the `claude mcp add` command for step 3,
   so the extracted folder can be deleted afterwards. Run it from a newer zip to update.

   ```powershell
   # Windows
   powershell -ExecutionPolicy Bypass -File scripts\install-addon.ps1
   ```
   ```sh
   # Linux / macOS
   scripts/install-addon.sh
   ```

2. **Start the bridge.** Restart FreeCAD, pick the **Fusion** workbench and press the
   green **Start MCP bridge** button. To have it start with FreeCAD, tick
   *Fusion → Start MCP bridge with FreeCAD*.

3. **Connect Claude Code.** Opening Claude Code in this repo picks up `.mcp.json`
   automatically (approve the `freecad` server when asked). To use it from anywhere:

   ```sh
   claude mcp add --scope user freecad -- uv --directory <path-to-repo>/mcp-server run fusion-freecad-mcp
   ```

4. Ask for a part, for example: *"Make a 60x30x6 mm mounting plate with four M4
   clearance holes 5 mm from the corners and 2 mm rounded corners, then export it as
   STEP."* Every tool call is one undo step in FreeCAD, so Ctrl+Z works as expected.

## Security

The bridge listens on `127.0.0.1` only and requires a random token that changes every
time it starts. The token is stored in `~/.fusion-freecad/rpc.json`, which only your
user can read. The `run_python` tool runs arbitrary Python inside FreeCAD, so any
program that can read that file can control FreeCAD. Stop the bridge when you're not
using it if that matters to you.

## License

[LGPL-2.1-or-later](LICENSE). The add-ons it installs are separate projects under
their own licenses.
