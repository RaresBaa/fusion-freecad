"""Other FreeCAD add-ons that the Fusion workbench builds on.

Each add-on is optional at runtime: its toolbar group appears only if it's installed.
Add-on commands only exist after their workbench has been loaded once, so the first
time the Fusion workbench is activated, ``load()`` activates each installed add-on's
workbench in the background, adds our toolbar groups, and comes back to Fusion.

The same registry drives package.xml dependencies, the install scripts (addons.json)
and the Nix flake inputs; keep them in sync (scripts/check-addons.py verifies this).
"""

import FreeCAD as App

from . import prefs


class Addon:
    def __init__(self, name, workbench=None, toolbars=(), notes=""):
        self.name = name              # Addon Manager name (= its folder in Mod/)
        self.workbench = workbench    # workbench to load so its commands exist
        self.toolbars = list(toolbars)  # [(toolbar name, [commands])]
        self.notes = notes


ADDONS = [
    Addon("fasteners", "FastenersWorkbench", [
        ("Fasteners", ["FSISO4762", "FSISO7380-1", "FSISO10642", "FSISO4017",
                       "FSISO4032", "FSISO7089", "FSThreadedRod", "FSScrewTap",
                       "Fasteners_Flip", "Fasteners_Move", "Fasteners_BOM"]),
    ], "Screws, nuts, washers, threaded rods. Select a hole edge first to seat it."),
    Addon("sheetmetal", "SMWorkbench", [
        ("Sheet Metal", ["SheetMetal_AddBase", "SheetMetal_AddWall",
                         "SheetMetal_AddFoldWall", "SheetMetal_AddBend",
                         "SheetMetal_AddRelief", "SheetMetal_AddCornerRelief",
                         "SheetMetal_AddHem", "SheetMetal_AddCutout",
                         "SheetMetal_FromSolid", "SheetMetal_Unfold"]),
    ], "Flanges, bends and flat patterns; features live in the PartDesign body."),
    Addon("freecad.gears", "GearWorkbench", [
        ("Gears", ["FCGear_InvoluteGear", "FCGear_InternalInvoluteGear",
                   "FCGear_InvoluteRack", "FCGear_BevelGear", "FCGear_WormGear",
                   "FCGear_TimingGear", "FCGear_PlanetaryGear"]),
    ]),
    Addon("ThreadProfile", "ThreadProfileWorkbench", [
        ("Threads", ["ThreadProfileCreateObject", "ThreadProfileDoSweep"]),
    ], "Modelled (printable) threads."),
    Addon("QuickMeasure", None, [
        ("Inspect", ["QuickMeasureTool"]),
    ], "Floating measurement window that follows the selection."),
    Addon("FusedFilamentDesign", None, [
        ("3D Print", ["ffDesign_HoleWizard", "ffDesign_Teardrop",
                      "ffDesign_CounterboreBridges", "ffDesign_AutoFillet",
                      "ffDesign_RibThreads", "ffDesign_ZipTieChannels"]),
    ], "Design helpers for FDM printing."),
    Addon("Gridfinity", "GridfinityWorkbench", [
        ("3D Print", ["CreateBinBlank", "CreatePartsBin", "CreateBaseplate"]),
    ]),
    # No toolbar of ours; useful on their own.
    Addon("SearchBar", notes="Search tools, objects and preferences (patched, see below)."),
    Addon("OpenTheme", notes="Dark/light themes: Preferences > General > Theme."),
    Addon("Curves", notes="NURBS curves and surfaces workbench."),
    Addon("Defeaturing", notes="Remove faces/features from imported STEP files."),
    Addon("FreeCAD-Ribbon", notes="Ribbon UI; shows the Fusion workbench as a tab."),
    Addon("PieMenu", notes="Radial menu on Tab, like Fusion's marking menu."),
    Addon("Render", notes="Photo-real renders; needs Blender, LuxCore or POV-Ray."),
    Addon("Manipulator", notes="Precise move/rotate/align tools."),
]

_loaded = False


def _gui():
    import FreeCADGui
    return FreeCADGui


