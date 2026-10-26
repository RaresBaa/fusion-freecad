"""Operations exposed over RPC. Every function here runs on FreeCAD's main thread.

Conventions:
- Lengths are millimetres, angles are degrees.
- ``document`` is optional everywhere and defaults to the active document.
- Objects can be referred to by internal name ("Pad001") or by label ("Base plate").
- Operations that change a document run inside one undo transaction, so a single
  Ctrl+Z in FreeCAD reverts a whole tool call.
"""

import base64
import contextlib
import functools
import io
import json
import os
import tempfile

import FreeCAD as App

from . import bodies, parameters as params
from .rpc import PROTOCOL_VERSION, HandlerError

if App.GuiUp:
    import FreeCADGui as Gui
else:
    Gui = None

V = App.Vector


# ---------------------------------------------------------------------------
# helpers

def _doc(name=None):
    if name:
        doc = App.listDocuments().get(name)
        if doc is None:
            for d in App.listDocuments().values():
                if d.Label == name:
                    return d
            raise HandlerError("no document named %r (open: %s)"
                               % (name, ", ".join(App.listDocuments()) or "none"))
        return doc
    if App.ActiveDocument is None:
        raise HandlerError("no document is open; call new_document first")
    return App.ActiveDocument


def _obj(doc, name):
    obj = doc.getObject(name)
    if obj is None:
        matches = doc.getObjectsByLabel(name)
        if not matches:
            raise HandlerError("no object %r in document %r" % (name, doc.Name))
        obj = matches[0]
    return obj


def _is_invalid(obj):
    return "Invalid" in obj.State or "Error" in obj.State


def _body_of(obj):
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def _active_body(doc):
    if Gui and Gui.ActiveDocument and Gui.ActiveDocument.Document is doc:
        view = Gui.ActiveDocument.ActiveView
        get_active = getattr(view, "getActiveObject", None)
        if get_active:
            body = get_active("pdbody")
            if body is not None:
                return body
    return None


def _resolve_body(doc, body):
    if body:
        obj = _obj(doc, body)
        if obj.TypeId != "PartDesign::Body":
            raise HandlerError("%r is a %s, not a PartDesign body" % (body, obj.TypeId))
        return obj
    active = _active_body(doc)
    if active is not None:
        return active
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    if len(bodies) == 1:
        return bodies[0]
    if not bodies:
        return _new_body(doc, "Body")
    raise HandlerError("document has several bodies (%s); pass body="
                       % ", ".join(b.Name for b in bodies))


def _new_body(doc, label):
    body = doc.addObject("PartDesign::Body", "Body")
    body.Label = label
    _set_active_body(doc, body)
    return body


def _set_active_body(doc, body):
    if Gui and Gui.ActiveDocument and Gui.ActiveDocument.Document is doc:
        view = Gui.ActiveDocument.ActiveView
        if hasattr(view, "setActiveObject"):
            view.setActiveObject("pdbody", body)


def _hide(obj):
    if Gui and obj is not None:
        obj.Visibility = False


