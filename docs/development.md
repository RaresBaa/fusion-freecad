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

## Gotchas

- `InitGui.py` is run by FreeCAD with `exec()`, so `__file__` is undefined there. Put
  logic in the `fusion_freecad` package and import it.
- FreeCAD APIs are main-thread only. Never call them from `rpc.py`'s network threads.
- Headless documents start with undo disabled; `_open_transaction()` turns it on.
- `PartDesign::Pad`'s `TwoLengths` mode shows up as `?TwoLengths` in 1.1's enum list,
  so it isn't exposed yet.
- The MCP SDK is 2.x: `from mcp.server.mcpserver import MCPServer` (FastMCP was renamed).
