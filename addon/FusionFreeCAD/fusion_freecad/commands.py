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


BRIDGE_COMMANDS = ["FusionFreeCAD_StartBridge", "FusionFreeCAD_StopBridge"]
BRIDGE_MENU = BRIDGE_COMMANDS + ["FusionFreeCAD_ToggleAutoStart"]

_registered = False


def register():
    global _registered
    if _registered:
        return
    Gui.addCommand("FusionFreeCAD_StartBridge", _StartBridge())
    Gui.addCommand("FusionFreeCAD_StopBridge", _StopBridge())
    Gui.addCommand("FusionFreeCAD_ToggleAutoStart", _ToggleAutoStart())
    _registered = True
