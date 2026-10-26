"""RPC handlers for construction geometry (Fusion: Construct): PartDesign datum planes,
axes and points, attached to the model so they follow it.

References are written like everywhere else: 'XY'/'XZ'/'YZ' and 'X'/'Y'/'Z' (the
body's origin), 'Pad:Face6', 'Pad:Edge3', 'Pad:Vertex2', or a datum's name. Axes and
points pick their attachment mode the way FreeCAD's attachment dialog does.
"""

import FreeCAD as App

from .handlers import (HandlerError, _feature_result, _mutating, _reference,
                       _resolve_body, _vec_out)

V = App.Vector


def _refs(doc, body, references):
    if isinstance(references, str):
        references = [references]
    if not references:
        raise HandlerError("pass at least one reference")
    out = []
    for ref in references:
        obj, subs = _reference(doc, body, ref)
        out.append((obj, subs[0]))
    return out


def _best_mode(kind, refs):
    import Part

    engine = Part.AttachEngine("Attacher::AttachEngine" + kind)
    engine.References = refs
    mode = engine.suggestModes()["bestFitMode"]
    if not mode or mode == "Deactivated":
        raise HandlerError("can't place a %s on %s" % (
            kind.lower(), ", ".join("%s%s" % (o.Name, ":" + s if s else "") for o, s in refs)))
    return mode


def _datum(doc, body, type_id, name, refs, mode, label):
    datum = body.newObject(type_id, name)
    if label:
        datum.Label = label
    datum.AttachmentSupport = refs
    datum.MapMode = mode
    return datum


def _check(doc, datum, body):
    doc.recompute()
    if "Invalid" in datum.State or "Error" in datum.State:
        raise HandlerError("%s can't be attached there: %s"
                           % (datum.Label, datum.getStatusString()))
    out = _feature_result(datum, body)
    out["shape"] = None
    out["placement"] = {"base": _vec_out(datum.Placement.Base),
                        "axis": _vec_out(datum.Placement.Rotation.multVec(V(0, 0, 1)))}
    out["mode"] = datum.MapMode
    return out


@_mutating("Datum plane")
def datum_plane(doc, on="XY", offset=0.0, angle=0.0, about=None, body=None, label=None):
    """``on``: a plane or planar face, or three vertices/points for a plane through
    them. ``offset`` moves it along its normal; ``angle`` (degrees) tilts it about
    ``about`` (an edge or axis lying in it; default the plane's own X direction)."""
    body_obj = _resolve_body(doc, body)
    refs = _refs(doc, body_obj, on)
    if len(refs) == 3:
        mode = "ThreePointsPlane"
    elif len(refs) == 1:
        mode = "FlatFace"
    else:
        raise HandlerError("on= takes one plane or face, or three points")
    datum = _datum(doc, body_obj, "PartDesign::Plane", "DatumPlane", refs, mode, label)
    datum.recompute()
    if "Invalid" in datum.State:
        raise HandlerError("%s isn't planar" % on)
    tilt = App.Placement()
    if angle:
        frame = datum.Placement  # where the attachment alone puts it
        if about:
            obj, subs = _reference(doc, body_obj, about)
            shape = obj.Shape.getElement(subs[0]) if subs[0] else obj.Shape
            edge = shape.Edges[0] if shape.Edges else None
            if edge is None or not hasattr(edge.Curve, "Direction"):
                raise HandlerError("about= must be a straight edge or an axis")
            point = frame.inverse().multVec(edge.Vertexes[0].Point)
            direction = frame.Rotation.inverted().multVec(edge.Curve.Direction)
            if abs(direction.z) > 1e-6 or abs(point.z) > 1e-6:
                raise HandlerError("about= must lie in the plane")
        else:
            point, direction = V(), V(1, 0, 0)
        rotation = App.Rotation(direction, float(angle))
        # Turn about the line through ``point``: there, rotate, and back.
        tilt = App.Placement(point, App.Rotation()) * App.Placement(V(), rotation) \
            * App.Placement(-point, App.Rotation())
    datum.AttachmentOffset = tilt * App.Placement(V(0, 0, float(offset)), App.Rotation())
    return _check(doc, datum, body_obj)


@_mutating("Datum axis")
def datum_axis(doc, through, mode=None, body=None, label=None):
    """``through``: a straight edge, two points, two planes (their intersection), or a
    circular edge / cylindrical face (its axis)."""
    body_obj = _resolve_body(doc, body)
    refs = _refs(doc, body_obj, through)
    if mode is None:
        obj, sub = refs[0]
        element = obj.Shape.getElement(sub) if len(refs) == 1 and sub else None
        if element is not None and element.ShapeType == "Edge" \
                and element.Curve.TypeId == "Part::GeomCircle":
            mode = "AxisOfCurvature"
        elif element is not None and element.ShapeType == "Face" \
                and element.Surface.TypeId == "Part::GeomCylinder":
            # No attacher mode takes a cylinder's axis (the inertia axes miss on short,
            # wide faces), so use one of its circular rims.
            rim = next((e for e in element.Edges if e.Curve.TypeId == "Part::GeomCircle"),
                       None)
            if rim is None:
                raise HandlerError("%s has no circular edge to take the axis from" % sub)
            index = next(i for i, e in enumerate(obj.Shape.Edges, 1) if e.isSame(rim))
            refs = [(obj, "Edge%d" % index)]
            mode = "AxisOfCurvature"
        else:
            mode = _best_mode("Line", refs)
    datum = _datum(doc, body_obj, "PartDesign::Line", "DatumLine", refs, mode, label)
    return _check(doc, datum, body_obj)


@_mutating("Datum point")
def datum_point(doc, at, offset=None, mode=None, body=None, label=None):
    """``at``: a vertex, or the centre of an edge, face or circle; ``offset`` [x, y, z]
    moves it from there."""
    body_obj = _resolve_body(doc, body)
    refs = _refs(doc, body_obj, at)
    if mode is None:
        obj, sub = refs[0]
        element = obj.Shape.getElement(sub) if len(refs) == 1 and sub else None
        if element is not None and element.ShapeType == "Vertex":
            mode = "Vertex"
        elif element is not None and element.ShapeType == "Edge" \
                and element.Curve.TypeId == "Part::GeomCircle":
            mode = "CenterOfCurvature"
        else:
            mode = _best_mode("Point", refs)
    datum = _datum(doc, body_obj, "PartDesign::Point", "DatumPoint", refs, mode, label)
    if offset:
        datum.AttachmentOffset = App.Placement(V(*[float(c) for c in offset]),
                                               App.Rotation())
    out = _check(doc, datum, body_obj)
    out["point"] = out.pop("placement")["base"]
    return out


HANDLERS = {fn.__name__: fn for fn in [datum_plane, datum_axis, datum_point]}
