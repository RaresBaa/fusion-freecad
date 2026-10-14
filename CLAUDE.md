# fusion-freecad

FreeCAD addon (Fusion 360-style workbench + RPC bridge) and an MCP server that drives it.
Read docs/architecture.md before changing the bridge, and docs/development.md for setup,
tests and FreeCAD gotchas. docs/roadmap.md tracks what's next; tick items off there.

- Tests: `cd mcp-server && uv run pytest` (spins up headless freecadcmd).
- New operation = handler in `addon/FusionFreeCAD/fusion_freecad/handlers.py` (+ `HANDLERS`),
  tool in `mcp-server/src/fusion_freecad_mcp/server.py`, test in `mcp-server/tests/test_bridge.py`,
  row in `docs/mcp-tools.md`.
- Addon code runs in FreeCAD's bundled Python (3.11): stdlib only, main thread only.
- Other add-ons: `addons.json` is the source of truth; keep `package.xml`, `flake.nix` and
  `integrations.py` in sync (tests/test_manifest.py). After changing pins, run
  `scripts/check-addons.py` against a GUI FreeCAD (see docs/addons.md).
