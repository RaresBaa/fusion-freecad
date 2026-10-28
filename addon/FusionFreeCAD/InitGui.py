# Fusion FreeCAD: registers the Fusion workbench and the MCP bridge commands.
# FreeCAD runs this file with exec(), so __file__ is not available here; the
# fusion_freecad package is importable because FreeCAD puts this folder on sys.path.

import FreeCAD
import FreeCADGui


class FusionWorkbench(FreeCADGui.Workbench):
    MenuText = "Fusion"
    ToolTip = "Fusion 360-style part modelling, plus an MCP bridge for AI agents"

    def __init__(self):
        import fusion_freecad
        self.__class__.Icon = fusion_freecad.icon("workbench.svg")

    def Initialize(self):
        # Importing these registers the Sketcher and PartDesign commands we reuse.
        import SketcherGui  # noqa: F401
        import PartDesignGui  # noqa: F401
        from fusion_freecad import commands, workbench

        commands.register()
        for name, cmds in workbench.TOOLBARS:
            cmds = workbench.available(cmds)
            if cmds:
                self.appendToolbar(name, cmds)
        self.appendMenu("Fusion", commands.MENU)

    def Activated(self):
        from PySide import QtCore
        from fusion_freecad import integrations, session

        session.enter()
        # Once per session: pull in other add-ons' tools (fasteners, sheet metal...).
        # Deferred because it switches workbenches, which can't happen mid-activation.
        QtCore.QTimer.singleShot(0, lambda: integrations.load(self))

    def Deactivated(self):
        # Not the end of Fusion mode: FreeCAD also switches workbench to edit
        # sketches and features. session.py decides when Fusion mode really ends.
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(FusionWorkbench())

# Commands now, not on first activation: the MCP toolbar (layout.py) is in every
# workbench.
try:
    from fusion_freecad import commands as _commands
    _commands.register()
except Exception as _e:
    FreeCAD.Console.PrintWarning("Fusion FreeCAD: commands not registered: %s\n" % _e)


def _fusion_freecad_autostart():
    from fusion_freecad import (bridge, integrations, layout, navigation, prefs,
                                shortcuts, sketcher)

    integrations.apply_patches()
    integrations.restore_after_ribbon()
    layout.migrate()
    layout.install()
    # Undo Fusion shortcuts, navigation and sketcher settings left behind if FreeCAD last quit inside
    # the workbench.
    workbench = FreeCADGui.activeWorkbench()
    if workbench is None or workbench.name() != "FusionWorkbench":
        shortcuts.restore()
        navigation.restore()
        sketcher.restore()
    if prefs().GetBool("AutoStartServer", False):
        bridge.start()


try:
    from PySide import QtCore as _QtCore
    _QtCore.QTimer.singleShot(0, _fusion_freecad_autostart)
except Exception as _e:
    FreeCAD.Console.PrintWarning("Fusion FreeCAD: bridge auto-start skipped: %s\n" % _e)
