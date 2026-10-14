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
        self.appendToolbar("MCP", commands.BRIDGE_COMMANDS)
        self.appendMenu("Fusion", commands.MENU)

    def Activated(self):
        from fusion_freecad import session

        session.enter()

    def Deactivated(self):
        # Not the end of Fusion mode: FreeCAD also switches workbench to edit
        # sketches and features. session.py decides when Fusion mode really ends.
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(FusionWorkbench())


def _fusion_freecad_autostart():
    from fusion_freecad import bridge, commands, prefs, shortcuts

    commands.register()
    # Undo Fusion shortcuts left behind if FreeCAD last quit inside the workbench.
    workbench = FreeCADGui.activeWorkbench()
    if workbench is None or workbench.name() != "FusionWorkbench":
        shortcuts.restore()
    if prefs().GetBool("AutoStartServer", False):
        bridge.start()


try:
    from PySide import QtCore as _QtCore
    _QtCore.QTimer.singleShot(0, _fusion_freecad_autostart)
except Exception as _e:
    FreeCAD.Console.PrintWarning("Fusion FreeCAD: bridge auto-start skipped: %s\n" % _e)
