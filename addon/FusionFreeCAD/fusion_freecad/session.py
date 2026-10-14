"""Keeps "Fusion mode" alive across FreeCAD's automatic workbench switches.

FreeCAD switches workbench by itself when you edit something: editing a sketch
activates the Sketcher workbench, and PartDesign feature dialogs activate PartDesign.
Treating those as leaving the Fusion workbench would hide the timeline and drop the
shortcuts mid-edit, and leave you in another workbench afterwards. Instead:

- A switch to Sketcher/PartDesign while something is being edited is an "excursion":
  the timeline and shortcuts stay, and when the edit ends we switch back to Fusion.
- Any other switch means the user left on purpose: Fusion mode ends, the timeline
  hides and the original shortcuts come back.

A short poll is used because the edit state isn't settled yet when FreeCAD calls
Workbench.Deactivated().
"""

import contextlib

import FreeCADGui as Gui
from PySide import QtCore

from . import prefs, shortcuts, timeline

FUSION = "FusionWorkbench"
EDIT_WORKBENCHES = {"SketcherWorkbench", "PartDesignWorkbench"}
POLL_MS = 250

_timer = None
_excursion = False
_suspended = 0


@contextlib.contextmanager
def suspended():
    """Switch workbenches on purpose (e.g. to load an add-on) without ending Fusion mode."""
    global _suspended
    _suspended += 1
    try:
        yield
    finally:
        _suspended -= 1


def _editing():
    gdoc = Gui.ActiveDocument
    if gdoc is not None and gdoc.getInEdit() is not None:
        return True
    return Gui.Control.activeDialog()


def _sketch_in_edit():
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc is not None else None
    return vp is not None and vp.Object.TypeId == "Sketcher::SketchObject"


def enter():
    """Called when the Fusion workbench is activated."""
    global _timer, _excursion
    if _suspended:
        return
    _excursion = False
    shortcuts.apply()
    if prefs().GetBool("ShowTimeline", True):
        timeline.show()
    if _timer is None:
        _timer = QtCore.QTimer()
        _timer.timeout.connect(_tick)
    _timer.start(POLL_MS)


def leave():
    global _excursion
    _excursion = False
    if _timer is not None:
        _timer.stop()
    shortcuts.restore()
    timeline.hide()


def _tick():
    global _excursion
    if _suspended:
        return
    wb = Gui.activeWorkbench()
    name = wb.name() if wb is not None else None

    if name == FUSION:
        _excursion = False
    elif name in EDIT_WORKBENCHES and (_excursion or _editing()):
        if _editing():
            _excursion = True
        else:
            # The edit that took us away has finished: come home.
            _excursion = False
            Gui.activateWorkbench(FUSION)
            return
    else:
        leave()
        return

    # Sketcher tool actions only exist once a sketch has been opened, so the
    # sketch keys can only be bound from inside the sketcher.
    if _sketch_in_edit():
        shortcuts.apply_sketch()