def _vec(value, what):
    try:
        if len(value) == 2:
            return V(float(value[0]), float(value[1]), 0)
        if len(value) == 3:
            return V(float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        pass
    raise HandlerError("%s must be [x, y] or [x, y, z], got %r" % (what, value))


def _round(x):
    return round(x, 6)


def _vec_out(v):
    return [_round(v.x), _round(v.y), _round(v.z)]


def _shape_summary(shape):
    if shape is None or shape.isNull():
        return None
    bb = shape.BoundBox
    summary = {
        "solids": len(shape.Solids),
        "faces": len(shape.Faces),
        "edges": len(shape.Edges),
        "bound_box": {"min": [_round(bb.XMin), _round(bb.YMin), _round(bb.ZMin)],
                      "max": [_round(bb.XMax), _round(bb.YMax), _round(bb.ZMax)]},
    }
    if shape.Solids:
        summary["volume"] = _round(shape.Volume)
        summary["area"] = _round(shape.Area)
    return summary


def _describe(obj, with_shape=True):
    info = {
        "name": obj.Name,
        "label": obj.Label,
        "type": obj.TypeId,
        "valid": not _is_invalid(obj),
    }
    if _is_invalid(obj):
        info["state"] = list(obj.State)
    body = _body_of(obj)
    if body is not None:
        info["body"] = body.Name
    if obj.TypeId == "PartDesign::Body":
        info["tip"] = obj.Tip.Name if obj.Tip else None
        info["features"] = [o.Name for o in obj.Group]
    if Gui:
        info["visible"] = bool(obj.Visibility)
    if with_shape and hasattr(obj, "Shape"):
        summary = _shape_summary(obj.Shape)
        if summary:
            info["shape"] = summary
    return info


def _recompute_report(doc):
    doc.recompute()
    broken = [o for o in doc.Objects if _is_invalid(o)]
    if not broken:
        return {}
    return {"errors": [{"name": o.Name, "label": o.Label, "state": list(o.State)}
                       for o in broken]}


def _open_transaction(doc, label):
    # Headless FreeCAD creates documents with undo disabled, which would make
    # transactions (and abort-on-error) silently do nothing.
    if not doc.UndoMode:
        doc.UndoMode = 1
    doc.openTransaction(label)


def _mutating(label):
    """Run a handler as one undoable transaction and recompute afterwards.

    The wrapped function receives the resolved document as its first argument.
    """
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(document=None, **kwargs):
            doc = _doc(document)
            _open_transaction(doc, label)
            try:
                result = fn(doc, **kwargs)
                result.update(_recompute_report(doc))
            except Exception:
                doc.abortTransaction()
                raise
            doc.commitTransaction()
            if Gui:
                Gui.updateGui()
            return result
        return wrapper
    return decorate


# ---------------------------------------------------------------------------
# session and documents

def ping():
    doc = App.ActiveDocument
    return {
        "freecad_version": ".".join(App.Version()[:3]),
        "gui": bool(App.GuiUp),
        "protocol": PROTOCOL_VERSION,
        "active_document": doc.Name if doc else None,
    }


def list_documents():
    active = App.ActiveDocument
    return {"documents": [
        {"name": d.Name, "label": d.Label, "file": d.FileName or None,
         "active": d is active, "objects": len(d.Objects)}
        for d in App.listDocuments().values()]}


def new_document(name="Unnamed"):
    doc = App.newDocument(name)
    if Gui:
        Gui.activeDocument()  # make sure the view exists before later calls
    return {"document": doc.Name, "label": doc.Label}


def open_document(path):
    if not os.path.isfile(path):
        raise HandlerError("file not found: %s" % path)
    doc = App.openDocument(path)
    return {"document": doc.Name, "label": doc.Label}


def save_document(document=None, path=None):
    doc = _doc(document)
    if path:
        doc.saveAs(path)
    elif doc.FileName:
        doc.save()
    else:
        raise HandlerError("document has never been saved; pass path= (a .FCStd file)")
    return {"document": doc.Name, "file": doc.FileName}


def close_document(document):
    doc = _doc(document)
    App.closeDocument(doc.Name)
    return {"closed": document}


def activate_document(document):
    doc = _doc(document)
    App.setActiveDocument(doc.Name)
    if Gui:
        Gui.setActiveDocument(doc.Name)
    return {"document": doc.Name}


# ---------------------------------------------------------------------------
# inspection

def list_objects(document=None):
    doc = _doc(document)
    return {"document": doc.Name,
            "objects": [_describe(o, with_shape=False) for o in doc.Objects]}


_SKIPPED_PROPERTIES = {"Shape", "Proxy", "ExpressionEngine", "Visibility", "Label2",
                       "_Body", "Geometry", "Constraints", "ExternalGeo"}


def get_object(name, document=None):
    doc = _doc(document)
    obj = _obj(doc, name)
    info = _describe(obj)
    props = {}
    for prop in obj.PropertiesList:
        if prop in _SKIPPED_PROPERTIES:
            continue
        try:
            value = getattr(obj, prop)
        except Exception:
            continue
        if hasattr(value, "Name") and hasattr(value, "TypeId"):
            value = value.Name
        text = value if isinstance(value, (bool, int, float)) else str(value)
        if isinstance(text, str) and len(text) > 200:
            text = text[:200] + "..."
        props[prop] = text
    info["properties"] = props
    if obj.TypeId == "Sketcher::SketchObject":
        info["sketch"] = _sketch_info(obj)
    return info


def _sketch_info(sketch):
    geometry = []
    for i, geo in enumerate(sketch.Geometry):
        item = {"index": i, "type": type(geo).__name__}
        if hasattr(geo, "StartPoint") and hasattr(geo, "EndPoint"):
            item["start"] = _vec_out(geo.StartPoint)[:2]
            item["end"] = _vec_out(geo.EndPoint)[:2]
        if hasattr(geo, "Center"):
            item["center"] = _vec_out(geo.Center)[:2]
        if hasattr(geo, "Radius"):
            item["radius"] = _round(geo.Radius)
        if sketch.getConstruction(i):
            item["construction"] = True
        geometry.append(item)
    constraints = [{"index": i, "type": c.Type, "name": c.Name or None,
                    "value": _round(c.Value) if c.Value else None}
                   for i, c in enumerate(sketch.Constraints)]
    info = {"geometry": geometry, "constraints": constraints,
            "fully_constrained": bool(getattr(sketch, "FullyConstrained", False))}
    # Projected geometry: GeoId -1 and -2 are the sketch axes, then one per projection.
    external = []
    for i, geo in enumerate(sketch.ExternalGeo[2:], 2):
        item = {"index": -(i + 1), "type": type(geo).__name__}
        if hasattr(geo, "StartPoint") and hasattr(geo, "EndPoint"):
            item["start"] = _vec_out(geo.StartPoint)[:2]
            item["end"] = _vec_out(geo.EndPoint)[:2]
        if hasattr(geo, "Center"):
            item["center"] = _vec_out(geo.Center)[:2]
        external.append(item)
    if external:
        info["external"] = external
    return info


def get_topology(name, document=None, max_items=300):
    """Faces and edges of an object's shape, so callers can pick e.g. edges to fillet."""
    doc = _doc(document)
    obj = _obj(doc, name)
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        raise HandlerError("%s has no shape" % obj.Name)

    faces = []
    for i, face in enumerate(shape.Faces[:max_items], 1):
        item = {"name": "Face%d" % i, "surface": type(face.Surface).__name__,
                "area": _round(face.Area), "center": _vec_out(face.CenterOfMass)}
        if item["surface"] == "Plane":
            u0, u1, v0, v1 = face.ParameterRange
            item["normal"] = _vec_out(face.normalAt((u0 + u1) / 2, (v0 + v1) / 2))
        elif hasattr(face.Surface, "Radius"):
            item["radius"] = _round(face.Surface.Radius)
        faces.append(item)

    edges = []
    for i, edge in enumerate(shape.Edges[:max_items], 1):
        item = {"name": "Edge%d" % i, "curve": type(edge.Curve).__name__,
                "length": _round(edge.Length), "center": _vec_out(edge.CenterOfMass)}
        if item["curve"] in ("Line", "LineSegment"):
            item["start"] = _vec_out(edge.Vertexes[0].Point)
            item["end"] = _vec_out(edge.Vertexes[-1].Point)
        elif hasattr(edge.Curve, "Radius"):
            item["radius"] = _round(edge.Curve.Radius)
        edges.append(item)

    result = {"name": obj.Name, "faces": faces, "edges": edges}
    if len(shape.Faces) > max_items or len(shape.Edges) > max_items:
        result["truncated"] = True
        result["total_faces"] = len(shape.Faces)
        result["total_edges"] = len(shape.Edges)
    return result


def _element(doc, ref):
    """'Pad' (whole shape) or 'Pad:Face6' / 'Pad:Edge3' / 'Pad:Vertex2'."""
    obj_name, _, sub = str(ref).partition(":")
    obj = _obj(doc, obj_name)
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        raise HandlerError("%s has no shape" % obj.Name)
    if not sub:
        return shape
    try:
        return shape.getElement(sub)
    except Exception:
        raise HandlerError("%s has no %s (see get_topology)" % (obj.Name, sub))


def _direction(shape):
    """Normal of a planar face or direction of a straight edge, else None."""
    import Part

    if isinstance(shape, Part.Face) and type(shape.Surface).__name__ == "Plane":
        u0, u1, v0, v1 = shape.ParameterRange
        return shape.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    if isinstance(shape, Part.Edge) and type(shape.Curve).__name__ in ("Line", "LineSegment"):
        return shape.Vertexes[-1].Point - shape.Vertexes[0].Point
    return None


def _measure_one(shape):
    import Part

    info = {"kind": type(shape).__name__.lower()}
    if isinstance(shape, Part.Vertex):
        info["point"] = _vec_out(shape.Point)
    elif isinstance(shape, Part.Edge):
        info["length"] = _round(shape.Length)
        if hasattr(shape.Curve, "Radius"):
            info["radius"] = _round(shape.Curve.Radius)
            info["diameter"] = _round(2 * shape.Curve.Radius)
            info["center"] = _vec_out(shape.Curve.Center)
    elif isinstance(shape, Part.Face):
        info["area"] = _round(shape.Area)
        if hasattr(shape.Surface, "Radius"):
            info["radius"] = _round(shape.Surface.Radius)
            info["diameter"] = _round(2 * shape.Surface.Radius)
    else:
        summary = _shape_summary(shape)
        if summary:
            info.update(summary)
    return info


def measure(a, b=None, document=None):
    """Size of one element, or the distance and angle between two."""
    doc = _doc(document)
    sa = _element(doc, a)
    if b is None:
        return _measure_one(sa)
    sb = _element(doc, b)
    dist, pairs, _ = sa.distToShape(sb)
    result = {"distance": _round(dist)}
    if pairs:
        p, q = pairs[0]
        result["closest_points"] = [_vec_out(p), _vec_out(q)]
        d = q - p
        result["delta"] = _vec_out(d)
    da, db = _direction(sa), _direction(sb)
    if da is not None and db is not None and da.Length > 0 and db.Length > 0:
        import math
        angle = math.degrees(da.getAngle(db))
        result["angle"] = _round(angle)
        # Parallel planar faces: the gap between their planes, not just the closest points.
        if abs(math.sin(math.radians(angle))) < 1e-9 and hasattr(sa, "Surface") \
                and hasattr(sb, "Surface"):
            n = V(da).normalize()
            result["plane_distance"] = _round(abs((sb.CenterOfMass - sa.CenterOfMass).dot(n)))
    return result


# ---------------------------------------------------------------------------
# modelling

@_mutating("Create body")
def create_body(doc, label="Body"):
    body = _new_body(doc, label)
    return {"body": body.Name, "label": body.Label}


_PLANE_ROLES = {"XY": "XY_Plane", "XZ": "XZ_Plane", "YZ": "YZ_Plane"}


@_mutating("Create sketch")
def create_sketch(doc, body=None, plane="XY", face=None, offset=0.0,
                  geometry=None, constraints=None, label=None):
    body_obj = _resolve_body(doc, body)
    sketch = body_obj.newObject("Sketcher::SketchObject", "Sketch")
    if label:
        sketch.Label = label

    if face:
        obj_name, _, sub = face.partition(":")
        if not sub:
            raise HandlerError("face must look like 'Pad:Face6', got %r" % face)
        sketch.AttachmentSupport = [(_obj(doc, obj_name), sub)]
    else:
        role = _PLANE_ROLES.get(str(plane).upper())
        if role is not None:
            support = next(f for f in body_obj.Origin.OriginFeatures if f.Role == role)
        else:
            support = doc.getObject(plane) or (doc.getObjectsByLabel(plane) or [None])[0]
            if support is None or not (support.isDerivedFrom("PartDesign::Plane")
                                       or support.isDerivedFrom("App::Plane")):
                raise HandlerError("plane must be XY, XZ, YZ or a datum plane, got %r"
                                   % plane)
        sketch.AttachmentSupport = [(support, "")]
    sketch.MapMode = "FlatFace"
    if offset:
        sketch.AttachmentOffset = App.Placement(V(0, 0, float(offset)), App.Rotation())

    indices = [_add_geometry(sketch, item) for item in (geometry or [])]
    for c in constraints or []:
        _add_constraint(sketch, c)

    status = sketch.solve()
    return {"sketch": sketch.Name, "body": body_obj.Name, "geometry_indices": indices,
            "solver_ok": status == 0,
            "fully_constrained": bool(getattr(sketch, "FullyConstrained", False))}


@_mutating("Add sketch geometry")
def add_sketch_geometry(doc, sketch, geometry=None, constraints=None):
    sk = _obj(doc, sketch)
    if sk.TypeId != "Sketcher::SketchObject":
        raise HandlerError("%r is not a sketch" % sketch)
    indices = [_add_geometry(sk, item) for item in (geometry or [])]
    for c in constraints or []:
        _add_constraint(sk, c)
    status = sk.solve()
    return {"sketch": sk.Name, "geometry_indices": indices, "solver_ok": status == 0,
            "fully_constrained": bool(getattr(sk, "FullyConstrained", False))}


def _add_geometry(sketch, item):
    """Add one geometry item; returns the list of sketch geometry indices it created."""
    import Part
    import Sketcher

    if not isinstance(item, dict) or "type" not in item:
        raise HandlerError("geometry items must be objects with a 'type', got %r" % (item,))
    kind = item["type"]
    construction = bool(item.get("construction", False))
    dimensioned = bool(item.get("dimensioned", True))

    def add(geo):
        return sketch.addGeometry(geo, construction)

    def con(*args):
        sketch.addConstraint(Sketcher.Constraint(*args))

    if kind == "line":
        return [add(Part.LineSegment(_vec(item["start"], "start"), _vec(item["end"], "end")))]

    if kind == "circle":
        radius = float(item["radius"])
        i = add(Part.Circle(_vec(item["center"], "center"), V(0, 0, 1), radius))
        if dimensioned:
            con("Diameter", i, 2 * radius)
        return [i]

    if kind == "arc":
        import math
        circle = Part.Circle(_vec(item["center"], "center"), V(0, 0, 1), float(item["radius"]))
        a0 = math.radians(float(item["start_angle"]))
        a1 = math.radians(float(item["end_angle"]))
        return [add(Part.ArcOfCircle(circle, a0, a1))]

    if kind == "rectangle":
        width, height = float(item["width"]), float(item["height"])
        if width <= 0 or height <= 0:
            raise HandlerError("rectangle width and height must be positive")
        if "center" in item:
            c = _vec(item["center"], "center")
            x, y = c.x - width / 2, c.y - height / 2
        else:
            c = _vec(item.get("corner", [0, 0]), "corner")
            x, y = c.x, c.y
        pts = [V(x, y, 0), V(x + width, y, 0), V(x + width, y + height, 0), V(x, y + height, 0)]
        lines = [add(Part.LineSegment(pts[k], pts[(k + 1) % 4])) for k in range(4)]
        for k in range(4):
            con("Coincident", lines[k], 2, lines[(k + 1) % 4], 1)
        con("Horizontal", lines[0])
        con("Horizontal", lines[2])
        con("Vertical", lines[1])
        con("Vertical", lines[3])
        if dimensioned:
            con("DistanceX", lines[0], 1, lines[0], 2, width)
            con("DistanceY", lines[1], 1, lines[1], 2, height)
        return lines

    if kind == "polygon":
        points = [_vec(p, "point") for p in item["points"]]
        if len(points) < 3:
            raise HandlerError("polygon needs at least 3 points")
        n = len(points)
        lines = [add(Part.LineSegment(points[k], points[(k + 1) % n])) for k in range(n)]
        for k in range(n):
            con("Coincident", lines[k], 2, lines[(k + 1) % n], 1)
        return lines

    raise HandlerError("unknown geometry type %r (use line, circle, arc, rectangle, polygon)"
                       % kind)


def _add_constraint(sketch, item):
    import Sketcher

    if not isinstance(item, dict) or "type" not in item:
        raise HandlerError("constraints must be objects like "
                           "{'type': 'Distance', 'args': [0, 1, 2, 10.0]}, got %r" % (item,))
    args = list(item.get("args", []))
    try:
        sketch.addConstraint(Sketcher.Constraint(item["type"], *args))
    except Exception as e:
        raise HandlerError("could not add constraint %r: %s" % (item, e))


def _sketch(doc, name):
    sk = _obj(doc, name)
    if sk.TypeId != "Sketcher::SketchObject":
        raise HandlerError("%r is not a sketch" % name)
    return sk


def _constraint_index(sk, constraint):
    if isinstance(constraint, int):
        if not 0 <= constraint < len(sk.Constraints):
            raise HandlerError("%s has no constraint %d" % (sk.Name, constraint))
        return constraint
    for i, c in enumerate(sk.Constraints):
        if c.Name == constraint:
            return i
    raise HandlerError("%s has no constraint named %r" % (sk.Name, constraint))


_DIMENSIONS = {"Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle"}


def _sketch_result(sk, status):
    return {"sketch": sk.Name, "solver_ok": status == 0,
            "fully_constrained": bool(getattr(sk, "FullyConstrained", False)),
            "sketch_info": _sketch_info(sk)}


@_mutating("Set dimension")
def set_dimension(doc, sketch, constraint, value=None, expression=None, name=None):
    sk = _sketch(doc, sketch)
    i = _constraint_index(sk, constraint)
    c = sk.Constraints[i]
    if name:
        sk.renameConstraint(i, name)
    if value is not None or expression is not None:
        if c.Type not in _DIMENSIONS:
            raise HandlerError("constraint %d is a %s, not a dimension" % (i, c.Type))
        path = ".Constraints.%s" % sk.Constraints[i].Name if sk.Constraints[i].Name \
            else ".Constraints[%d]" % i
        if expression is not None:
            try:
                sk.setExpression(path, expression)
            except Exception as e:
                raise HandlerError("bad expression %r: %s" % (expression, e))
        else:
            sk.setExpression(path, None)
            unit = "deg" if c.Type == "Angle" else "mm"
            try:
                sk.setDatum(i, App.Units.Quantity("%s %s" % (float(value), unit)))
            except Exception as e:
                raise HandlerError("could not set constraint %d to %s: %s" % (i, value, e))
    return _sketch_result(sk, sk.solve())


@_mutating("Delete sketch geometry")
def delete_sketch_geometry(doc, sketch, geometry=None, constraints=None):
    sk = _sketch(doc, sketch)
    if not geometry and not constraints:
        raise HandlerError("pass geometry=[indices] and/or constraints=[indices or names]")
    # Constraints first: deleting geometry renumbers them.
    for i in sorted({_constraint_index(sk, c) for c in constraints or []}, reverse=True):
        sk.delConstraint(i)
    geometry = sorted(set(int(g) for g in geometry or []))
    if geometry:
        bad = [g for g in geometry if not 0 <= g < len(sk.Geometry)]
        if bad:
            raise HandlerError("%s has no geometry %s" % (sk.Name, bad))
        sk.delGeometries(geometry)
    return _sketch_result(sk, sk.solve())


_POINTS = {"edge": 0, "start": 1, "end": 2, "center": 3}


@_mutating("Move sketch geometry")
def move_sketch_geometry(doc, sketch, index, to, point="edge", relative=False):
    sk = _sketch(doc, sketch)
    if not 0 <= int(index) < len(sk.Geometry):
        raise HandlerError("%s has no geometry %d" % (sk.Name, index))
    if point not in _POINTS:
        raise HandlerError("point must be edge, start, end or center")
    status = sk.moveGeometry(int(index), _POINTS[point], _vec(to, "to"), bool(relative))
    if status not in (0, None):
        raise HandlerError("the sketch solver could not move it there (constraints?)")
    return _sketch_result(sk, sk.solve())


# Parameters (Fusion: Change Parameters) live in parameters.py, shared with the dialog.

@_mutating("Set parameters")
def set_parameters(doc, parameters):
    if not isinstance(parameters, dict) or not parameters:
        raise HandlerError("pass parameters={'width': 40, 'angle': '30 deg', "
                           "'half': '=width / 2'}")
    vs = params.varset(doc, create=True)
    params.set_many(vs, parameters)
    return {"parameters": params.listing(vs)}


@_mutating("Delete parameter")
def delete_parameter(doc, name):
    vs = params.varset(doc)
    if vs is None or name not in params.names(vs):
        raise HandlerError("no parameter %r" % name)
    vs.removeProperty(name)
    return {"parameters": params.listing(vs)}


@_mutating("Rename parameter")
def rename_parameter(doc, name, new_name):
    vs = params.varset(doc)
    if vs is None:
        raise HandlerError("no parameter %r" % name)
    params.rename(vs, name, new_name)
    return {"parameters": params.listing(vs)}


def get_parameters(document=None):
    doc = _doc(document)
    vs = params.varset(doc)
    expressions = [{"object": o.Name, "property": prop.lstrip("."), "expression": expr}
                   for o in doc.Objects for prop, expr in o.ExpressionEngine]
    return {"parameters": params.listing(vs) if vs else [], "expressions": expressions}


@_mutating("Set expression")
def set_expression(doc, name, property, expression=None):
    obj = _obj(doc, name)
    root = property.split(".")[0].split("[")[0]
    if root not in obj.PropertiesList:
        raise HandlerError("%s has no property %r" % (obj.Name, root))
    if obj.TypeId == "Sketcher::SketchObject" and root == "Constraints" \
            and not property.startswith("."):
        property = "." + property
    try:
        obj.setExpression(property, expression)
    except Exception as e:
        raise HandlerError("bad expression %r: %s" % (expression, e))
    result = {"name": obj.Name, "property": property.lstrip("."), "expression": expression}
    if "." not in property.lstrip(".") and "[" not in property:
        doc.recompute()
        value = getattr(obj, root)
        value = getattr(value, "Value", value)
        result["value"] = _round(value) if isinstance(value, (int, float)) else str(value)
    return result


def _feature_from_sketch(doc, sketch, type_id, label):
    sk = _obj(doc, sketch)
    body = _body_of(sk)
    if body is None:
        raise HandlerError("%s is not inside a PartDesign body" % sk.Name)
    feature = body.newObject(type_id, type_id.split("::")[1])
    if label:
        feature.Label = label
    feature.Profile = sk
    _hide(sk)
    return body, sk, feature


def _feature_result(feature, body):
    return {"feature": feature.Name, "body": body.Name,
            "shape": _shape_summary(feature.Shape) if not _is_invalid(feature) else None}


def _finish(doc, feature, body):
    doc.recompute()
    return _feature_result(feature, body)


def _set_midplane(feat, midplane):
    """Extrude symmetrically. FreeCAD 1.1 replaced Midplane by SideType and warns (with
    a notification popup) whenever Midplane is set, even to False."""
    if not midplane:
        return
    if "SideType" in feat.PropertiesList:
        feat.SideType = "Symmetric"
    else:
        feat.Midplane = True


def _extrude_options(feat, length2, taper):
    """A second side ``length2`` mm the other way (Fusion: Two Sides), and a taper in
    degrees (on both sides)."""
    if length2 is not None:
        if feat.SideType == "Symmetric":
            raise HandlerError("pass either midplane or length2, not both")
        feat.SideType = "Two sides"
        feat.Length2 = float(length2)
    if taper:
        feat.TaperAngle = float(taper)
        if length2 is not None:
            feat.TaperAngle2 = float(taper)


@_mutating("Pad")
def pad(doc, sketch, length=10.0, reversed=False, midplane=False,
        up_to_face=None, length2=None, taper=0.0, label=None):
    body, _, feat = _feature_from_sketch(doc, sketch, "PartDesign::Pad", label)
    if up_to_face:
        obj_name, _, sub = up_to_face.partition(":")
        feat.Type = "UpToFace"
        feat.UpToFace = (_obj(doc, obj_name), [sub])
    else:
        feat.Type = "Length"
        feat.Length = float(length)
    feat.Reversed = bool(reversed)
    _set_midplane(feat, midplane)
    _extrude_options(feat, length2, taper)
    return _finish(doc, feat, body)


@_mutating("Pocket")
def pocket(doc, sketch, length=10.0, through_all=False, reversed=False,
           midplane=False, length2=None, taper=0.0, label=None):
    body, _, feat = _feature_from_sketch(doc, sketch, "PartDesign::Pocket", label)
    if through_all:
        feat.Type = "ThroughAll"
    else:
        feat.Type = "Length"
        feat.Length = float(length)
    feat.Reversed = bool(reversed)
    _set_midplane(feat, midplane)
    _extrude_options(feat, length2, taper)
    return _finish(doc, feat, body)


_SKETCH_AXES = {"V": "V_Axis", "H": "H_Axis", "V_AXIS": "V_Axis", "H_AXIS": "H_Axis"}


@_mutating("Revolve")
def revolve(doc, sketch, angle=360.0, axis="V", groove=False, label=None):
    type_id = "PartDesign::Groove" if groove else "PartDesign::Revolution"
    body, sk, feat = _feature_from_sketch(doc, sketch, type_id, label)
    key = str(axis).upper()
    if key in _SKETCH_AXES:
        feat.ReferenceAxis = (sk, [_SKETCH_AXES[key]])
    elif key in ("X", "Y", "Z"):
        origin_axis = next(f for f in body.Origin.OriginFeatures if f.Role == key + "_Axis")
        feat.ReferenceAxis = (origin_axis, [""])
    else:
        raise HandlerError("axis must be V, H (sketch axes) or X, Y, Z (body axes)")
    feat.Angle = float(angle)
    return _finish(doc, feat, body)


@_mutating("Loft")
def loft(doc, sketches, cut=False, ruled=False, closed=False, label=None):
    if isinstance(sketches, str) or len(sketches) < 2:
        raise HandlerError("pass at least two sketches=['Sketch', 'Sketch001', ...]")
    type_id = "PartDesign::SubtractiveLoft" if cut else "PartDesign::AdditiveLoft"
    body, _, feat = _feature_from_sketch(doc, sketches[0], type_id, label)
    sections = [_obj(doc, n) for n in sketches[1:]]
    if any(_body_of(s) is not body for s in sections):
        raise HandlerError("all loft sketches must be in body %s" % body.Name)
    feat.Sections = sections
    for s in sections:
        _hide(s)
    feat.Ruled = bool(ruled)
    feat.Closed = bool(closed)
    return _finish(doc, feat, body)


_SWEEP_MODES = {"standard": "Standard", "fixed": "Fixed", "frenet": "Frenet"}
_TRANSITIONS = {"transformed": "Transformed", "right": "Right corner", "round": "Round corner"}


@_mutating("Sweep")
def sweep(doc, sketch, path, path_edges=None, cut=False, mode="standard",
          transition="transformed", label=None):
    obj_name, _, sub = str(path).partition(":")
    spine = _obj(doc, obj_name)
    edges = list(path_edges or []) + ([sub] if sub else [])
    if mode not in _SWEEP_MODES:
        raise HandlerError("mode must be standard, fixed or frenet")
    if transition not in _TRANSITIONS:
        raise HandlerError("transition must be transformed, right or round")
    type_id = "PartDesign::SubtractivePipe" if cut else "PartDesign::AdditivePipe"
    body, _, feat = _feature_from_sketch(doc, sketch, type_id, label)
    feat.Spine = (spine, edges)
    feat.Mode = _SWEEP_MODES[mode]
    feat.Transition = _TRANSITIONS[transition]
    if spine.TypeId == "Sketcher::SketchObject":
        _hide(spine)
    return _finish(doc, feat, body)


def _dress_up(doc, type_id, base, edges, label):
    if base:
        base_obj = _obj(doc, base)
        body = _body_of(base_obj)
    else:
        body = _resolve_body(doc, None)
        base_obj = body.Tip
    if body is None or base_obj is None:
        raise HandlerError("need a PartDesign feature to modify (pass base=)")
    feature = body.newObject(type_id, type_id.split("::")[1])
    if label:
        feature.Label = label
    if edges == "all":
        feature.Base = (base_obj, [])
        feature.UseAllEdges = True
    else:
        if isinstance(edges, str):
            edges = [edges]
        if not edges:
            raise HandlerError("pass edges=['Edge1', ...] or edges='all'")
        feature.Base = (base_obj, list(edges))
    return body, feature


@_mutating("Fillet")
def fillet(doc, edges, radius, base=None, label=None):
    body, feat = _dress_up(doc, "PartDesign::Fillet", base, edges, label)
    feat.Radius = float(radius)
    return _finish(doc, feat, body)


@_mutating("Chamfer")
def chamfer(doc, edges, size, base=None, label=None):
    body, feat = _dress_up(doc, "PartDesign::Chamfer", base, edges, label)
    feat.Size = float(size)
    return _finish(doc, feat, body)


@_mutating("Shell")
def shell(doc, faces, thickness, base=None, outward=False, label=None):
    if isinstance(faces, str):
        faces = [faces]
    if not faces:
        raise HandlerError("pass faces=['Face6', ...]: the faces to remove (open up)")
    body, feat = _dress_up(doc, "PartDesign::Thickness", base, faces, label)
    feat.Value = float(thickness)
    feat.Reversed = not outward  # FreeCAD's default (Reversed) keeps the outside size
    return _finish(doc, feat, body)


_HOLE_CUTS = {"none": "None", "counterbore": "Counterbore", "countersink": "Countersink",
              "counterdrill": "Counterdrill"}


def _thread_size(feat, thread):
    """Find the thread type and size for e.g. 'M6', 'M8x1.0', '1/4' (UNC) or 'UNF 1/4'."""
    text = thread.strip()
    kind, _, size = text.rpartition(" ")
    types = [t for t in feat.getEnumerationsOfProperty("ThreadType") if t != "None"]
    if kind:
        match = [t for t in types if t.lower() == kind.lower()]
        if not match:
            raise HandlerError("unknown thread type %r (use %s)" % (kind, ", ".join(types)))
        types = match
    for t in types:
        feat.ThreadType = t
        sizes = feat.getEnumerationsOfProperty("ThreadSize")
        if size in sizes:
            return t, size
        # 'M6' means the coarse pitch: M6x1.0
        coarse = [s for s in sizes if s.startswith(size + "x")]
        if coarse and t == "ISOMetricProfile":
            return t, coarse[0]
    raise HandlerError("unknown thread size %r; e.g. 'M6', 'M8x1.0' (fine), '1/4' (UNC), "
                       "'UNF 1/4'" % thread)


@_mutating("Hole")
def hole(doc, sketch, diameter=None, depth=10.0, through_all=False, thread=None,
         tapped=False, modeled_thread=False, fit=None, cut=None, cut_diameter=None,
         cut_depth=None, countersink_angle=None, flat_bottom=False, reversed=False,
         label=None):
    sk = _obj(doc, sketch)
    circles = [g for i, g in enumerate(getattr(sk, "Geometry", []))
               if type(g).__name__ == "Circle" and not sk.getConstruction(i)]
    if not circles:
        raise HandlerError("%s has no circles; a hole is drilled at each circle's centre"
                           % sk.Name)
    body, _, feat = _feature_from_sketch(doc, sketch, "PartDesign::Hole", label)
    if thread:
        feat.ThreadType, feat.ThreadSize = _thread_size(feat, thread)
        feat.Threaded = bool(tapped or modeled_thread)
        feat.ModelThread = bool(modeled_thread)
        if fit:
            fits = feat.getEnumerationsOfProperty("ThreadFit")
            if fit not in fits:
                raise HandlerError("fit for %s must be one of %s"
                                   % (feat.ThreadType, ", ".join(fits)))
            feat.ThreadFit = fit
    elif diameter is None:
        feat.Diameter = 2 * circles[0].Radius
    if diameter is not None:
        feat.Diameter = float(diameter)
    if through_all:
        feat.DepthType = "ThroughAll"
    else:
        feat.DepthType = "Dimension"
        feat.Depth = float(depth)
    feat.DrillPoint = "Flat" if flat_bottom else "Angled"
    if cut:
        cut_type = _HOLE_CUTS.get(str(cut).lower())
        if cut_type is None:
            raise HandlerError("cut must be counterbore, countersink or counterdrill")
        feat.HoleCutType = cut_type
        if cut_diameter is not None or cut_depth is not None or countersink_angle is not None:
            feat.HoleCutCustomValues = True
        if cut_diameter is not None:
            feat.HoleCutDiameter = float(cut_diameter)
        if cut_depth is not None:
            feat.HoleCutDepth = float(cut_depth)
        if countersink_angle is not None:
            feat.HoleCutCountersinkAngle = float(countersink_angle)
    feat.Reversed = bool(reversed)
    result = _finish(doc, feat, body)
    result.update({"holes": len(circles), "diameter": _round(feat.Diameter.Value)})
    if thread:
        result["thread"] = "%s %s" % (feat.ThreadType, feat.ThreadSize)
    if feat.HoleCutType != "None":
        result["cut"] = {"type": feat.HoleCutType,
                         "diameter": _round(feat.HoleCutDiameter.Value),
                         "depth": _round(feat.HoleCutDepth.Value)}
    return result


_ORIGIN_ROLES = {"X": "X_Axis", "Y": "Y_Axis", "Z": "Z_Axis",
                 "XY": "XY_Plane", "XZ": "XZ_Plane", "YZ": "YZ_Plane"}


def _reference(doc, body, ref):
    """'X'/'Y'/'Z', 'XY'/'XZ'/'YZ' (body origin), 'Pad:Face3', 'Sketch:H_Axis' or a datum."""
    key = str(ref).upper()
    if key in _ORIGIN_ROLES:
        role = _ORIGIN_ROLES[key]
        return (next(f for f in body.Origin.OriginFeatures if f.Role == role), [""])
    obj_name, _, sub = str(ref).partition(":")
    return (_obj(doc, obj_name), [sub] if sub else [""])


def _transformed(doc, type_id, features, whole_body, label):
    if isinstance(features, str):
        features = [features]
    if features:
        originals = [_obj(doc, n) for n in features]
        body = _body_of(originals[0])
        if body is None or any(_body_of(o) is not body for o in originals):
            raise HandlerError("features must all be in the same PartDesign body")
    else:
        body = _resolve_body(doc, None)
        if body.Tip is None:
            raise HandlerError("the body has no features to copy")
        originals = [body.Tip]
    feat = body.newObject(type_id, type_id.split("::")[1])
    if label:
        feat.Label = label
    if whole_body:
        feat.TransformMode = "Whole shape"
    else:
        feat.Originals = originals
    return body, feat


@_mutating("Mirror")
def mirror(doc, plane="YZ", features=None, whole_body=False, label=None):
    body, feat = _transformed(doc, "PartDesign::Mirrored", features, whole_body, label)
    feat.MirrorPlane = _reference(doc, body, plane)
    return _finish(doc, feat, body)


def _set_direction(feat, suffix, count, spacing, length):
    count = int(count)
    if count < 2:
        raise HandlerError("count must be at least 2 (it includes the original)")
    setattr(feat, "Occurrences" + suffix, count)
    # -1 = "use the default spacing". FreeCAD 1.1 leaves Spacings2 at [0.0], which
    # stacks every copy in the second direction on top of the first row.
    setattr(feat, "Spacings" + suffix, [-1.0] * (count - 1))
    if spacing is not None:
        setattr(feat, "Mode" + suffix, "Spacing")
        setattr(feat, "Offset" + suffix, float(spacing))
    elif length is not None:
        setattr(feat, "Mode" + suffix, "Extent")
        setattr(feat, "Length" + suffix, float(length))
    else:
        raise HandlerError("pass spacing= (between copies) or length= (whole pattern)")


@_mutating("Linear pattern")
def linear_pattern(doc, direction, count, spacing=None, length=None, features=None,
                   reversed=False, direction2=None, count2=None, spacing2=None,
                   length2=None, whole_body=False, label=None):
    body, feat = _transformed(doc, "PartDesign::LinearPattern", features, whole_body, label)
    feat.Direction = _reference(doc, body, direction)
    _set_direction(feat, "", count, spacing, length)
    feat.Reversed = bool(reversed)
    if direction2:
        feat.Direction2 = _reference(doc, body, direction2)
        _set_direction(feat, "2", count2 or 2, spacing2, length2)
    return _finish(doc, feat, body)


@_mutating("Polar pattern")
def polar_pattern(doc, count, axis="Z", angle=360.0, features=None, reversed=False,
                  whole_body=False, label=None):
    body, feat = _transformed(doc, "PartDesign::PolarPattern", features, whole_body, label)
    feat.Axis = _reference(doc, body, axis)
    if int(count) < 2:
        raise HandlerError("count must be at least 2 (it includes the original)")
    feat.Occurrences = int(count)
    feat.Mode = "Extent"
    feat.Angle = float(angle)
    feat.Reversed = bool(reversed)
    return _finish(doc, feat, body)


@_mutating("Press/Pull")
def press_pull(doc, face, distance=None, radius=None, label=None):
    from .presspull import PressPullError, RadiusPull, start

    obj_name, _, sub = face.partition(":")
    if not sub:
        raise HandlerError("face must look like 'Pad:Face6', got %r" % face)
    if (distance is None) == (radius is None):
        raise HandlerError("pass distance= or (for a cylindrical face) radius=")
    try:
        op = start(_obj(doc, obj_name), sub)
        if radius is not None:
            if not isinstance(op, RadiusPull):
                raise HandlerError("radius= is for cylindrical faces; use distance=")
            original = op.original
            op.set_radius(radius)
        else:
            if abs(float(distance)) < 1e-9:
                raise HandlerError("distance must not be zero")
            original = getattr(op, "original", None)
            op.set_distance(distance)
    except PressPullError as e:
        raise HandlerError(str(e))
    if not isinstance(op, RadiusPull):
        if label:
            op.feature.Label = label
        return _finish(doc, op.feature, op.body)
    if op.feature is None:
        raise HandlerError("that is the current radius already")
    doc.recompute()
    result = _feature_result(op.body.Tip, op.body)
    result.update({"feature": op.feature.Name,
                   "radius": {"from": _round(original), "to": _round(op.radius)}})
    return result


def _body_arg(doc, name):
    obj = _obj(doc, name)
    body = bodies.body_of(obj)
    if body is None:
        raise HandlerError("%s is not a body or in one" % obj.Label)
    return body


@_mutating("Combine")
def combine(doc, target, tools, operation="join", keep_tools=False, label=None):
    if isinstance(tools, str):
        tools = [tools]
    target_body = _body_arg(doc, target)
    feature = bodies.combine(target_body, [_body_arg(doc, t) for t in tools], operation,
                             keep_tools)
    if label:
        feature.Label = label
    return _finish(doc, feature, target_body)


@_mutating("Split body")
def split_body(doc, body, tool, offset=0.0):
    body_obj = _body_arg(doc, body)
    obj, sub = _reference(doc, body_obj, tool)
    pieces = bodies.split(body_obj, (obj, sub[0]), offset)
    doc.recompute()
    return {"bodies": [{"body": b.Name, "label": b.Label,
                        "shape": _shape_summary(b.Shape)} for b in pieces],
            "original": body_obj.Name}


@_mutating("Set property")
def set_property(doc, name, property, value):
    obj = _obj(doc, name)
    if property not in obj.PropertiesList:
        raise HandlerError("%s has no property %r" % (obj.Name, property))
    setattr(obj, property, value)
    return {"name": obj.Name, "property": property, "value": str(getattr(obj, property))}


@_mutating("Delete")
def delete_object(doc, name):
    obj = _obj(doc, name)
    body = _body_of(obj)
    if body is not None:
        body.removeObject(obj)
    doc.removeObject(obj.Name)
    return {"deleted": name}


# ---------------------------------------------------------------------------
# timeline (feature history)

def _timeline_body(doc, body):
    from . import history

    if body:
        return _resolve_body(doc, body)
    found = history.find_body(doc)
    if found is None:
        raise HandlerError("document has no PartDesign body")
    return found


def get_timeline(body=None, document=None):
    from . import history

    doc = _doc(document)
    b = _timeline_body(doc, body)
    return {"body": b.Name, "tip": b.Tip.Name if b.Tip else None,
            "marker_index": history.marker_index(b), "entries": history.entries(b)}


@_mutating("Roll timeline")
def roll_timeline(doc, to=None, steps=None, body=None):
    from . import history

    b = _timeline_body(doc, body)
    if steps is not None:
        history.step(b, int(steps))
    elif to == "end":
        history.roll_to_end(b)
    elif to == "start":
        history.roll_to_start(b)
    elif to:
        obj = _obj(doc, to)
        if obj not in b.Group:
            raise HandlerError("%s is not in body %s" % (obj.Name, b.Name))
        history.roll_to(b, obj)
    else:
        raise HandlerError("pass to= (feature name, 'start' or 'end') or steps=")
    return {"body": b.Name, "tip": b.Tip.Name if b.Tip else None,
            "marker_index": history.marker_index(b)}


@_mutating("Move feature")
def move_feature(doc, name, after=None, before=None, with_sketch=True):
    from . import history

    obj = _obj(doc, name)
    b = history.body_of(obj)
    if b is None:
        raise HandlerError("%s is not in a PartDesign body" % obj.Name)
    group = b.Group
    if (after is None) == (before is None):
        raise HandlerError("pass after= or before= (a feature name, or 'start' / 'end')")
    target = after if after is not None else before
    if target == "start":
        boundary = -1
    elif target == "end":
        boundary = len(group) - 1
    else:
        other = _obj(doc, target)
        if other not in group:
            raise HandlerError("%s is not in body %s" % (other.Name, b.Name))
        boundary = group.index(other) - (0 if after is not None else 1)
    try:
        moved = history.move(b, obj, boundary, with_sketch=bool(with_sketch))
    except ValueError as e:
        raise HandlerError(str(e))
    doc.recompute()
    return {"moved": moved, "body": b.Name, "order": [o.Name for o in b.Group],
            "tip": b.Tip.Name if b.Tip else None,
            "shape": _shape_summary(b.Shape)}


@_mutating("Suppress feature")
def suppress_feature(doc, name, suppressed=True):
    from . import history

    obj = _obj(doc, name)
    try:
        history.set_suppressed(obj, suppressed)
    except ValueError as e:
        raise HandlerError(str(e))
    return {"name": obj.Name, "suppressed": bool(suppressed)}


def recompute(document=None):
    doc = _doc(document)
    result = {"document": doc.Name}
    result.update(_recompute_report(doc))
    return result


def undo(document=None, steps=1):
    doc = _doc(document)
    done = []
    for _ in range(int(steps)):
        names = doc.UndoNames
        if not names:
            break
        done.append(names[0])
        doc.undo()
    doc.recompute()
    return {"undone": done}


def redo(document=None, steps=1):
    doc = _doc(document)
    done = []
    for _ in range(int(steps)):
        names = doc.RedoNames
        if not names:
            break
        done.append(names[0])
        doc.redo()
    doc.recompute()
    return {"redone": done}


# ---------------------------------------------------------------------------
# view (GUI only)

_VIEWS = {
    "isometric": "viewIsometric", "front": "viewFront", "back": "viewRear",
    "top": "viewTop", "bottom": "viewBottom", "left": "viewLeft", "right": "viewRight",
}


def _view():
    if not Gui:
        raise HandlerError("this needs the FreeCAD GUI (running headless)")
    if Gui.ActiveDocument is None:
        raise HandlerError("no document is open")
    return Gui.ActiveDocument.ActiveView


def set_view(view="isometric", fit=True):
    v = _view()
    if view:
        method = _VIEWS.get(view)
        if method is None:
            raise HandlerError("view must be one of: %s" % ", ".join(_VIEWS))
        getattr(v, method)()
    if fit:
        v.fitAll()
    return {"view": view}


def screenshot(view=None, width=1024, height=768, fit=False):
    v = _view()
    if view:
        set_view(view, fit)
    elif fit:
        v.fitAll()
    Gui.updateGui()
    fd, path = tempfile.mkstemp(suffix=".png", prefix="fusion_freecad_")
    os.close(fd)
    try:
        v.saveImage(path, int(width), int(height), "Current")
        with open(path, "rb") as f:
            data = f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return {"png_base64": base64.b64encode(data).decode("ascii"),
            "width": int(width), "height": int(height)}


# ---------------------------------------------------------------------------
# import / export

_EXPORT_FORMATS = {".step": "step", ".stp": "step", ".iges": "iges", ".igs": "iges",
                   ".stl": "stl", ".obj": "obj", ".brep": "brep", ".brp": "brep",
                   ".fcstd": "fcstd", ".dxf": "dxf"}


def _flat_outline(shape):
    """The largest planar face of a shape, laid onto XY with its corner at the origin."""
    faces = [f for f in shape.Faces if type(f.Surface).__name__ == "Plane"]
    if not faces:
        raise HandlerError("DXF export needs a flat part (a plate or flat pattern)")
    face = max(faces, key=lambda f: f.Area)
    u0, u1, v0, v1 = face.ParameterRange
    normal = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    flat = face.copy()
    flat.transformShape(App.Placement(V(), App.Rotation(normal, V(0, 0, 1))).toMatrix())
    bb = flat.BoundBox
    flat.translate(V(-bb.XMin, -bb.YMin, -bb.ZMin))
    return flat


def _export_dxf(doc, objs, path):
    import Part
    import importDXF

    edges, x = [], 0.0
    for o in objs:
        flat = _flat_outline(o.Shape)
        flat.translate(V(x, 0, 0))
        edges += flat.Edges
        x = flat.BoundBox.XMax + 10  # side by side, 10 mm apart
    tmp = doc.addObject("Part::Feature", "DXFExport")
    try:
        tmp.Shape = Part.Compound(edges)
        importDXF.export([tmp], path)
    finally:
        doc.removeObject(tmp.Name)


def export(path, objects=None, document=None):
    doc = _doc(document)
    ext = os.path.splitext(path)[1].lower()
    fmt = _EXPORT_FORMATS.get(ext)
    if fmt is None:
        raise HandlerError("unsupported extension %r (use %s)"
                           % (ext, ", ".join(sorted(_EXPORT_FORMATS))))
    if fmt == "fcstd":
        doc.saveCopy(path)
        return {"path": path, "format": fmt}

    if objects:
        objs = [_obj(doc, n) for n in objects]
    else:
        # Default: every body plus loose solids that aren't inside a body.
        objs = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        objs += [o for o in doc.Objects
                 if o.TypeId.startswith("Part::") and _body_of(o) is None
                 and not o.InList and hasattr(o, "Shape") and o.Shape.Solids]
    if not objs:
        raise HandlerError("nothing to export")

    if fmt == "dxf":
        _export_dxf(doc, objs, path)
    elif fmt in ("step", "iges"):
        import Import
        Import.export(objs, path)
    elif fmt in ("stl", "obj"):
        import Mesh
        Mesh.export(objs, path)
    else:
        import Part
        Part.makeCompound([o.Shape for o in objs]).exportBrep(path)
    return {"path": path, "format": fmt, "objects": [o.Name for o in objs],
            "bytes": os.path.getsize(path)}


def import_file(path, document=None):
    if not os.path.isfile(path):
        raise HandlerError("file not found: %s" % path)
    doc = _doc(document) if document or App.ActiveDocument else App.newDocument("Imported")
    before = set(o.Name for o in doc.Objects)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".stl", ".obj"):
        import Mesh
        Mesh.insert(path, doc.Name)
    else:
        import Import
        Import.insert(path, doc.Name)
    doc.recompute()
    return {"document": doc.Name,
            "new_objects": [o.Name for o in doc.Objects if o.Name not in before]}


