"""Other FreeCAD add-ons that the Fusion workbench builds on.

Each add-on is optional at runtime: its toolbar group appears only if it's installed.
Add-on commands only exist after their workbench has been loaded once, so the first
time the Fusion workbench is activated, ``load()`` activates each installed add-on's
workbench in the background, adds our toolbar groups, and comes back to Fusion.

The same registry drives package.xml dependencies, the install scripts (addons.json)
and the Nix flake inputs; keep them in sync (scripts/check-addons.py verifies this).
"""

import re

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
        # Not "Sheet Metal": FreeCAD stores toolbar visibility by name, and that's
        # the SheetMetal workbench's own toolbar.
        ("Sheet Metal Tools", ["SheetMetal_AddBase", "SheetMetal_AddWall",
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
    import sys
    if os.path.isdir(os.path.join(App.getUserAppDataDir(), "Mod", addon.name)):
        return True
    # Loaded with --module-path (e.g. the Nix flake's FreeCAD): on sys.path by folder name.
    return any(os.path.basename(os.path.normpath(p)) == addon.name for p in sys.path if p)


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
    _quiet_threadprofile()
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


def _quiet_threadprofile():
    """ThreadProfile re-shows its toolbar in every workbench after you leave it once
    (its KeepToolbar setting). Loading it in the background would put it everywhere;
    its tools are in our Threads group, so turn that off unless the user set it."""
    pg = App.ParamGet("User parameter:BaseApp/Preferences/Mod/ThreadProfile")
    if "KeepToolbar" not in pg.GetBools():
        pg.SetBool("KeepToolbar", False)


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


_ELEMENT = re.compile(r"\S*[.;]((?:Vertex|Edge|Face)\d+)\b")


def short_element_names(text):
    """'Pad.;#f:2;:H5f2:7,E.Edge1' (a selection's full subname) -> 'Edge1'."""
    return _ELEMENT.sub(r"\1", text)


def patch_quickmeasure():
    """QuickMeasure names what it measured by the selection's full subname, which in
    FreeCAD 1.x includes the toponaming map ('Pad.;#f:2;...Edge1'). Show 'Edge1'."""
    try:
        import inspect

        import CD_Measure
    except ImportError:
        return False
    method = CD_Measure.measureClass.measureSelected
    if getattr(method, "_fusion_patched", False):
        return False
    try:
        source = inspect.getsource(method)
    except (OSError, TypeError):
        return False
    if "f0.fname, f0.bodyname" not in source:
        return False  # changed upstream

    def measureSelected(self):
        method(self)
        box = CD_Measure.form1.txtboxReport
        text = box.toPlainText()
        short = short_element_names(text)
        if short != text:
            box.setText(short)

    measureSelected._fusion_patched = True
    CD_Measure.measureClass.measureSelected = measureSelected
    return True


def apply_patches():
    applied = [name for name, fn in [("SearchBar#47", patch_searchbar),
                                     ("QuickMeasure names", patch_quickmeasure)] if fn()]
    if applied:
        App.Console.PrintLog("Fusion FreeCAD: patched %s\n" % ", ".join(applied))


# ---------------------------------------------------------------------------
# Leftovers of add-ons that change the whole interface.

RIBBON_PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeCAD-Ribbon"
TOOLBAR_PARAMS = "User parameter:BaseApp/MainWindow/Toolbars"


def ribbon_removed(ribbon_installed, ribbon_params=RIBBON_PARAMS):
    """True once, on the first start after FreeCAD Ribbon was uninstalled.

    Ribbon hides every classic toolbar and FreeCAD saves that, so without Ribbon the
    toolbars would stay hidden. Its settings group outlives it, which tells us it was
    there (also when it was removed before Fusion FreeCAD was installed)."""
    pg = prefs()
    if ribbon_installed:
        pg.SetString("Ribbon", "installed")
        return False
    state = pg.GetString("Ribbon", "")
    if state == "cleaned":
        return False
    seen = state == "installed" or bool(App.ParamGet(ribbon_params).GetContents())
    pg.SetString("Ribbon", "cleaned" if seen else "never")
    return seen


HIDDEN_BY_DEFAULT = {"Clipboard", "Individual Views", "Macro"}  # FreeCAD 1.1


def show_hidden_toolbars(toolbar_params=TOOLBAR_PARAMS):
    """Mark every toolbar stored as hidden visible again, except the ones FreeCAD
    hides by default; returns their names."""
    stored = App.ParamGet(toolbar_params)
    names = [n for n in stored.GetBools()
             if not stored.GetBool(n, True) and n not in HIDDEN_BY_DEFAULT]
    for name in names:
        stored.SetBool(name, True)
    return names


def restore_after_ribbon():
    """Bring the toolbars and menu bar back after FreeCAD Ribbon was removed."""
    ribbon = next(a for a in ADDONS if a.name == "FreeCAD-Ribbon")
    if not ribbon_removed(is_installed(ribbon)):
        return
    names = set(show_hidden_toolbars())
    from PySide import QtWidgets
    mw = _gui().getMainWindow()
    mw.menuBar().show()
    for bar in mw.findChildren(QtWidgets.QToolBar):
        if bar.objectName() in names:
            bar.setVisible(True)
    App.Console.PrintMessage("Fusion FreeCAD: FreeCAD Ribbon was removed; showed the "
                             "%d toolbars it had hidden\n" % len(names))


# PieMenu opens on Tab, which the sketcher uses to move between on-view inputs.
# In Fusion mode its key is off while a sketch is open (our marking menu works there).
PIE_ACTION = "PieMenuShortCut"


def _pie_action():
    from PySide import QtGui
    action_type = getattr(QtGui, "QAction", None)
    if action_type is None:
        from PySide import QtWidgets
        action_type = QtWidgets.QAction
    return _gui().getMainWindow().findChild(action_type, PIE_ACTION)


def set_pie_menu_key(enabled):
    action = _pie_action()
    if action is not None and action.isEnabled() != enabled:
        action.setEnabled(enabled)
