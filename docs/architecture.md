# Architecture

```
Claude Code ──MCP (stdio)──▶ fusion-freecad-mcp ──JSON lines over TCP──▶ bridge in FreeCAD
                             (mcp-server/, any Python)   127.0.0.1 + token   (addon/, FreeCAD's Python)
```

There are two processes because FreeCAD ships its own Python (3.11 in FreeCAD 1.1) and
we don't want to install the MCP SDK and its dependencies into it. The bridge inside
FreeCAD uses only the standard library; everything MCP-specific lives in `mcp-server/`.

## The bridge (`addon/FusionFreeCAD/fusion_freecad/`)

| File | Role |
|---|---|
| `rpc.py` | TCP server, auth, request queue. No FreeCAD imports, so it is easy to reason about |
| `handlers.py` | The operations (sketch, pad, fillet, export, ...). This is where CAD logic goes |
| `bridge.py` | Starts/stops the server in the GUI, or runs it headless for tests |
| `commands.py` | FreeCAD GUI commands (bridge, timeline and shortcut toggles) |
| `workbench.py` | Toolbar layout of the Fusion workbench |
| `history.py` | Timeline model: body features, rollback marker (= body Tip), suppression. No Qt |
| `timeline.py` | The timeline dock widget (Qt), drawn on top of `history.py` |
| `presspull.py` | Press/Pull core: a Pad or Pocket with a face as its profile. No Qt |
| `presspull_gui.py` | The Q task panel: pick a face, live distance preview, one undo step |
| `integrations.py` | Registry of other add-ons: their toolbar groups, loading them, compatibility patches |
| `handlers_addons.py` | RPC handlers that drive those add-ons (fasteners, gears, sheet metal, any command) |
| `shortcuts.py` | Fusion single-key shortcuts and restoring FreeCAD's originals |
| `session.py` | "Fusion mode": keeps timeline and shortcuts alive across FreeCAD's automatic workbench switches |
| `../InitGui.py` | Registers the workbench; at launch, auto-starts the bridge and cleans up stale shortcuts |

## Fusion mode (`session.py`)

FreeCAD switches workbench by itself during edits: opening a sketch activates the
Sketcher workbench, and PartDesign feature dialogs activate PartDesign. So
`Workbench.Deactivated()` doesn't mean the user left. Instead, `session.py` polls the
active workbench every 250 ms while in Fusion mode:

- Sketcher/PartDesign while something is being edited: an excursion. Keep the
  timeline and keys, and switch back to Fusion when the edit ends.
- Anything else: the user left on purpose. Hide the timeline and restore shortcuts.

## Timeline (`history.py`, `timeline.py`)

The timeline is the body's `Group` in order. The marker is the body's `Tip`: PartDesign
already excludes features after the tip from the body's shape and inserts new features
right after it, which is exactly Fusion's rollback. Only solid features can be the tip,
so rolling to a sketch puts the tip on the nearest solid feature before it.

The widget repaints when a cheap signature of the active body (names, labels, states,
tip, selection) changes, polled a few times a second while visible. That keeps it in
sync with every source of change (tree, undo, Python, MCP) without document observers.

## Press/Pull (`presspull.py`)

PartDesign's Pad and Pocket accept a face of an earlier feature as their profile, so
Press/Pull is just that: a Pad (positive distance, grows along the face normal) or a
Pocket (negative, cuts into the solid), with no hidden sketch. While the panel is open
the distance can change sign, which swaps Pad and Pocket; at zero the feature is
removed. The whole interaction is one transaction, so Cancel leaves nothing behind.
PartDesign's default Refine merges coplanar faces, so pushing a face keeps a clean
solid.

## Other add-ons (`integrations.py`, `handlers_addons.py`)

`addons.json` lists the add-ons we build on; `package.xml`, `flake.nix` and the
`ADDONS` registry in `integrations.py` follow it (a test checks). An add-on's commands
only exist after its workbench has been initialized, so the first activation of the
Fusion workbench schedules `integrations.load()`: it activates each installed add-on's
workbench inside `session.suspended()` (so Fusion mode doesn't end), appends our
toolbar groups to the Fusion workbench, and activates Fusion again, which rebuilds the
toolbars. MCP handlers call `ensure_command()` to do the same on demand.

Most add-ons are built around GUI commands and task panels, so `handlers_addons.py`
drives them like a user: select, `Gui.runCommand`, accept the task dialog, then set
properties on the new object. That keeps us on their public behaviour rather than
their internal Python APIs.

Compatibility patches for add-on bugs live in `integrations.py` and are applied at
startup; each checks that the bug is still present before patching.

## Shortcuts (`shortcuts.py`)

FreeCAD shortcuts are global and persisted, so Fusion keys are bound when Fusion mode
starts and the previous shortcuts are restored when it ends. The originals are stored
in preferences (`SavedShortcuts`), so a FreeCAD that quits in Fusion mode is cleaned up
on the next launch. Sketcher tool actions only exist once a sketch has been opened, so
sketch keys are bound from inside the sketcher. FreeCAD's sketcher uses many single
letters for constraints; part keys (E, F, H) coexist with them because each set is only
enabled in its own context. Fusion's clashing sketch keys (L, C, P) are opt-in.

### Threading

FreeCAD's document and GUI APIs must only be used from the main thread. The TCP
server runs on background threads that only parse requests, check the token and put
calls on a queue. In the GUI a `QTimer` drains the queue every 25 ms on the main
thread; headless, `bridge.serve_headless()` drains it in a loop. The network thread
waits up to 300 s for the result (a modal dialog left open in FreeCAD blocks calls).

### Protocol

One JSON object per line:

```json
{"id": 1, "token": "<from rpc.json>", "method": "pad", "params": {"sketch": "Sketch", "length": 5}}
{"id": 1, "result": {"feature": "Pad", "body": "Body", "shape": {"volume": 4000.0}}}
{"id": 1, "error": {"type": "HandlerError", "message": "no object 'Skech' in document 'Unnamed'"}}
```

On start the bridge writes `~/.fusion-freecad/rpc.json` (`host`, `port`, `token`,
`pid`, `protocol`), and deletes it when it stops or FreeCAD quits. The MCP server
re-reads it on every call, so FreeCAD can be restarted without restarting the agent.
`FUSION_FREECAD_RPC_FILE` overrides the location (tests use this to run in isolation).

### Undo and errors

Every modelling handler is wrapped by `_mutating()` in `handlers.py`: it opens a
document transaction, runs, recomputes and commits. If the handler raises, the
transaction is aborted, so a failed call leaves nothing half-built. Features that
fail to recompute don't raise; they are listed under `"errors"` in the result so the
agent can see them and decide to undo or fix them.

`HandlerError` marks expected, user-facing errors (bad arguments, missing objects);
the MCP client shows just the message. Other exceptions include a traceback.

## The MCP server (`mcp-server/src/fusion_freecad_mcp/`)

`server.py` defines the tools with the `mcp` SDK (2.x, `MCPServer`). Each tool is a
thin wrapper that calls the handler of the same name, adding typed parameters and
descriptions for the agent. `client.py` is the bridge client.

To add an operation: write the handler in `handlers.py`, add it to `HANDLERS`, add a
tool in `server.py`, and add a test in `mcp-server/tests/test_bridge.py`.
