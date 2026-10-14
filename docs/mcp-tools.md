# MCP tools

All lengths are millimetres and all angles degrees. `document` is optional on every
tool and defaults to the active document. Objects can be named by internal name
(`Pad001`) or label. Each modelling tool is a single undo step in FreeCAD.

## Session and documents

| Tool | Does |
|---|---|
| `freecad_status` | Version, GUI vs headless, active document. Good first call |
| `list_documents` | Open documents |
| `new_document(name)` | Create a document and make it active |
| `open_document(path)` / `save_document(path?)` / `close_document(document)` | File handling for `.FCStd` |
| `activate_document(document)` | Switch the active document |

## Inspection

| Tool | Does |
|---|---|
| `list_objects` | Every object: name, label, type, owning body, validity |
| `get_object(name)` | Properties and shape summary; for sketches also geometry and constraints |
| `get_topology(name)` | Faces (type, area, centre, normal) and edges (type, length, endpoints/radius) |

Use `get_topology` to choose a face to sketch on or edges to fillet. Face and edge
names can change when earlier features change, so look them up again after edits.

## Modelling

| Tool | Fusion equivalent |
|---|---|
| `create_body(label)` | New component / body |
| `create_sketch(geometry, plane \| face, offset, constraints)` | Create Sketch |
| `add_sketch_geometry(sketch, geometry, constraints)` | Edit sketch |
| `pad(sketch, length, reversed, midplane, up_to_face)` | Extrude (Join) |
| `pocket(sketch, length, through_all, reversed, midplane)` | Extrude (Cut) |
| `revolve(sketch, angle, axis, groove)` | Revolve (Join or Cut) |
| `fillet(edges, radius, base)` / `chamfer(edges, size, base)` | Fillet / Chamfer. `edges` can be `"all"` |
| `press_pull(face, distance)` | Press Pull: move a flat face, e.g. `"Pad:Face6"`; positive adds, negative cuts |
| `set_property(name, property, value)` | Edit feature, e.g. change a Pad's `Length` |
| `delete_object(name)` | Delete |
| `recompute`, `undo(steps)`, `redo(steps)` | |

### Sketch geometry

```json
[
  {"type": "rectangle", "center": [0, 0], "width": 40, "height": 20},
  {"type": "rectangle", "corner": [0, 0], "width": 40, "height": 20},
  {"type": "circle", "center": [12, 0], "radius": 2},
  {"type": "line", "start": [0, 0], "end": [10, 5]},
  {"type": "arc", "center": [0, 0], "radius": 5, "start_angle": 0, "end_angle": 90},
  {"type": "polygon", "points": [[0, 0], [10, 0], [5, 8]]}
]
```

Any item can have `"construction": true`. Rectangles get width/height dimensions and
circles a diameter dimension, so you can edit them later in FreeCAD; pass
`"dimensioned": false` to skip that. The result's `geometry_indices` lists, per item,
the sketch geometry indices it created (a rectangle creates four lines).

### Sketch constraints

Passed straight to `Sketcher.Constraint(type, *args)`. Point positions: 1 = start,
2 = end, 3 = centre. Geometry `-1` is the sketch X axis, `-2` the Y axis, and point
`(-1, 1)` is the origin.

```json
[
  {"type": "Coincident", "args": [0, 1, -1, 1]},
  {"type": "Distance", "args": [4, 10.0]},
  {"type": "Symmetric", "args": [0, 1, 0, 2, -1, 1]}
]
```

## Timeline

The body's feature history, like Fusion's timeline. The rollback marker sits right
after the body's tip; features after it are excluded from the model, and new
features are inserted at the marker.

| Tool | Does |
|---|---|
| `get_timeline(body?)` | Entries in order: kind (sketch/feature/datum), rolled back, suppressed, failed |
| `roll_timeline(to \| steps)` | `to`: feature name, `"start"` or `"end"`; `steps`: move by N solid features (negative = back) |
| `suppress_feature(name, suppressed)` | Disable a feature without deleting it |

Typical use: roll back before a fillet, add a hole, then `roll_timeline(to="end")`.

## Other add-ons (GUI only)

These drive the add-ons in [addons.md](addons.md) and say so if one isn't installed.

| Tool | Does |
|---|---|
| `list_addons` | Which add-ons are installed |
| `insert_fastener(type, diameter, length, hole \| position)` | Standard screw, nut or washer (Fasteners). With `hole="Pocket:Edge14"` (a hole's circular edge) it's placed and sized for the hole. A wrong length lists the valid ones |
| `create_gear(kind, teeth, module, height, position, in_body)` | Parametric gear: involute, internal, rack, bevel, worm, timing, cycloid, crown. A separate part unless `in_body` |
| `sheet_metal_base(sketch, thickness, radius)` | Sheet metal plate from a closed sketch |
| `sheet_metal_flange(edges, length, angle, radius)` | Bend a flange up along sheet edges |
| `sheet_metal_unfold(face \| base)` | Flat pattern (export it with `export`) |
| `list_commands(filter)` | Find any GUI command, e.g. `"teardrop"` |
| `run_command(command, selection, accept_dialog)` | Run any command as if clicked, after selecting `selection`; returns what it created |

## View (GUI only)

| Tool | Does |
|---|---|
| `set_view(view, fit)` | `isometric`, `front`, `back`, `top`, `bottom`, `left`, `right` |
| `screenshot(view, width, height, fit)` | Returns a PNG image the agent can look at |

## Files

| Tool | Does |
|---|---|
| `export(path, objects?)` | `.step/.stp`, `.iges/.igs`, `.stl`, `.obj`, `.brep`, `.FCStd` (copy). Defaults to all bodies |
| `import_file(path)` | STEP, IGES, BREP, STL, OBJ |

## Escape hatch

`run_python(code)` runs Python inside FreeCAD with `App`, `Gui` (None when headless)
and `doc` predefined. Assign to `result` to return a value; printed output comes back
as `stdout`. It runs as one undo step.
