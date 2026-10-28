# Development

## Setup

```sh
cd mcp-server
uv sync
```

Install the addon with `scripts/install-addon.ps1` (Windows) or
`scripts/install-addon.sh` (Linux/macOS). It links the repo folder into FreeCAD, so
there is nothing to copy after edits, but FreeCAD must be restarted to reload Python
code. In the FreeCAD Python console you can also reload by hand:

```python
import importlib, fusion_freecad.handlers as h; importlib.reload(h)
```

(the running bridge keeps references to the old functions, so stop and start it after
reloading).

## Tests

```sh
cd mcp-server
uv run pytest
```

The integration tests start a **headless** FreeCAD (`freecadcmd`) running the bridge
on a random port with its own `rpc.json`, so they don't interfere with a FreeCAD you
have open. `freecadcmd` is looked up on `PATH` and in `C:\Program Files\FreeCAD*`; set
`FREECADCMD` to point at it otherwise. If it can't be found, those tests are skipped.

GUI-only tools (`screenshot`, `set_view`) can't run headless. To check them, start
FreeCAD with the bridge and use the client directly:

```sh
uv run python -c "from fusion_freecad_mcp.client import FreeCADClient; print(FreeCADClient().call('ping'))"
```

## Testing with other add-ons, without touching your FreeCAD setup

FreeCAD honours `FREECAD_USER_HOME`: point it at an empty folder to get a throwaway
profile (its own `Mod`, settings and `AdditionalPythonPackages`). Combined with
`FUSION_FREECAD_RPC_FILE` the bridge doesn't clash with your normal FreeCAD:

```sh
export FREECAD_USER_HOME=/tmp/fc-test FUSION_FREECAD_RPC_FILE=/tmp/fc-test/rpc.json
scripts/install-addon.sh --addons all /tmp/fc-test/Mod
freecad   # then Fusion workbench -> Start MCP bridge
cd mcp-server && uv run python ../scripts/check-addons.py
```

A fresh profile shows FreeCAD's first-run dialogs (and Ribbon's, if installed); they
block startup scripts until answered.

## Windows release

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
```

builds `dist\fusion-freecad-<version>-windows.zip` from the committed `HEAD` (version
from `package.xml`; bump it, and `mcp-server/pyproject.toml`, first). It bundles every
add-on in `addons.json` at its pinned commit, so installing needs no git. Upload the
zip to a GitHub release by hand; there is no CI.

`install-addon.ps1` notices the bundled `addons\` folder and copies instead of linking:
the addon into `Mod\FusionFreeCAD`, the add-ons into `Mod`, the MCP server into
`%LOCALAPPDATA%\fusion-freecad\mcp-server`. Copied folders get a `.fusion-freecad-rev`
file (the commit), so a later install can replace them; `-Uninstall` removes the addon
and the MCP server copy.

## Gotchas

- `InitGui.py` is run by FreeCAD with `exec()`, so `__file__` is undefined there. Put
  logic in the `fusion_freecad` package and import it.
- FreeCAD APIs are main-thread only. Never call them from `rpc.py`'s network threads.
- Headless documents start with undo disabled; `_open_transaction()` turns it on.
- `PartDesign::Pad`'s `TwoLengths` mode shows up as `?TwoLengths` in 1.1's enum list,
  so it isn't exposed yet.
- The MCP SDK is 2.x: `from mcp.server.mcpserver import MCPServer` (FastMCP was renamed).
  Only `ToolError` messages reach the agent; other exceptions show as "Error executing tool".
- FreeCAD switches workbench during edits (Sketcher for sketches, PartDesign for feature
  dialogs). Don't treat `Workbench.Deactivated()` as "user left"; see `session.py`.
- Sketcher tool actions (and so their shortcuts) only exist after a sketch has been
  opened once; `Gui.Command.get(...).getShortcut()` returns "" for them before that.
- FreeCAD 1.1 sketcher single-key shortcuts: A H/V, C coincident, E equal, H horizontal,
  I vertical distance, L horizontal distance, N perpendicular, P parallel, S symmetric,
  T tangent, V vertical, W move. Digits 0-6 are standard views.
- An add-on's commands exist only after its workbench was initialized (activated
  once). `integrations.ensure_command()` handles that.
- Add-ons that create PartDesign-aware objects (Gears, SheetMetal) put them into the
  *active body*. Clear `view.setActiveObject("pdbody", None)` first if that's unwanted.
- Screenshots and offscreen renders come out blank while the Windows session is locked.
- Assembly joints (1.1): pass references as `[part_link, [sub, sub]]`. The
  `[assembly, ["Link.Edge2", ...]]` form is accepted and stored, but the solver then
  leaves the parts where they are (and still returns 0). `asm.Group` also holds
  helper objects that aren't parts.
- `PartDesign::LinearPattern` in 1.1 leaves `Spacings2` at `[0.0]`, which stacks the
  second direction on the first; set it to `[-1.0] * (Occurrences2 - 1)`.
- `sketch.setDatum()` keeps an existing expression on that constraint; clear it with
  `setExpression(path, None)` first.
- GUI checks: `Gui.getMainWindow().grab()` shows widgets but not the 3D view (OpenGL);
  use the `screenshot` handler for the model. `PySide6.QtTest.QTest` can simulate key
  presses and mouse drags through `run_python`.
- TechDraw in the GUI computes view edges (hidden-line removal) in a thread and hands
  them over through the event loop: right after a recompute `getVisibleEdges()` still
  returns the old ones, and a projection group's spacing follows the view sizes.
  `handlers_drawing._settle()` pumps events until they arrive. Headless it's synchronous.
- TechDraw's automatic scale never goes above 1:1; `create_drawing` picks its own.
- Dimension `X`/`Y` are relative to the view, in sheet mm with Y up, the same frame as
  `getVisibleEdges()`; TechDraw leaves new ones at the view's centre.
- The sketcher's `LeaveSketchWithEscape` (1.1) is read from `Mod/Sketcher` but only
  re-read when it changes in `Mod/Sketcher/General` (where the preferences page writes
  it). Set it in both, `Mod/Sketcher` first; `sketcher.SETTINGS` does.
- `QTest.keyClick(view.graphicsView().viewport(), Qt.Key_Escape)` reaches the sketcher
  like a real key press, for checking Esc behaviour through `run_python`.
