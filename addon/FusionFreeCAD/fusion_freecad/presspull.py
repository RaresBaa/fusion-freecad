"""Press/Pull: push or pull a planar face of a solid by a distance, like Fusion's Q.

A positive distance adds material (a PartDesign Pad using the face as its profile, so
it grows along the face normal); a negative one removes it (a Pocket into the solid).
Using the face directly keeps the history readable: no hidden sketches.

No Qt here; the interactive tool lives in presspull_gui.py.
"""

import FreeCAD as App

from . import history


class PressPullError(ValueError):
    pass


def resolve_face(obj, face_name):
    """Map a selection (feature or body + 'FaceN') to the solid feature that owns it."""
    if obj.TypeId == "PartDesign::Body":
        if obj.Tip is None:
            raise PressPullError("body %s has no solid yet" % obj.Name)
        obj = obj.Tip
    if not history.is_feature(obj):
        raise PressPullError("%s is not a PartDesign solid feature" % obj.Name)
    body = history.body_of(obj)
    if body is None:
        raise PressPullError("%s is not inside a body" % obj.Name)
    if not face_name.startswith("Face"):
        raise PressPullError("select a face, not %s" % face_name)
    try:
        face = obj.Shape.getElement(face_name)
    except Exception:
        raise PressPullError("%s has no %s" % (obj.Name, face_name))
    if type(face.Surface).__name__ != "Plane":
        raise PressPullError("Press/Pull works on flat faces; %s is a %s"
                             % (face_name, type(face.Surface).__name__))
    return body, obj


class PressPull:
    """One press/pull operation whose distance can be changed until it's finished.

    The feature is replaced when the distance changes sign (Pad <-> Pocket) and
    removed at zero. Callers handle transactions and recompute.
    """

    def __init__(self, obj, face_name):
        self.body, self.base = resolve_face(obj, face_name)
        self.face_name = face_name
        self.feature = None
        self.distance = 0.0

    def set_distance(self, distance):
        distance = float(distance)
        wanted = None if abs(distance) < 1e-9 else (
            "PartDesign::Pad" if distance > 0 else "PartDesign::Pocket")
        if self.feature is not None and (wanted is None or self.feature.TypeId != wanted):
            self._remove()
        if wanted is not None and self.feature is None:
            self._create(wanted)
        if self.feature is not None:
            self.feature.Length = abs(distance)
        self.distance = distance

    def _create(self, type_id):
        name = "PressPull" if type_id.endswith("Pad") else "PressPullCut"
        previous_tip = self.body.Tip
        feature = self.body.newObject(type_id, name)
        feature.Profile = (self.base, [self.face_name])
        feature.Type = "Length"
        if App.GuiUp:
            if previous_tip is not None:
                previous_tip.Visibility = False
            feature.Visibility = True
        self.feature = feature

    def _remove(self):
        feature, self.feature = self.feature, None
        doc = feature.Document
        # Removing a body's tip makes the previous feature the tip again.
        self.body.removeObject(feature)
        doc.removeObject(feature.Name)
        if App.GuiUp and self.body.Tip is not None:
            self.body.Tip.Visibility = True
