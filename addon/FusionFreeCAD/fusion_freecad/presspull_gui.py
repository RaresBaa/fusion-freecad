"""Interactive Press/Pull (Q): pick a face, then drag the arrow on it, or type or scroll
a distance, and see it live.

The whole operation is one undo transaction; Cancel aborts it, leaving no trace.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from .presspull import PressPullError, RadiusPull, handle_frame, start

ARROW_COLOR = (0.95, 0.55, 0.16)   # the timeline marker's orange
ARROW_ACTIVE_COLOR = (1.0, 0.75, 0.35)


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


def _arrow(length, color):
    """An arrow along +X from the origin, as a Coin scene graph."""
    from pivy import coin

    root = coin.SoSeparator()
    material = coin.SoMaterial()
    material.diffuseColor.setValue(*color)
    material.emissiveColor.setValue(*(c * 0.4 for c in color))
    root.addChild(material)
    # Cylinders and cones stand along +Y; turn them to +X.
    turn = coin.SoRotation()
    turn.rotation.setValue(coin.SbVec3f(0, 0, 1), -1.5707963)
    root.addChild(turn)
    shaft_length = length * 0.7
    shaft_at = coin.SoTranslation()
    shaft_at.translation.setValue(0, shaft_length / 2, 0)
    shaft = coin.SoCylinder()
    shaft.radius = length * 0.05
    shaft.height = shaft_length
    head_at = coin.SoTranslation()  # adds to shaft_at: from the shaft's middle
    head_at.translation.setValue(0, length / 2, 0)
    head = coin.SoCone()
    head.bottomRadius = length * 0.14
    head.height = length - shaft_length
    for node in (shaft_at, shaft, head_at, head):
        root.addChild(node)
    return root


def _nice_step(x):
    """The largest of 0.1, 0.2, 0.5, 1, 2, 5... mm that is at most x."""
    step = 0.1
    for candidate in (0.2, 0.5, 1, 2, 5, 10, 20, 50):
        if candidate <= x:
            step = candidate
    return step


class DragHandle(QtCore.QObject):
    """Fusion's drag arrow, on the face along its outward normal.

    Dragging is done in Qt, not with a Coin dragger: an event filter on the 3D view
    takes presses near the arrow on screen, so navigation never sees them, and moves
    the arrow and the model from Qt's event handling. (A Coin dragger lost its grab
    when a recompute changed a hole's sketch mid-drag.) ``on_drag(distance)`` gets the
    snapped distance in mm.
    """

    PICK_PIXELS = 8

    def __init__(self, op, on_drag):
        from pivy import coin

        super().__init__()
        self.on_drag = on_drag
        self.dragging = False
        self.hover = False
        self.distance = 0.0
        self.base, self.normal = handle_frame(op.face, op.base.Shape)
        diagonal = op.body.Shape.BoundBox.DiagonalLength
        self.length = min(max(diagonal * 0.15, 3.0), 60.0)
        self.step = _nice_step(self.length / 20)

        frame = coin.SoTransform()
        frame.translation.setValue(self.base.x, self.base.y, self.base.z)
        n = self.normal
        frame.rotation.setValue(coin.SbRotation(coin.SbVec3f(1, 0, 0), coin.SbVec3f(n.x, n.y, n.z)))
        self.offset = coin.SoTranslation()
        self.looks = coin.SoSwitch()
        self.looks.addChild(_arrow(self.length, ARROW_COLOR))
        self.looks.addChild(_arrow(self.length, ARROW_ACTIVE_COLOR))
        self.looks.whichChild = 0
        self.root = coin.SoSeparator()
        for node in (frame, self.offset, self.looks):
            self.root.addChild(node)
        self.view = Gui.ActiveDocument.ActiveView
        self.view.getSceneGraph().addChild(self.root)
        self.viewport = self.view.graphicsView().viewport()
        self.viewport.installEventFilter(self)

    def follow(self, distance):
        """Move the arrow to a distance typed in the panel."""
        if not self.dragging:
            self._place(distance)

    def remove(self):
        try:
            self.viewport.removeEventFilter(self)
            self.viewport.unsetCursor()
            self.view.getSceneGraph().removeChild(self.root)
        except Exception:  # the view was closed
            pass

    def _place(self, distance):
        self.distance = distance
        self.offset.translation.setValue(distance, 0, 0)

    def _screen(self, along):
        """Qt viewport coordinates of the point ``along`` mm up the arrow's axis."""
        x, y = self.view.getPointOnViewport(self.base + self.normal * along)
        return QtCore.QPointF(x, self.viewport.height() - y)

    def _near(self, pos):
        a, b = self._screen(self.distance), self._screen(self.distance + self.length)
        ab, ap = b - a, pos - a
        length2 = QtCore.QPointF.dotProduct(ab, ab)
        t = 0.0 if length2 < 1e-9 else max(0.0, min(1.0, QtCore.QPointF.dotProduct(ap, ab) / length2))
        closest = a + ab * t
        return (pos - closest).manhattanLength() <= self.PICK_PIXELS

    def _set_hover(self, hover):
        if hover != self.hover:
            self.hover = hover
            self.looks.whichChild = 1 if hover else 0
            if hover:
                self.viewport.setCursor(QtCore.Qt.PointingHandCursor)
            else:
                self.viewport.unsetCursor()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                        QtCore.QEvent.MouseButtonRelease):
            return False
        pos = QtCore.QPointF(event.position() if hasattr(event, "position") else event.pos())
        if kind == QtCore.QEvent.MouseButtonPress:
            if event.button() != QtCore.Qt.LeftButton or not self._near(pos):
                return False
            # Screen direction of the axis, measured once: dragging along it by its
            # length in pixels moves the face by the arrow's length in mm.
            a, b = self._screen(self.distance), self._screen(self.distance + self.length)
            axis = b - a
            if QtCore.QPointF.dotProduct(axis, axis) < 4:  # pointing at the camera
                return True
            self.dragging = True
            self._drag = (pos, self.distance, axis)
            self._set_hover(True)
            return True
        if kind == QtCore.QEvent.MouseMove:
            if not self.dragging:
                if not event.buttons():
                    self._set_hover(self._near(pos))
                return False
            start, distance, axis = self._drag
            moved = QtCore.QPointF.dotProduct(pos - start, axis) / QtCore.QPointF.dotProduct(axis, axis)
            snapped = round((distance + moved * self.length) / self.step) * self.step
            if abs(snapped - self.distance) > 1e-9:
                self._place(snapped)
                self.on_drag(snapped)
            return True
        if self.dragging:  # release
            self.dragging = False
            self._set_hover(self._near(pos))
            return True
        return False


