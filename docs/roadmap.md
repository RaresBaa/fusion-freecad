# Roadmap

## 1. MCP bridge (done, v0.1)

- [x] RPC bridge inside FreeCAD (localhost, token auth, main-thread execution)
- [x] MCP server: documents, sketches, pad/pocket/revolve, fillet/chamfer, topology,
      properties, undo/redo, screenshots, STEP/STL export, `run_python`
- [x] Headless integration tests against real FreeCAD
- [x] Hole (with thread presets, counterbore/countersink), linear and polar patterns,
      mirror, shell
- [x] Loft, sweep (join or cut)
- [x] Assemblies (FreeCAD 1.x Assembly workbench): insert parts, joints, solve
- [x] Sketch editing: move/delete geometry, named dimensions, expressions/parameters
- [x] Measurements (distance, angle) as tools

## 2. Fusion workbench basics

- [x] One workbench with Fusion-style toolbars (Sketch / Create / Modify / Pattern /
      Construct / Inspect) built from PartDesign commands
- [x] Fusion keyboard shortcuts, active only in Fusion mode: E extrude, F fillet,
      H hole; in sketches R rectangle, D dimension, X construction, O offset;
      opt-in L line, C circle, P project (these take FreeCAD's sketcher keys)
- [x] Stay in Fusion across FreeCAD's automatic workbench switches during edits
- [x] Q press/pull
- [x] Command search (SearchBar add-on)
- [x] Keep the Fusion toolbars visible while editing sketches (core groups, next to
      the sketch tools)
- [x] Fusion mouse navigation in Fusion mode (Revit style: middle pans, Shift+middle
      orbits); dark theme is FreeCAD 1.1's built-in "FreeCAD Dark" or OpenTheme's OpenDark
- [x] Toolbar tabs (SOLID / SHEET METAL / 3D PRINT / INSERT), each showing its own
      groups; our own instead of FreeCAD Ribbon, which replaces and hides every toolbar

## 3. Timeline

- [x] Dock widget at the bottom showing the active body's features as icons
- [x] Drag the marker or use the playback buttons to roll back (moves the body Tip);
      double-click to edit; right-click to edit, roll back, suppress or delete
- [x] Rolled-back features faded, suppressed struck through, failing outlined red
- [x] Stays in sync with every kind of change; MCP tools for the agent
- [x] Drag features to reorder them (their own sketch moves along); MCP tool `move_feature`
- [x] Group sketches with the feature that uses them: a feature's own sketch right
      before it shares its slot, shown as a badge (*Fusion → Group sketches in
      timeline*, on by default; Fusion shows them separately)

## 4. Smart tools

- [x] Press/Pull (Q): pick a flat face, type or scroll a distance, live preview;
      positive pads, negative pockets; MCP tool `press_pull`
- [x] Press/Pull drag handle: an orange arrow on the face, along its outward normal;
      dragging it sets the distance (snapped) with live preview, typing moves it
- [x] Press/Pull arrow on holes and bosses sits at the open end (rim or top), not
      halfway down the bore
- [x] Press/Pull on cylindrical faces: resizes the hole, fillet or sketch circle

## 5. Add-ons

- [x] Tested 15 add-ons with FreeCAD 1.1; pinned in `addons.json`, installed by the
      scripts, the Addon Manager and the Nix flake
- [x] Fusion toolbars for Fasteners, SheetMetal, Gears, ThreadProfile, QuickMeasure,
      FusedFilamentDesign, Gridfinity; MCP tools for fasteners, gears, sheet metal and
      any command
- [x] Patch for SearchBar's FreeCAD 1.1 crash (drop when upstream #47 is fixed)
- [x] S opens SearchBar's search box at the mouse (outside sketches)
- [x] Sheet metal flat pattern export to DXF (`export` to `.dxf`, any flat part)
- [x] Smooth over add-on rough edges: QuickMeasure shows short element names, PieMenu's
      Tab is off in sketches in Fusion mode, toolbars come back after removing Ribbon
- [ ] Test the Nix flake on NixOS

## 6. More Fusion tools

- [x] Change Parameters dialog: one table of the document's parameters (name, value,
      expression), editable, on top of the `Parameters` VarSet the MCP tools use
- [x] Combine (join / cut / intersect bodies) and Split Body on the Modify toolbar;
      MCP tools
- [x] Timeline groups: collapse a range of features into one named slot (right-click →
      Group selected; stored on the body); MCP tools `group_timeline`, `edit_timeline_group`
- [x] Marking menu: Fusion's radial right-click menu in the 3D view (click for the ring,
      right-drag to mark; sketch / dialog / part rings; More... opens FreeCAD's menu)
- [x] Sketch: closer to Fusion's sketcher. FreeCAD 1.1 already infers constraints
      (auto-constraints) and makes dimensions from values typed while drawing
      (on-view parameters); Fusion mode keeps those on and Esc no longer closes the
      sketch. Closed profiles are shaded while editing, overlapping loops as
      separate regions

## 7. More MCP tools

- [x] Construction geometry: datum planes (offset, angled, through 3 points), axes,
      points; sketches on them
- [x] Self-checks: `check_geometry` (valid, closed, self-intersections),
      `interference` between bodies, `mass_properties` (mass, centre of mass, inertia),
      `set_material` from FreeCAD's material library
- [x] Sketch tools: project model edges, offset a profile, fillet corners
      (constraints already go through `add_sketch_geometry` / `delete_sketch_geometry`)
- [x] Features: draft, two-sided and tapered extrudes, text / emboss
- [x] Rib (FreeCAD has no rib feature: a thickened open profile up to the solid, as a
      Python PartDesign feature); MCP tool `rib`
- [x] Bodies: `move_body`, `copy_body`, `appearance` (colour, also of linked copies)
- [x] 2D drawings (TechDraw): views and dimensions, export to PDF / DXF; MCP tools
      `create_drawing`, `drawing_dimension`, `export_drawing`
- [x] Drawings in the GUI: PDF / SVG export checked; views fill the sheet above the
      title block, new dimensions go outside the view on a side with no neighbour
- [x] MCP resources (documents, objects, timeline, parameters) and prompts (model a
      part, prepare for printing, review the model)

## 8. Distribution

- [x] Distributed from GitHub: NixOS through the flake, Windows through a release zip
      built by hand with `scripts/build-release.ps1` and uploaded to a GitHub release
      (no CI for now). Not in the Addon Manager or on PyPI.
- [x] License: LGPL-2.1-or-later, matching FreeCAD
