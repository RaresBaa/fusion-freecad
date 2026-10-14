"""Interactive Press/Pull (Q): pick a flat face, type or scroll a distance, see it live.

The whole operation is one undo transaction; Cancel aborts it, leaving no trace.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from .presspull import PressPull, PressPullError


def _split_subname(obj, sub):
    """Selections inside bodies can come as ('Body', 'Pad.Face6'); return (Pad, 'Face6')."""
    if "." in sub:
        parts = sub.split(".")
        owner = obj.Document.getObject(parts[-2]) if parts[-2] else None
        return owner or obj, parts[-1]
    return obj, sub


def _selected_face():
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames:
            obj, name = _split_subname(sel.Object, sub)
            if name.startswith("Face"):
                return obj, name
    return None


class PressPullPanel:
    def __init__(self):
        self.doc = App.ActiveDocument
        self.op = None
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Press/Pull")
        layout = QtWidgets.QFormLayout(self.form)

        self.face_label = QtWidgets.QLabel()
        self.face_label.setWordWrap(True)
        layout.addRow("Face:", self.face_label)

        self.distance = QtWidgets.QDoubleSpinBox()
        self.distance.setRange(-10000, 10000)
        self.distance.setDecimals(2)
        self.distance.setSingleStep(1.0)
        self.distance.setSuffix(" mm")
        self.distance.setKeyboardTracking(False)  # update on Enter/arrows, not per digit
        self.distance.setEnabled(False)
        self.distance.valueChanged.connect(self._on_distance)
        layout.addRow("Distance:", self.distance)

        hint = QtWidgets.QLabel("Positive pulls material out, negative pushes it in. "
                                "Type a value or scroll over the field.")
        hint.setWordWrap(True)
        hint.setEnabled(False)
        layout.addRow(hint)

        self.doc.openTransaction("Press/Pull")
        picked = _selected_face()
        if picked is None or not self._start(*picked):
            self.face_label.setText("Click a flat face of the solid.")
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

    # -- selection ------------------------------------------------------------

    def _start(self, obj, face_name):
        try:
            self.op = PressPull(obj, face_name)
        except PressPullError as e:
            self.face_label.setText("<span style='color:#d9534f'>%s</span>" % e)
            return False
        self.face_label.setText("%s, %s" % (self.op.base.Label, face_name))
        self.distance.setEnabled(True)
        QtCore.QTimer.singleShot(0, self._focus_distance)
        return True

    def _focus_distance(self):
        self.distance.setFocus()
        self.distance.selectAll()

    def addSelection(self, doc_name, obj_name, sub, _pnt):
        if self.op is not None or doc_name != self.doc.Name:
            return
        obj, name = _split_subname(self.doc.getObject(obj_name), sub)
        if name.startswith("Face") and self._start(obj, name):
            Gui.Selection.removeObserver(self)

    # -- preview --------------------------------------------------------------

    def _on_distance(self, value):
        if self.op is None:
            return
        self.op.set_distance(value)
        self.doc.recompute()

    # -- task dialog API ------------------------------------------------------

    def _cleanup(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass

    def accept(self):
        self._cleanup()
        # Apply a value still being typed (keyboard tracking is off).
        self.distance.interpretText()
        if self.op is not None and self.op.distance != self.distance.value():
            self._on_distance(self.distance.value())
        if self.op is not None and self.op.feature is not None:
            self.doc.commitTransaction()
        else:
            self.doc.abortTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._cleanup()
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


class PressPullCommand:
    def GetResources(self):
        from . import icon

        return {"Pixmap": icon("presspull.svg"),
                "MenuText": "Press/Pull",
                "ToolTip": "Push or pull a flat face to add or remove material (Q)"}

    def Activated(self):
        Gui.Control.showDialog(PressPullPanel())

    def IsActive(self):
        if App.ActiveDocument is None or Gui.Control.activeDialog():
            return False
        gdoc = Gui.ActiveDocument
        return gdoc is not None and gdoc.getInEdit() is None
