"""Split Body from the GUI: select the body, then the face or plane to split it with."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from .bodies import BodyError, body_of, split
from .presspull_gui import _split_subname

HOW = ("Select a planar face or a plane of the body to split it there, or select the "
       "body first and then (Ctrl+click) the face or plane to split it with.")


def _picks():
    """(selected top-level object, object, subelement) per pick, in selection order."""
    picks = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames or [""]:
            obj, name = _split_subname(sel.Object, sub) if sub else (sel.Object, "")
            picks.append((sel.Object, obj, name))
    return picks


def _is_plane(obj):
    return obj.isDerivedFrom("App::Plane") or obj.isDerivedFrom("PartDesign::Plane")


class SplitBodyCommand:
    def GetResources(self):
        from . import icon

        return {"Pixmap": icon("split_body.svg"),
                "MenuText": "Split Body",
                "ToolTip": "Split a body in pieces along a face or plane; each piece "
                           "becomes a body. " + HOW}

    def Activated(self):
        picks = _picks()
        body = None
        if len(picks) == 1:  # a face or plane of the body itself
            top, tool, sub = picks[0]
            body = body_of(top) or body_of(tool)
        elif len(picks) == 2:
            (_, first, _), (_, tool, sub) = picks
            body = body_of(first)
        if body is None or (not sub.startswith("Face") and not _is_plane(tool)):
            QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Split Body", HOW)
            return
        doc = body.Document
        doc.openTransaction("Split body")
        try:
            pieces = split(body, (tool, sub), 0.0)
            doc.recompute()
        except BodyError as e:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Split Body", str(e))
            return
        doc.commitTransaction()
        Gui.Selection.clearSelection()
        App.Console.PrintMessage("Split %s into %s\n"
                                 % (body.Label, ", ".join(p.Label for p in pieces)))

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()
