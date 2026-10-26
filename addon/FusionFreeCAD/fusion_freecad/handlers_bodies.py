"""RPC handlers that place and copy whole bodies (Fusion: Move/Copy, Appearance).

They work on anything with a Placement: bodies, assembly links, Part objects.
"""

import math

import FreeCAD as App

from .handlers import (HandlerError, _mutating, _obj, _round, _shape_summary, _vec,
                       _vec_out)

V = App.Vector
_AXES = {"X": V(1, 0, 0), "Y": V(0, 1, 0), "Z": V(0, 0, 1)}


def _placed(obj):
    if "Placement" not in obj.PropertiesList:
        raise HandlerError("%s has no placement" % obj.Label)
    return obj


def _result(obj):
    p = obj.Placement
    axis, angle = p.Rotation.Axis, p.Rotation.Angle
    return {"name": obj.Name, "label": obj.Label,
            "placement": {"base": _vec_out(p.Base), "axis": _vec_out(axis),
                          "angle": _round(math.degrees(angle))},
            "shape": _shape_summary(obj.Shape) if hasattr(obj, "Shape") else None}


def _motion(translate, axis, angle, center):
    axis_vec = _AXES.get(str(axis).upper()) if isinstance(axis, str) else \
        _vec(axis, "axis") if axis is not None else _AXES["Z"]
    if axis_vec is None or axis_vec.Length == 0:
        raise HandlerError("axis must be X, Y, Z or [x, y, z]")
    pivot = _vec(center, "center") if center is not None else V()
    move = App.Placement(_vec(translate, "translate") if translate is not None else V(),
                         App.Rotation())
    if angle:
        turn = App.Placement(V(), App.Rotation(axis_vec, float(angle)))
        move = move * App.Placement(pivot, App.Rotation()) * turn \
            * App.Placement(-pivot, App.Rotation())
    return move


@_mutating("Move")
def move_body(doc, name, translate=None, axis=None, angle=0.0, center=None):
    """Move a body: rotate ``angle`` degrees about ``axis`` through ``center``, then
    translate. Relative to where it is."""
    obj = _placed(_obj(doc, name))
    if translate is None and not angle:
        raise HandlerError("pass translate=[x, y, z] and/or angle= (with axis=)")
    obj.Placement = _motion(translate, axis, angle, center) * obj.Placement
    doc.recompute()
    return _result(obj)


@_mutating("Copy")
def copy_body(doc, name, linked=False, translate=None, label=None):
    """A copy of a body: independent (its features copied too) or ``linked`` (an
    App::Link that always shows the original's current shape)."""
    obj = _placed(_obj(doc, name))
    if linked:
        copy = doc.addObject("App::Link", obj.Name + "Link")
        copy.LinkedObject = obj
        copy.Placement = obj.Placement
    else:
        copy = doc.copyObject(obj, True)
    copy.Label = label or "%s copy" % obj.Label
    if translate is not None:
        copy.Placement = App.Placement(_vec(translate, "translate"), App.Rotation()) \
            * copy.Placement
    doc.recompute()
    out = _result(copy)
    out["linked"] = bool(linked)
    return out


def _color(value):
    if isinstance(value, str):
        text = value.lstrip("#")
        if len(text) != 6:
            raise HandlerError("colour must be '#rrggbb' or [r, g, b], got %r" % value)
        return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    rgb = [float(c) for c in value]
    if len(rgb) != 3:
        raise HandlerError("colour must be '#rrggbb' or [r, g, b]")
    if any(c > 1 for c in rgb):  # 0-255
        rgb = [c / 255.0 for c in rgb]
    return tuple(rgb)


@_mutating("Appearance")
def appearance(doc, name, color=None, transparency=None):
    """Colour (and transparency, 0-100) of a body or part in the 3D view."""
    obj = _obj(doc, name)
    vo = getattr(obj, "ViewObject", None)
    if vo is None:
        raise HandlerError("appearance needs FreeCAD's GUI (this one is headless)")
    if "OverrideMaterial" in vo.PropertiesList:  # a link: its own material on top
        material = vo.ShapeMaterial
        if color is not None:
            material.DiffuseColor = _color(color)
        if transparency is not None:
            material.Transparency = int(transparency) / 100.0
        vo.ShapeMaterial = material
        vo.OverrideMaterial = True
        return {"name": obj.Name,
                "color": [_round(c) for c in vo.ShapeMaterial.DiffuseColor[:3]],
                "transparency": round(vo.ShapeMaterial.Transparency * 100)}
    if color is not None:
        vo.ShapeColor = _color(color)
    if transparency is not None:
        vo.Transparency = int(transparency)
    return {"name": obj.Name, "color": [_round(c) for c in vo.ShapeColor[:3]],
            "transparency": vo.Transparency}


HANDLERS = {fn.__name__: fn for fn in [move_body, copy_body, appearance]}
