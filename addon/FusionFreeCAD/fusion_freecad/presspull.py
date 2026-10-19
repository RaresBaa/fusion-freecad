"""Press/Pull: push or pull a face of a solid by a distance, like Fusion's Q.

Flat faces: a positive distance adds material (a PartDesign Pad using the face as its
profile, so it grows along the face normal); a negative one removes it (a Pocket into
the solid). Using the face directly keeps the history readable: no hidden sketches.

Cylindrical faces (holes, bosses, fillets): PartDesign has no "offset face" feature,
so we find the feature that created the surface and change its size instead: a
Fillet's radius, a Hole's diameter or counterbore, or the circle in a Pad's or
Pocket's sketch. Positive still means "adds material": a hole gets smaller, a boss
bigger, an outside fillet sharper.

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
    return body, obj, face


def start(obj, face_name):
    """The right Press/Pull operation for the face: flat or cylindrical."""
    _, _, face = resolve_face(obj, face_name)
    kind = type(face.Surface).__name__
    if kind == "Plane":
        return PressPull(obj, face_name)
    if kind in ("Cylinder", "Toroid"):
        return RadiusPull(obj, face_name)
    raise PressPullError("Press/Pull works on flat and cylindrical faces; %s is a %s"
                         % (face_name, kind))


class PressPull:
    """One press/pull operation whose distance can be changed until it's finished.

    The feature is replaced when the distance changes sign (Pad <-> Pocket) and
    removed at zero. Callers handle transactions and recompute.
    """

    def __init__(self, obj, face_name):
        self.body, self.base, face = resolve_face(obj, face_name)
        if type(face.Surface).__name__ != "Plane":
            raise PressPullError("%s is curved; use start() for curved faces" % face_name)
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


# ---------------------------------------------------------------------------
# cylindrical faces

_TOL = 1e-6


def _same_surface(a, b):
    kind = type(a).__name__
    if kind != type(b).__name__ or a.Axis.cross(b.Axis).Length > _TOL:
        return False
    if kind == "Cylinder":
        offset = b.Center - a.Center
        off_axis = offset - a.Axis * offset.dot(a.Axis)
        return abs(a.Radius - b.Radius) < _TOL and off_axis.Length < _TOL
    return (abs(a.MinorRadius - b.MinorRadius) < _TOL
            and abs(a.MajorRadius - b.MajorRadius) < _TOL
            and (a.Center - b.Center).Length < _TOL)


def _has_surface(shape, surface):
    return shape is not None and not shape.isNull() and any(
        _same_surface(surface, f.Surface) for f in shape.Faces)


def _radius(surface):
    return surface.Radius if type(surface).__name__ == "Cylinder" else surface.MinorRadius


def _is_convex(face):
    """True when the face bulges outwards (a boss, an outside fillet), not a hole."""
    s = face.Surface
    u0, u1, v0, v1 = face.ParameterRange
    u, v = (u0 + u1) / 2, (v0 + v1) / 2
    p, n = face.valueAt(u, v), face.normalAt(u, v)
    q = p - s.Center
    radial = q - s.Axis * q.dot(s.Axis)
    if type(s).__name__ == "Toroid":
        tube_centre = s.Center + App.Vector(radial).normalize() * s.MajorRadius
        radial = p - tube_centre
    return n.dot(radial) > 0


def _origin_feature(body, base, surface):
    """The feature at or before base whose result first has this surface."""
    features = [o for o in body.Group if history.is_feature(o)]
    for feat in reversed(features[:features.index(base) + 1]):
        if not _has_surface(feat.Shape, surface):
            continue
        before = feat.BaseFeature
        if before is None or not _has_surface(before.Shape, surface):
            return feat
    return None


class _Size:
    """The radius (mm) that controls a face, as a getter/setter pair."""

    def __init__(self, obj, path, get, set_):
        expressions = dict(obj.ExpressionEngine)
        if path in expressions:
            raise PressPullError("%s %s is driven by the expression '%s'; change that "
                                 "instead" % (obj.Label, path.lstrip("."), expressions[path]))
        self.get, self.set = get, set_


def _fillet_size(feat):
    return _Size(feat, "Radius", lambda: feat.Radius.Value,
                 lambda v: setattr(feat, "Radius", v))


def _hole_size(feat, r):
    if abs(feat.Diameter.Value / 2 - r) < _TOL:
        if feat.ThreadType != "None":
            raise PressPullError("%s's diameter comes from its thread size (%s %s)"
                                 % (feat.Label, feat.ThreadType, feat.ThreadSize))
        return _Size(feat, "Diameter", lambda: feat.Diameter.Value / 2,
                     lambda v: setattr(feat, "Diameter", 2 * v))
    if feat.HoleCutType != "None" and abs(feat.HoleCutDiameter.Value / 2 - r) < _TOL:
        def set_cut(v):
            feat.HoleCutCustomValues = True
            feat.HoleCutDiameter = 2 * v
        return _Size(feat, "HoleCutDiameter", lambda: feat.HoleCutDiameter.Value / 2,
                     set_cut)
    return None


def _sketch_size(feat, surface):
    """The circle in a Pad/Pocket profile sketch that made a cylinder."""
    profile = getattr(feat, "Profile", None)
    sketch = profile[0] if isinstance(profile, tuple) else profile
    if sketch is None or sketch.TypeId != "Sketcher::SketchObject":
        return None
    r = _radius(surface)
    placement = sketch.getGlobalPlacement()
    candidates = []
    for i, geo in enumerate(sketch.Geometry):
        if type(geo).__name__ not in ("Circle", "ArcOfCircle") or sketch.getConstruction(i):
            continue
        if abs(geo.Radius - r) > _TOL:
            continue
        offset = placement.multVec(geo.Center) - surface.Center
        on_axis = (offset - surface.Axis * offset.dot(surface.Axis)).Length < _TOL
        candidates.append((not on_axis, i))
    if not candidates:
        return None
    index = min(candidates)[1]

    def get():
        return sketch.Geometry[index].Radius

    for c_index, c in enumerate(sketch.Constraints):
        if c.Type in ("Radius", "Diameter") and c.First == index:
            path = ".Constraints.%s" % c.Name if c.Name else ".Constraints[%d]" % c_index
            factor = 2 if c.Type == "Diameter" else 1

            def set_datum(v):
                sketch.setDatum(c_index, App.Units.Quantity(factor * v, App.Units.Unit("mm")))
            return _Size(sketch, path, get, set_datum)

    def set_geometry(v):
        geometry = sketch.Geometry
        geometry[index].Radius = v
        sketch.Geometry = geometry
    return _Size(sketch, "Geometry", get, set_geometry)


class RadiusPull:
    """Press/Pull on a cylindrical face: resizes the feature that made it.

    Same interface as PressPull (base, body, feature, distance, set_distance).
    ``feature`` is the PartDesign feature that changed, or None while unchanged.
    """

    def __init__(self, obj, face_name):
        self.body, self.base, face = resolve_face(obj, face_name)
        surface = face.Surface
        self.face_name = face_name
        origin = _origin_feature(self.body, self.base, surface)
        if origin is None:
            raise PressPullError("can't tell which feature made %s" % face_name)
        size, fillet = None, False
        if origin.TypeId == "PartDesign::Fillet":
            if abs(origin.Radius.Value - _radius(surface)) < _TOL:
                size, fillet = _fillet_size(origin), True
        elif origin.TypeId == "PartDesign::Hole":
            size = _hole_size(origin, _radius(surface))
        elif type(surface).__name__ == "Cylinder":
            size = _sketch_size(origin, surface)
        if size is None:
            raise PressPullError("can't resize %s: it comes from %s (%s)"
                                 % (face_name, origin.Label, origin.TypeId.split("::")[-1]))
        self.origin, self.size = origin, size
        self.original = size.get()
        # +distance adds material: a cylinder grows if it bulges out and shrinks if
        # it's a hole. A fillet radius works the other way round: a bigger outside
        # fillet removes more of the corner.
        self.sign = (1 if _is_convex(face) else -1) * (-1 if fillet else 1)
        self.feature = None
        self.distance = 0.0

    @property
    def radius(self):
        return self.size.get()

    def set_distance(self, distance):
        self.set_radius(self.original + self.sign * float(distance))

    def set_radius(self, radius):
        radius = float(radius)
        if radius <= _TOL:
            raise PressPullError("that would make the radius %.3g mm" % radius)
        self.size.set(radius)
        self.feature = self.origin if abs(radius - self.original) > 1e-9 else None
        self.distance = self.sign * (radius - self.original)
