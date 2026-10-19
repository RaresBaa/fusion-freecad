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
- [ ] Group sketches with the feature that uses them (Fusion shows them separately,
      but it would make long timelines shorter)

## 4. Smart tools

- [x] Press/Pull (Q): pick a flat face, type or scroll a distance, live preview;
      positive pads, negative pockets; MCP tool `press_pull`
- [ ] Press/Pull drag handle (an arrow in the 3D view, like Fusion's)
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
- [ ] Test the Nix flake on NixOS

## Open questions

- Ship as one addon in the FreeCAD Addon Manager, with the MCP server published to PyPI?
- License: currently marked LGPL-2.1-or-later to match FreeCAD; not final.
