# Roadmap

## 1. MCP bridge (done, v0.1)

- [x] RPC bridge inside FreeCAD (localhost, token auth, main-thread execution)
- [x] MCP server: documents, sketches, pad/pocket/revolve, fillet/chamfer, topology,
      properties, undo/redo, screenshots, STEP/STL export, `run_python`
- [x] Headless integration tests against real FreeCAD
- [ ] More features: hole (with thread presets), patterns, mirror, shell, loft, sweep
- [ ] Assemblies (FreeCAD 1.x Assembly workbench): insert parts, joints
- [ ] Sketch editing: move/delete geometry, named dimensions, expressions/parameters
- [ ] Measurements (distance, angle) as tools

## 2. Fusion workbench basics

- [x] One workbench with Fusion-style toolbars (Sketch / Create / Modify / Pattern /
      Construct / Inspect) built from PartDesign commands
- [ ] Fusion keyboard shortcuts (L line, C circle, R rectangle, D dimension, E extrude,
      F fillet, Q press/pull, S search) as a switchable profile
- [ ] Fusion mouse navigation and a dark theme
- [ ] Ribbon-style tabs (evaluate the community Ribbon UI addon vs our own)

## 3. Timeline

- [ ] Dock widget at the bottom showing the active body's features as icons
- [ ] Double-click to edit, drag the marker to roll back (move the body Tip),
      right-click to suppress/delete
- [ ] Keep it in sync with document changes (observer)

## 4. Smart tools

- [ ] Press/Pull: select a face, drag to pad or pocket depending on direction
- [ ] Extrude straight from a selected face without opening a sketch
- [ ] S-key command search popup

## Open questions

- Ship as one addon in the FreeCAD Addon Manager, with the MCP server published to PyPI?
- License: currently marked LGPL-2.1-or-later to match FreeCAD; not final.
