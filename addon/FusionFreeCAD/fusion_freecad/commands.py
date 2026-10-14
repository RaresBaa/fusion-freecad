"""FreeCAD GUI commands provided by the addon."""

import FreeCAD as App
import FreeCADGui as Gui

from . import bridge, icon, prefs


class _StartBridge:
    def GetResources(self):
        return {"Pixmap": icon("bridge_start.svg"),
                "MenuText": "Start MCP bridge",
                "ToolTip": "Let AI agents (e.g. Claude Code) control FreeCAD through MCP"}

    def Activated(self):
        bridge.start()

    def IsActive(self):
        return not bridge.is_running()


class _StopBridge:
    def GetResources(self):
        return {"Pixmap": icon("bridge_stop.svg"),
                "MenuText": "Stop MCP bridge",
                "ToolTip": "Stop accepting commands from AI agents"}

    def Activated(self):
        bridge.stop()

    def IsActive(self):
        return bridge.is_running()


class _ToggleAutoStart:
    def GetResources(self):
        return {"MenuText": "Start MCP bridge with FreeCAD",
                "ToolTip": "Start the MCP bridge automatically when FreeCAD launches",
                "Checkable": prefs().GetBool("AutoStartServer", False)}

    def Activated(self, checked=None):
        if checked is None:
            checked = not prefs().GetBool("AutoStartServer", False)
        prefs().SetBool("AutoStartServer", bool(checked))
        App.Console.PrintMessage("Fusion FreeCAD: bridge auto-start %s\n"
                                 % ("enabled" if checked else "disabled"))

    def IsActive(self):
        return True


class _ToggleTimeline:
    def GetResources(self):
        return {"Pixmap": icon("timeline.svg"),
                "MenuText": "Timeline",
                "ToolTip": "Show or hide the Fusion-style feature timeline",
                "Checkable": prefs().GetBool("ShowTimeline", True)}

    def Activated(self, checked=None):
        from . import timeline

        if checked is None:
            checked = not prefs().GetBool("ShowTimeline", True)
        prefs().SetBool("ShowTimeline", bool(checked))
        if checked:
            timeline.show()
        else:
            timeline.hide()

    def IsActive(self):
        return True


class _ToggleShortcuts:
    def GetResources(self):
        return {"MenuText": "Fusion keyboard shortcuts",
                "ToolTip": "E extrude, F fillet, H hole; in sketches R rectangle, "
                           "D dimension, X construction, O offset. "
                           "Only active in the Fusion workbench.",
                "Checkable": prefs().GetBool("FusionShortcuts", True)}

    def Activated(self, checked=None):
        from . import shortcuts

        if checked is None:
            checked = not shortcuts.enabled()
        shortcuts.set_enabled(checked)

    def IsActive(self):
        return True


class _ToggleSketcherOverride:
    def GetResources(self):
        return {"MenuText": "Use Fusion keys L, C, P in sketches",
                "ToolTip": "L line, C circle, P project, like Fusion. This takes those keys "
                           "from FreeCAD's sketcher (horizontal distance, coincident, "
                           "parallel) while in the Fusion workbench.",
                "Checkable": prefs().GetBool("OverrideSketcherKeys", False)}

    def Activated(self, checked=None):
        from . import shortcuts

        if checked is None:
            checked = not shortcuts.override_sketcher_keys()
        shortcuts.set_override_sketcher_keys(checked)

    def IsActive(self):
        return True


class _ShowToolbars:
    """Some add-ons (FreeCAD Ribbon) hide the classic toolbars and save that; this
    brings the Fusion workbench's toolbars back."""

    def GetResources(self):
        return {"MenuText": "Show all Fusion toolbars",
                "ToolTip": "Make every toolbar of the Fusion workbench visible again"}

    def Activated(self):
        from PySide import QtWidgets

        names = set(Gui.getWorkbench("FusionWorkbench").listToolbars())
        stored = App.ParamGet("User parameter:BaseApp/MainWindow/Toolbars")
        for name in names:
            stored.SetBool(name, True)
        for bar in Gui.getMainWindow().findChildren(QtWidgets.QToolBar):
            if bar.objectName() in names:
                bar.setVisible(True)

    def IsActive(self):
        return True


BRIDGE_COMMANDS = ["FusionFreeCAD_StartBridge", "FusionFreeCAD_StopBridge"]
MENU = ["FusionFreeCAD_ToggleTimeline", "FusionFreeCAD_ToggleShortcuts",
        "FusionFreeCAD_ToggleSketcherOverride", "FusionFreeCAD_ShowToolbars",
        "Separator",
        "FusionFreeCAD_StartBridge", "FusionFreeCAD_StopBridge",
        "FusionFreeCAD_ToggleAutoStart"]

_registered = False


def register():
    global _registered
    if _registered:
        return
    Gui.addCommand("FusionFreeCAD_StartBridge", _StartBridge())
    Gui.addCommand("FusionFreeCAD_StopBridge", _StopBridge())
    Gui.addCommand("FusionFreeCAD_ToggleAutoStart", _ToggleAutoStart())
    Gui.addCommand("FusionFreeCAD_ToggleTimeline", _ToggleTimeline())
    Gui.addCommand("FusionFreeCAD_ToggleShortcuts", _ToggleShortcuts())
    Gui.addCommand("FusionFreeCAD_ToggleSketcherOverride", _ToggleSketcherOverride())
    Gui.addCommand("FusionFreeCAD_ShowToolbars", _ShowToolbars())

    from .presspull_gui import PressPullCommand
    Gui.addCommand("FusionFreeCAD_PressPull", PressPullCommand())
    _registered = True