def is_installed(addon):
    Gui = _gui()
    if addon.workbench:
        return addon.workbench in Gui.listWorkbenches()
    known = set(Gui.listCommands())
    commands = [c for _, cmds in addon.toolbars for c in cmds]
    if commands:
        return any(c in known for c in commands)
    import os
    return os.path.isdir(os.path.join(App.getUserAppDataDir(), "Mod", addon.name))


def installed():
    return [a for a in ADDONS if is_installed(a)]


def toolbars():
    """Our toolbar groups, merged by name, with only commands that exist."""
    known = set(_gui().listCommands())
    merged = {}
    for addon in installed():
        for name, cmds in addon.toolbars:
            merged.setdefault(name, [])
            merged[name] += [c for c in cmds if c in known and c not in merged[name]]
    return [(name, cmds) for name, cmds in merged.items() if cmds]


def enabled():
    return prefs().GetBool("IntegrateAddons", True)


def load(fusion_workbench):
    """Load installed add-ons' commands and add their toolbars to the Fusion workbench.

    Runs once per session, right after the Fusion workbench is first activated.
    """
    global _loaded
    if _loaded or not enabled():
        return
    _loaded = True
    Gui = _gui()
    from . import session

    available = Gui.listWorkbenches()
    to_load = [a.workbench for a in installed()
               if a.workbench and a.workbench in available and a.toolbars]
    if to_load:
        with session.suspended():
            for name in to_load:
                try:
                    Gui.activateWorkbench(name)
                except Exception as e:
                    App.Console.PrintWarning("Fusion FreeCAD: couldn't load %s: %s\n"
                                             % (name, e))
            for name, cmds in toolbars():
                fusion_workbench.appendToolbar(name, cmds)
            # Re-activating rebuilds Fusion's toolbars, now including the new groups.
            Gui.activateWorkbench("FusionWorkbench")
        # The add-ons just brought their own shortcuts (SheetMetal's "S, B", ...).
        from . import shortcuts
        if shortcuts.active():
            shortcuts.apply()
    else:
        for name, cmds in toolbars():
            fusion_workbench.appendToolbar(name, cmds)
    from . import tabs
    tabs.show()  # now with the add-on tabs


def ensure_command(workbench, command):
    """Make sure an add-on command is registered, loading its workbench if needed.

    Returns False if the add-on isn't installed.
    """
    Gui = _gui()
    if command in Gui.listCommands():
        return True
    if workbench not in Gui.listWorkbenches():
        return False
    from . import session
    current = Gui.activeWorkbench()
    with session.suspended():
        Gui.activateWorkbench(workbench)
        if current is not None:
            Gui.activateWorkbench(current.name())
    return command in Gui.listCommands()


# ---------------------------------------------------------------------------
# Compatibility patches for add-ons, applied at startup. Each one checks that the
# bug is still there, so it switches itself off once the add-on is fixed.

def patch_searchbar():
    """SearchBar crashes on first use in FreeCAD 1.1: listToolbars() raises for
    workbenches never loaded (e.g. Assembly), and its error handler then calls
    workbench.name(), which raises too. Upstream: APEbbers/SearchBar#47."""
    try:
        import inspect

        import ResultsToolbar
    except ImportError:
        return False
    try:
        source = inspect.getsource(ResultsToolbar.getAllToolbars)
    except (OSError, TypeError):
        return False
    if "workbench.name()" not in source:
        return False  # fixed upstream

    def getAllToolbars():
        all_tbs = {}
        for wbname, workbench in _gui().listWorkbenches().items():
            try:
                tbs = workbench.listToolbars()
            except Exception:
                continue
            for tb in tbs:
                all_tbs.setdefault(tb, set()).add(wbname)
        return all_tbs

    ResultsToolbar.getAllToolbars = getAllToolbars
    return True


def apply_patches():
    applied = [name for name, fn in [("SearchBar#47", patch_searchbar)] if fn()]
    if applied:
        App.Console.PrintLog("Fusion FreeCAD: patched %s\n" % ", ".join(applied))
