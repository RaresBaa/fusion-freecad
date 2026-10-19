# Add-ons

Fusion FreeCAD builds on other FreeCAD add-ons instead of reinventing them. They're
listed in [`addons.json`](../addons.json), pinned to commits tested with FreeCAD 1.1.4
(2026-10-14), and installed by the install scripts, the Addon Manager (from
`package.xml`) or the [Nix flake](nix.md).

| Set | Installed by |
|---|---|
| **required** | always (install scripts' default, Addon Manager's required dependencies) |
| **recommended** | by default (`-Addons minimal` / `--addons minimal` skips them) |
| **ui** | only on request (`-Addons all`), because they change the whole interface |

## What each one adds

| Add-on | Set | In the Fusion workbench | Agent (MCP) tools | Tested |
|---|---|---|---|---|
| [SearchBar](https://github.com/APEbbers/SearchBar) | required | Search box for tools, objects, preferences | `list_commands` | Works with our patch (below) |
| [Fasteners](https://github.com/shaise/FreeCAD_FastenersWB) | required | **Fasteners** toolbar: socket/button/countersunk/hex screws, nut, washer, threaded rod, tap, flip, move, BOM | `insert_fastener` | Screw seated in a selected hole, parametric size/length |
| [SheetMetal](https://github.com/shaise/FreeCAD_SheetMetal) | required | **Sheet Metal** toolbar: base, wall, fold, bend, reliefs, hem, cutout, convert solid, unfold | `sheet_metal_base`, `sheet_metal_flange`, `sheet_metal_unfold` | Base plate, flange and flat pattern; features show in the timeline |
| [Gears](https://github.com/looooo/freecad.gears) | required | **Gears** toolbar: involute, internal, rack, bevel, worm, timing, planetary | `create_gear` | Involute and bevel gears |
| [QuickMeasure](https://github.com/DanMiel/QuickMeasure) | required | **Inspect**: live measurement window | | Length, angle, distance of selections |
| [ThreadProfile](https://github.com/mwganson/ThreadProfile) | recommended | **Threads** toolbar: modelled threads | `run_command` | Thread profile created |
| [FusedFilamentDesign](https://github.com/rahix/FusedFilamentDesign) | recommended | **3D Print** toolbar: hole wizard, teardrop, counterbore bridges, auto-fillet, rib threads, zip-tie channels | `run_command` | Auto-fillet adds a PartDesign fillet |
| [Gridfinity](https://github.com/Stu142/FreeCAD-Gridfinity-Workbench) | recommended | **3D Print**: bins and baseplates | `run_command` | Bin and baseplate |
| [OpenTheme](https://github.com/obelisk79/OpenTheme) | recommended | Themes: *Preferences → General → Theme → OpenDark* | | Installs as a preference pack |
| [Curves](https://github.com/tomate44/CurvesWB) | recommended | Own workbench (NURBS surfaces) | `run_command` | Loads cleanly |
| [Defeaturing](https://github.com/easyw/Defeaturing_WB) | recommended | Own workbench (clean up imported STEP) | `run_command` | Loads cleanly |
| [Manipulator](https://github.com/easyw/Manipulator) | recommended | Own workbench (precise move/align) | | Loads cleanly |
| [Render](https://github.com/FreeCAD/FreeCAD-render) | recommended | Own workbench | | Loads; needs Blender, LuxCore or POV-Ray installed to render |
| [FreeCAD Ribbon](https://github.com/APEbbers/FreeCAD-Ribbon) | ui | Ribbon UI; Fusion becomes a tab with our groups | | Works alongside Fusion (see notes) |
| [PieMenu](https://github.com/Grubuntu/PieMenu) | ui | Radial menu on **Tab** | | Loads cleanly |

Toolbars appear only for add-ons that are installed. The first time you open the
Fusion workbench in a session, it quietly loads those add-ons' workbenches so their
tools exist (about a second), then returns to Fusion.

`run_command` lets an agent use any add-on tool: `list_commands("teardrop")` finds the
command, `run_command(command, selection=[...])` runs it like a click.

## Known issues and workarounds

- **SearchBar crashes on first use in FreeCAD 1.1** (`'AssemblyWorkbench' object has no
  attribute '__Workbench__'`), because it asks every workbench for its toolbars,
  including ones never loaded. Upstream:
  [APEbbers/SearchBar#47](https://github.com/APEbbers/SearchBar/issues/47). Fusion
  FreeCAD patches the function at startup (`integrations.patch_searchbar`); the patch
  switches itself off once the upstream code changes.
- **SearchBar's search-at-mouse box opens off-screen** unless FreeCAD sits at the
  top-left of the desktop (it places the box with screen coordinates inside the main
  window), and when reopened it keeps the old text without keyboard focus, so typing
  fires shortcuts instead. Fusion's S key runs it through `FusionFreeCAD_SearchAtCursor`,
  which moves it to the mouse and clears and focuses it. In Fusion mode FreeCAD's
  `S, …` two-key shortcuts (select back/forward, link select, SheetMetal's) are
  unbound so a bare S isn't ambiguous; they come back when you leave Fusion.
- **FreeCAD Ribbon** asks three things on its first start (a welcome form, "generate a
  data file?", and BIM's setup dialog, because it loads every workbench), checks GitHub
  for updates on every start, and hides all classic toolbars, *saving* that. If you
  remove Ribbon later, your toolbars stay hidden: use *Fusion → Show all Fusion
  toolbars* (or *View → Toolbars*).
- **PieMenu** uses Tab, which the sketcher also uses to move between on-view inputs.
- **Gears** adds a gear to the active PartDesign body if there is one, fusing it with
  your part. `create_gear` makes a separate part unless `in_body=True`.
- **QuickMeasure** shows FreeCAD's internal element names (`Pad.;#f:2;...Edge1`) next to
  the values; the values are right.
- **Render** does nothing useful until a render engine is installed.

## Updating the pins

1. Update the clones (`install-addon -Update` after editing `rev`, or check out newer
   commits in a test profile).
2. Restart FreeCAD, start the bridge, and run `uv run python ../scripts/check-addons.py`
   from `mcp-server/`.
3. Update `rev` in `addons.json` and the matching input in `flake.nix`;
   `uv run pytest tests/test_manifest.py` checks they agree with `package.xml` and
   `integrations.py`.
