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


class _ToggleGroupSketches:
    def GetResources(self):
        return {"MenuText": "Group sketches in timeline",
                "ToolTip": "Show a feature's own sketch in the feature's timeline slot",
                "Checkable": prefs().GetBool("GroupSketches", True)}

    def Activated(self, checked=None):
        from . import timeline

        if checked is None:
            checked = not prefs().GetBool("GroupSketches", True)
        prefs().SetBool("GroupSketches", bool(checked))
        timeline.refresh()

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


class _ToggleSketcher:
    def GetResources(self):
        return {"MenuText": "Fusion sketcher settings",
                "ToolTip": "Auto-constraints, on-view dimensions while drawing, snap to "
                           "objects, and Esc cancels the tool without closing the sketch. "
                           "Only active in the Fusion workbench.",
                "Checkable": prefs().GetBool("FusionSketcher", True)}

    def Activated(self, checked=None):
        from . import sketcher

        if checked is None:
            checked = not sketcher.enabled()
        sketcher.set_enabled(checked)

    def IsActive(self):
        return True


class _ToggleProfiles:
    def GetResources(self):
        return {"MenuText": "Shade sketch profiles",
                "ToolTip": "Fill the closed regions of the sketch being edited, like "
                           "Fusion's profiles",
                "Checkable": prefs().GetBool("ShadeProfiles", True)}

    def Activated(self, checked=None):
        from . import sketcher_gui

        if checked is None:
            checked = not sketcher_gui.enabled()
        sketcher_gui.set_enabled(checked)

    def IsActive(self):
        return True


class _ToggleNavigation:
    def GetResources(self):
        return {"MenuText": "Fusion mouse navigation",
                "ToolTip": "Middle-drag pans, Shift+middle-drag orbits, the wheel zooms "
                           "(FreeCAD's Revit style). Only active in the Fusion workbench.",
                "Checkable": prefs().GetBool("FusionNavigation", True)}

    def Activated(self, checked=None):
        from . import navigation

        if checked is None:
            checked = not navigation.enabled()
        navigation.set_enabled(checked)

    def IsActive(self):
        return True


class _ToggleMarkingMenu:
    def GetResources(self):
        return {"MenuText": "Marking menu on right-click",
                "ToolTip": "Fusion's radial menu in the 3D view: right-click for a ring of "
                           "commands, or right-drag towards one to run it. \"More...\" "
                           "opens FreeCAD's menu. Only active in the Fusion workbench.",
                "Checkable": prefs().GetBool("MarkingMenu", True)}

    def Activated(self, checked=None):
        from . import marking

        if checked is None:
            checked = not marking.enabled()
        marking.set_enabled(checked)

    def IsActive(self):
        return True


class _ToggleTabs:
    def GetResources(self):
        return {"MenuText": "Toolbar tabs",
                "ToolTip": "SOLID / SHEET METAL / 3D PRINT / INSERT tabs above the "
                           "toolbars, each showing its own tool groups, like Fusion",
                "Checkable": prefs().GetBool("FusionTabs", True)}

    def Activated(self, checked=None):
        from . import tabs

        if checked is None:
            checked = not prefs().GetBool("FusionTabs", True)
        tabs.set_enabled(checked)

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
        from . import tabs
        if tabs.showing():
            tabs.show()  # back to the selected tab's groups

    def IsActive(self):
        return True


class _SearchAtCursor:
    """S: SearchBar's search box at the mouse, like Fusion's S toolbox.

    Wraps SearchBar's own command so the key can live on an action we control: it's
    off while a sketch is being edited, where S is FreeCAD's Symmetric constraint.
    """

    def GetResources(self):
        return {"MenuText": "Search at cursor",
                "ToolTip": "Search commands, objects and preferences at the mouse "
                           "(SearchBar add-on)"}

    def Activated(self):
        from PySide import QtCore, QtGui, QtWidgets

        Gui.runCommand("SearchBar", 0)
        # SearchBar moves its box to the cursor's screen position in main-window
        # coordinates, so it lands off-screen unless FreeCAD sits at (0, 0).
        mw = Gui.getMainWindow()
        bar = mw.findChild(QtWidgets.QToolBar, "SearchBarAtMouse")
        if bar is None or not bar.isVisible():
            return
        # The box is nested in a wrapper toolbar; move the outermost one.
        outer = bar
        while outer.parentWidget() is not None and outer.parentWidget() is not mw:
            outer = outer.parentWidget()
        target = QtGui.QCursor.pos() + QtCore.QPoint(10, -10)
        outer.move(mw.mapFromGlobal(target) if outer.parentWidget() is mw else target)
        # Reopened, it keeps the last text and doesn't take focus, so typing would
        # trigger shortcuts in the 3D view instead. Start empty and focused, like Fusion.
        line = bar.findChild(QtWidgets.QLineEdit)
        if line is not None:
            line.clear()
            line.setFocus(QtCore.Qt.ShortcutFocusReason)

    def IsActive(self):
        from .session import _sketch_in_edit
        return "SearchBar" in Gui.listCommands() and not _sketch_in_edit()


BRIDGE_COMMANDS = ["FusionFreeCAD_StartBridge", "FusionFreeCAD_StopBridge"]
MENU = ["FusionFreeCAD_ToggleTimeline", "FusionFreeCAD_ToggleGroupSketches",
        "FusionFreeCAD_ToggleShortcuts",
        "FusionFreeCAD_ToggleSketcherOverride", "FusionFreeCAD_ToggleSketcher",
        "FusionFreeCAD_ToggleProfiles", "FusionFreeCAD_ToggleNavigation",
        "FusionFreeCAD_ToggleMarkingMenu",
        "FusionFreeCAD_ToggleTabs", "FusionFreeCAD_ShowToolbars",
        "FusionFreeCAD_SearchAtCursor",
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
    Gui.addCommand("FusionFreeCAD_ToggleGroupSketches", _ToggleGroupSketches())
    Gui.addCommand("FusionFreeCAD_ToggleShortcuts", _ToggleShortcuts())
    Gui.addCommand("FusionFreeCAD_ToggleSketcherOverride", _ToggleSketcherOverride())
    Gui.addCommand("FusionFreeCAD_ToggleSketcher", _ToggleSketcher())
    Gui.addCommand("FusionFreeCAD_ToggleProfiles", _ToggleProfiles())
    Gui.addCommand("FusionFreeCAD_ToggleNavigation", _ToggleNavigation())
    Gui.addCommand("FusionFreeCAD_ToggleMarkingMenu", _ToggleMarkingMenu())
    Gui.addCommand("FusionFreeCAD_ToggleTabs", _ToggleTabs())
    Gui.addCommand("FusionFreeCAD_ShowToolbars", _ShowToolbars())
    Gui.addCommand("FusionFreeCAD_SearchAtCursor", _SearchAtCursor())

    from .presspull_gui import PressPullCommand
    Gui.addCommand("FusionFreeCAD_PressPull", PressPullCommand())
    from .bodies_gui import SplitBodyCommand
    Gui.addCommand("FusionFreeCAD_SplitBody", SplitBodyCommand())
    from .parameters_gui import ChangeParametersCommand
    Gui.addCommand("FusionFreeCAD_ChangeParameters", ChangeParametersCommand())
    _registered = True
