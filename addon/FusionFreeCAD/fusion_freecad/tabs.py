"""Fusion-style tabs (SOLID, SHEET METAL, ...) above the Fusion toolbars.

Each tab shows a set of the workbench's toolbar groups and hides the rest, like
Fusion's toolbar tabs, so the add-on groups don't crowd one long row. It's a plain
tab bar over FreeCAD's own toolbars, not a ribbon: the FreeCAD Ribbon add-on replaces
every toolbar (and saves that), so when it's installed the tabs stay off.
"""

import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import prefs

# (tab, toolbar groups). Groups that don't exist (add-on not installed) are skipped,
# and so are tabs left with nothing but Sketch/Inspect.
TABS = [
    ("Solid", ["Sketch", "Create", "Modify", "Pattern", "Construct", "Inspect"]),
    ("Sheet Metal", ["Sketch", "Sheet Metal Tools", "Construct", "Inspect"]),
    ("3D Print", ["Sketch", "3D Print", "Threads", "Inspect"]),
    ("Insert", ["Fasteners", "Gears", "Threads", "Inspect"]),
]
COMMON = {"Sketch", "Construct", "Inspect"}
BAR_NAME = "FusionTabs"

_bar = None


def enabled():
    from . import integrations
    ribbon = next(a for a in integrations.ADDONS if a.name == "FreeCAD-Ribbon")
    return prefs().GetBool("FusionTabs", True) and not integrations.is_installed(ribbon)


def _groups():
    """Our toolbar groups in the Fusion workbench (its list also has File, View...)."""
    from . import integrations, workbench

    ours = {n for n, _ in workbench.TOOLBARS} | {n for n, _ in integrations.toolbars()}
    return ours & set(Gui.getWorkbench("FusionWorkbench").listToolbars())


def all_groups():
    return set(_order())


def tabs():
    groups = _groups()
    out = []
    for name, wanted in TABS:
        present = [g for g in wanted if g in groups]
        if set(present) - COMMON:
            out.append((name, present))
    return out


def showing():
    return _bar is not None and _bar.isVisible()


def current():
    """Groups shown by the selected tab (all groups if the tabs are off)."""
    available = tabs()
    if not showing() or not available:
        return _groups()
    index = min(_bar.tabs.currentIndex(), len(available) - 1)
    return set(available[max(index, 0)][1])


def _toolbars():
    mw = Gui.getMainWindow()
    return [b for b in mw.findChildren(QtWidgets.QToolBar) if b.parentWidget() is mw]


def _apply():
    groups = _groups()
    shown = current()
    for bar in _toolbars():
        name = bar.objectName()
        if name in groups:
            bar.setVisible(name in shown)
    prefs().SetString("FusionTab", _bar.tabs.tabText(_bar.tabs.currentIndex()))


class _TabBar(QtWidgets.QToolBar):
    def __init__(self, parent):
        super().__init__("Fusion tabs", parent)
        self.setObjectName(BAR_NAME)
        self.setMovable(False)
        self.setFloatable(False)
        self.toggleViewAction().setVisible(False)  # not in View > Toolbars
        self.tabs = QtWidgets.QTabBar(self)
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setFocusPolicy(QtCore.Qt.NoFocus)
        font = self.tabs.font()
        font.setBold(True)
        self.tabs.setFont(font)
        # Fusion marks the active tab with a blue underline.
        self.tabs.setStyleSheet(
            "QTabBar::tab { padding: 3px 12px; border: none;"
            " border-bottom: 2px solid transparent; background: transparent; }"
            "QTabBar::tab:selected { border-bottom-color: #0696d7; }")
        self.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda _: _apply())

    def set_tabs(self, names):
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for name in names:
            self.tabs.addTab(name.upper())
        self.tabs.blockSignals(False)
        saved = prefs().GetString("FusionTab", "")
        labels = [n.upper() for n in names]
        self.tabs.setCurrentIndex(labels.index(saved) if saved in labels else 0)


def _order():
    from . import integrations, workbench

    names = [n for n, _ in workbench.TOOLBARS] + [n for n, _ in integrations.toolbars()]
    return names


def _place(bar):
    """Tab row on its own line, then all our groups on one line below it, so each
    tab's groups sit in one row (hidden toolbars take no space)."""
    mw = Gui.getMainWindow()
    by_name = {b.objectName(): b for b in _toolbars() if b is not bar}
    groups = [by_name[n] for n in _order() if n in by_name]
    area = QtCore.Qt.TopToolBarArea
    visible = {b: b.isVisible() for b in groups}
    for b in [bar] + groups:
        mw.removeToolBar(b)  # also hides it
    mw.addToolBarBreak(area)
    mw.addToolBar(area, bar)
    mw.addToolBarBreak(area)
    for b in groups:
        mw.addToolBar(area, b)
        b.setVisible(visible[b])
    bar.show()


def show():
    """Show the tabs (Fusion mode). Safe to call again, e.g. after add-on groups load."""
    global _bar
    if not enabled():
        hide()
        return
    names = [n for n, _ in tabs()]
    if len(names) < 2:
        hide()
        return
    if _bar is None:
        _bar = _TabBar(Gui.getMainWindow())
    _bar.set_tabs(names)
    _place(_bar)
    _apply()


def hide():
    if _bar is not None and _bar.isVisible():
        _bar.hide()


def set_enabled(value):
    prefs().SetBool("FusionTabs", bool(value))
    if value:
        show()
    else:
        hide()
        groups = _groups()
        for bar in _toolbars():
            if bar.objectName() in groups:
                bar.setVisible(True)
