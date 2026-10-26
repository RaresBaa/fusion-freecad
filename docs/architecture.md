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
| `presspull.py` | Press/Pull core: a Pad or Pocket with a face as its profile; resizing for curved faces. No Qt |
| `presspull_gui.py` | The Q task panel: pick a face, live distance preview, one undo step |
| `integrations.py` | Registry of other add-ons: their toolbar groups, loading them, compatibility patches |
| `handlers_assembly.py` | RPC handlers for assemblies: links to parts, joints and the solver of FreeCAD's Assembly workbench |
| `handlers_addons.py` | RPC handlers that drive those add-ons (fasteners, gears, sheet metal, any command) |
| `shortcuts.py` | Fusion single-key shortcuts and restoring FreeCAD's originals |
| `navigation.py` | Fusion mouse navigation (Revit style) in Fusion mode |
| `tabs.py` | Toolbar tabs (SOLID, SHEET METAL, ...) that show one set of groups at a time |
| `layout.py` | First toolbar row in every workbench (standard, SearchBar, MCP); the MCP toolbar |
| `session.py` | "Fusion mode": keeps timeline and shortcuts alive across FreeCAD's automatic workbench switches |
| `../InitGui.py` | Registers the workbench; at launch, auto-starts the bridge and cleans up stale shortcuts and navigation |

## Fusion mode (`session.py`)

FreeCAD switches workbench by itself during edits: opening a sketch activates the
Sketcher workbench, and PartDesign feature dialogs activate PartDesign. So
`Workbench.Deactivated()` doesn't mean the user left. Instead, `session.py` polls the
active workbench every 250 ms while in Fusion mode:

- Sketcher/PartDesign while something is being edited: an excursion. Keep the
  timeline and keys, show the core Fusion toolbars again (the edit workbench hides
  them; their tools are greyed out until the edit ends, but the layout stays put),
  and switch back to Fusion when the edit ends.
- Anything else: the user left on purpose. Hide the timeline and restore shortcuts and navigation.

## Timeline (`history.py`, `timeline.py`)

The timeline is the body's `Group` in order. The marker is the body's `Tip`: PartDesign
already excludes features after the tip from the body's shape and inserts new features
right after it, which is exactly Fusion's rollback. Only solid features can be the tip,
so rolling to a sketch puts the tip on the nearest solid feature before it.

Dragging a feature reorders the body's `Group` (`history.move`): the feature and the
profile sketch only it uses are removed and re-inserted at the drop point, and
PartDesign relinks the BaseFeature chain itself. A move is refused when something
would end up before an object it links to (its sketch, the face a sketch is attached
to), and the marker stays on the same feature, or at the end if it was there.

In the widget, a feature's own profile sketch directly before it shares the feature's
slot (`history.cells`), drawn as a badge; dragging or rolling works on slots, which
map back to `Group` indices (the feature is always a slot's last member, so the marker
never lands inside one). *Fusion → Group sketches in timeline* turns it off.

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

The drag arrow (`presspull_gui.DragHandle`) is placed by `presspull.handle_frame`: on
the face, along its outward normal, which is the way a positive distance moves any face
(a pad grows out, a hole's normal points at its axis, so it shrinks). On a cylinder it
goes to an open end (just past it along the axis is outside the solid; the higher one
if both are), so it isn't hidden down a bore. Dragging is a Qt event filter on the 3D
view, not a Coin dragger: a press within a few pixels of the arrow on screen starts it
(navigation never sees it), and the mouse is projected onto the arrow's on-screen
direction. The model then recomputes from Qt's event handling. A Coin
`SoTranslate1Dragger` lost its grab when a recompute changed a hole's sketch mid-drag.

Cylindrical faces (`RadiusPull`) can't be offset that way: PartDesign has no offset-face
feature. Instead we walk the body back from the selected feature to the first one whose
result has that exact surface (same axis and radius) while its base feature doesn't,
and change its size: a Fillet's `Radius`, a Hole's `Diameter` or `HoleCutDiameter`, or
the circle (its dimension, if it has one) in a Pad's or Pocket's sketch. So the history
stays editable. Positive distance still adds material, so the radius goes up or down
depending on whether the face is convex (boss, outside fillet) or concave (hole).
Sizes driven by an expression or a thread size are refused with a message.

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

## Toolbar tabs (`tabs.py`)

A tab bar in its own toolbar row; each tab (`TABS`) shows some of our toolbar groups
and hides the rest, so the add-on groups don't make one long row. Our groups are put
on one line below the tabs, so a tab's groups sit together (hidden toolbars take no
space). Tabs whose add-ons aren't installed are dropped. During a sketch excursion the
selected tab's groups stay next to the sketch tools. Off when FreeCAD Ribbon is
installed, since Ribbon replaces the toolbars itself.

Our sheet metal group is "Sheet Metal Tools", not "Sheet Metal": FreeCAD stores toolbar
visibility by name when you leave a workbench, so hiding ours would hide the SheetMetal
workbench's own toolbar. For the same reason, when Fusion mode ends the groups a tab
had hidden are marked visible again.

## First toolbar row (`layout.py`)

In every workbench the first row is FreeCAD's standard toolbars, then SearchBar and
MCP; the workbench's toolbars go below. FreeCAD won't keep that by itself: it appends
new toolbars to the last row, SearchBar re-adds its toolbar at the end on each switch,
and global custom toolbars are rebuilt on each switch. So the MCP toolbar is our own
QToolBar (FreeCAD leaves toolbars it didn't make alone; its actions run the commands
and poll `isActive()`), and `arrange()` runs after every `workbenchActivated` to move
stray toolbars off the first row and put SearchBar and MCP at its end. It leaves the
layout alone if the standard toolbars aren't on the first row (the user moved them).

## Navigation (`navigation.py`)

Fusion pans with the middle button, orbits with Shift+middle and zooms at the cursor;
FreeCAD's Revit navigation style matches. Like the shortcuts, it's set (preference and
open views) when Fusion mode starts and the user's style comes back when it ends,
with the original kept in `SavedNavigationStyle` for crash cleanup. If the user picks
another style while in Fusion mode, theirs is kept.

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