# ---------------------------------------------------------------------------
# escape hatch

def run_python(code, document=None):
    """Run arbitrary Python inside FreeCAD. Set ``result`` to return a value."""
    doc = App.ActiveDocument if document is None else _doc(document)
    namespace = {"App": App, "FreeCAD": App, "Gui": Gui, "FreeCADGui": Gui, "doc": doc}
    out = io.StringIO()
    if doc:
        _open_transaction(doc, "Python")

    def still_open():
        # The code may have closed the document it started in.
        return doc is not None and any(d is doc for d in App.listDocuments().values())

    try:
        with contextlib.redirect_stdout(out):
            exec(compile(code, "<mcp>", "exec"), namespace)
    except Exception:
        if still_open():
            doc.abortTransaction()
        raise
    if still_open():
        doc.commitTransaction()
    result = namespace.get("result")
    try:
        json.dumps(result)
    except (TypeError, ValueError):
        result = repr(result)
    return {"stdout": out.getvalue(), "result": result}


HANDLERS = {fn.__name__: fn for fn in [
    ping, list_documents, new_document, open_document, save_document, close_document,
    activate_document, list_objects, get_object, get_topology, measure,
    create_body, create_sketch, add_sketch_geometry, set_dimension, delete_sketch_geometry,
    move_sketch_geometry, set_parameters, delete_parameter, rename_parameter,
    get_parameters, set_expression,
    pad, pocket, revolve, fillet, chamfer,
    press_pull, combine, split_body, hole, shell, mirror, linear_pattern, polar_pattern, loft, sweep,
    set_property, delete_object, get_timeline, roll_timeline, move_feature, suppress_feature,
    recompute, undo, redo,
    set_view, screenshot, export, import_file, run_python,
]}


def _extra_handlers():
    from . import (handlers_addons, handlers_assembly, handlers_bodies,
                   handlers_construct, handlers_features, handlers_inspect,
                   handlers_sketch)
    return dict(handlers_addons.HANDLERS, **handlers_assembly.HANDLERS,
                **handlers_bodies.HANDLERS, **handlers_construct.HANDLERS,
                **handlers_features.HANDLERS, **handlers_inspect.HANDLERS,
                **handlers_sketch.HANDLERS)


HANDLERS.update(_extra_handlers())
