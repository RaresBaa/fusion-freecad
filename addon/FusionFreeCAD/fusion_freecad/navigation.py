"""Fusion-style mouse navigation, active only in Fusion mode.

Fusion: middle-drag pans, Shift+middle-drag orbits, the wheel zooms at the cursor.
FreeCAD's Revit style does exactly that, so in Fusion mode it becomes the navigation
style (the preference, which new views read, and every open view), and the user's own
style comes back when they leave. The previous style is kept in our preferences so it
survives a crash in Fusion mode, like the shortcuts.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import prefs

STYLE = "Gui::RevitNavigationStyle"


def _view_prefs():
    return App.ParamGet("User parameter:BaseApp/Preferences/View")


def enabled():
    return prefs().GetBool("FusionNavigation", True)


def set_enabled(value):
    prefs().SetBool("FusionNavigation", bool(value))
    if value:
        apply()
    else:
        restore()


def _views():
    for doc in App.listDocuments().values():
        gdoc = Gui.getDocument(doc.Name)
        if gdoc is None:
            continue
        for view in gdoc.mdiViewsOfType("Gui::View3DInventor"):
            yield view


def _set_style(style):
    _view_prefs().SetString("NavigationStyle", style)
    for view in _views():
        try:
            if view.getNavigationType() != style:
                view.setNavigationType(style)
        except Exception:
            pass  # a view being closed


def apply():
    if not enabled():
        return
    current = _view_prefs().GetString("NavigationStyle", "Gui::CADNavigationStyle")
    if not prefs().GetString("SavedNavigationStyle", "") and current != STYLE:
        prefs().SetString("SavedNavigationStyle", current)
    _set_style(STYLE)


def restore():
    saved = prefs().GetString("SavedNavigationStyle", "")
    if not saved:
        return
    prefs().RemString("SavedNavigationStyle")
    # If the user picked another style meanwhile, keep theirs.
    if _view_prefs().GetString("NavigationStyle", "") == STYLE:
        _set_style(saved)
