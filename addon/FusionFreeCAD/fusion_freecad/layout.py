"""Toolbar layout outside the Fusion workbench's own groups.

The first toolbar row is FreeCAD's standard toolbars, then SearchBar and the MCP
bridge buttons, in every workbench; the workbench's own toolbars share one row below
it (in Fusion, below the tab row). That holds whatever layout FreeCAD saved.

FreeCAD doesn't keep that by itself: it appends a workbench's new toolbars to the
last row (and only breaks a row when it's full), SearchBar re-adds its toolbar at the
end on every workbench switch, and global custom toolbars are rebuilt on every switch.
So the MCP toolbar is our own (like SearchBar's, FreeCAD leaves it alone), and after
each workbench switch ``arrange()`` puts the first row back in order.

Also: FreeCAD remembers each toolbar's visibility by name when you leave a workbench,
so groups hidden by a Fusion tab must not stay "hidden" there.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import prefs

MCP_TOOLBAR = "MCP"
TOP_ROW = ["SearchBar", MCP_TOOLBAR]
# FreeCAD's own toolbars, shown in every workbench, in FreeCAD's order.
STANDARD = ["File", "Edit", "Clipboard", "Workbench", "Macro", "View",
            "Individual Views", "Structure", "Help"]
_STORED = "User parameter:BaseApp/MainWindow/Toolbars"

_mcp_bar = None
_connected = False


def enabled():
    return prefs().GetBool("ArrangeToolbars", True)


def _mw():
    return Gui.getMainWindow()


def mcp_toolbar():
    """Our MCP toolbar (start/stop bridge), created once, never owned by a workbench."""
    global _mcp_bar
    from PySide import QtWidgets

    from . import commands

    if _mcp_bar is not None:
        return _mcp_bar
    from PySide import QtCore, QtGui

    mw = _mw()
    bar = QtWidgets.QToolBar(MCP_TOOLBAR, mw)
    bar.setObjectName(MCP_TOOLBAR)
    # Our own actions: FreeCAD only creates a command's QAction once it's in a menu
    # or workbench toolbar, which may not have happened yet.
    actions = []
    for name in commands.BRIDGE_COMMANDS:
        info = Gui.Command.get(name).getInfo()
        action = bar.addAction(QtGui.QIcon(info["pixmap"]), info["menuText"])
        action.setToolTip(info["toolTip"])
        action.triggered.connect(lambda _=False, n=name: Gui.runCommand(n, 0))
        actions.append((name, action))

    def refresh():
        if bar.isVisible():
            for name, action in actions:
                action.setEnabled(Gui.Command.get(name).isActive())

    timer = QtCore.QTimer(bar)
    timer.timeout.connect(refresh)
    timer.start(500)
    mw.addToolBar(bar)
    bar.setVisible(App.ParamGet(_STORED).GetBool(MCP_TOOLBAR, True))
    _mcp_bar = bar
    return bar


def _top_bars():
    from PySide import QtCore, QtWidgets

    mw = _mw()
    bars = [b for b in mw.findChildren(QtWidgets.QToolBar)
            if b.parentWidget() is mw and b.isVisible()
            and mw.toolBarArea(b) == QtCore.Qt.TopToolBarArea]
    return sorted(bars, key=lambda b: (b.geometry().y(), b.geometry().x()))


def arrange():
    """First row: every standard toolbar (even ones a saved layout put lower down),
    SearchBar, MCP. Everything else goes on one row below (the Fusion tab row stays
    a row of its own)."""
    from .tabs import BAR_NAME
    if not enabled():
        return
    mw = _mw()
    bars = _top_bars()
    if not bars:
        return
    first_y = bars[0].geometry().y()
    row = [b for b in bars if b.geometry().y() == first_y]
    by_name = {b.objectName(): b for b in bars}
    wanted = [by_name[n] for n in STANDARD + TOP_ROW if n in by_name]
    intruders = [b for b in row if b not in wanted]
    rest = [b for b in bars if b.geometry().y() != first_y and b not in wanted
            and b.objectName() != BAR_NAME]
    if row == wanted and len({b.geometry().y() for b in rest}) <= 1:
        return  # already right
    # Build the row in front of its current first toolbar: insertToolBar(before, bar)
    # moves bar, from any row, to just ahead of `before`.
    anchor = row[0]
    for b in wanted:
        if b is not anchor:
            mw.insertToolBar(anchor, b)
    if anchor in wanted:
        after = wanted[wanted.index(anchor) + 1:]
        if after:
            mw.insertToolBar(after[0], anchor)
    # Workbench toolbars all go on the last row below it (a new one if needed), in
    # order: inserting them in turn before the last one keeps their order.
    if rest:
        last = rest[-1]
        for b in intruders + rest[:-1]:
            mw.insertToolBar(last, b)
    elif intruders:
        for b in intruders:
            mw.removeToolBar(b)  # also hides it
        mw.addToolBarBreak()
        for b in intruders:
            mw.addToolBar(b)
            b.show()


def _on_workbench(_name=None):
    from PySide import QtCore

    # After FreeCAD and SearchBar have added their toolbars.
    QtCore.QTimer.singleShot(0, arrange)


def install():
    """Create the MCP toolbar and keep the first row in order from now on."""
    global _connected
    mcp_toolbar()
    if not _connected:
        _mw().workbenchActivated.connect(_on_workbench)
        _connected = True
    _on_workbench()


def reset_stored_visibility(names):
    """Forget "hidden" for toolbars we hid ourselves (Fusion tabs)."""
    stored = App.ParamGet(_STORED)
    for name in names:
        if not stored.GetBool(name, True):
            stored.SetBool(name, True)


def migrate():
    """One-off fixes for settings written by earlier versions."""
    if prefs().GetBool("LayoutMigrated1", False):
        return
    # Our tab-hidden "Sheet Metal" group shared its name with the SheetMetal
    # workbench's toolbar, which then showed up empty.
    reset_stored_visibility(["Sheet Metal", "Fasteners", "Gears", "Threads", "3D Print"])
    prefs().SetBool("LayoutMigrated1", True)