class PressPullPanel:
    def __init__(self):
        self.doc = App.ActiveDocument
        self.op = None
        self.handle = None
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
                                "Drag the arrow, type a value or scroll over the field.")
        hint.setWordWrap(True)
        hint.setEnabled(False)
        layout.addRow(hint)

        self.doc.openTransaction("Press/Pull")
        picked = _selected_face()
        if picked is None or not self._start(*picked):
            self.face_label.setText("Click a face of the solid: flat, or a hole, "
                                    "boss or fillet.")
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

    # -- selection ------------------------------------------------------------

    def _start(self, obj, face_name):
        try:
            self.op = start(obj, face_name)
        except PressPullError as e:
            self.face_label.setText("<span style='color:#d9534f'>%s</span>" % e)
            return False
        self._show_face()
        self.distance.setEnabled(True)
        if Gui.ActiveDocument is not None:
            self.handle = DragHandle(self.op, self.distance.setValue)
        QtCore.QTimer.singleShot(0, self._focus_distance)
        return True

    def _show_face(self, error=None):
        text = "%s, %s" % (self.op.base.Label, self.op.face_name)
        if isinstance(self.op, RadiusPull):
            text += "<br>%s: radius %.2f mm" % (self.op.origin.Label, self.op.radius)
        if error:
            text += "<br><span style='color:#d9534f'>%s</span>" % error
        self.face_label.setText(text)

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
        try:
            self.op.set_distance(value)
        except PressPullError as e:  # e.g. a hole shrunk to nothing
            self._show_face(e)
            return
        self.doc.recompute()
        self._show_face()
        if self.handle is not None:
            self.handle.follow(value)

    # -- task dialog API ------------------------------------------------------

    def _cleanup(self):
        if self.handle is not None:
            self.handle.remove()
            self.handle = None
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
