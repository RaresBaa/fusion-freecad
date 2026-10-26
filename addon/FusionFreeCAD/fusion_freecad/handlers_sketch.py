"""RPC handlers for sketch tools beyond drawing shapes (Fusion: Project, Offset, Sketch
Fillet). Sketch coordinates are the sketch's own 2D ones; geometry indices are the
ones get_object lists, and projected (external) geometry has negative indices, as in
Sketcher constraints.
"""

import math

import FreeCAD as App

from .handlers import (HandlerError, _mutating, _obj, _sketch, _sketch_result, _vec)

V = App.Vector
TOL = 1e-6


@_mutating("Project to sketch")
def project_to_sketch(doc, sketch, elements, defining=False):
    """Project model edges, faces or vertices into the sketch (Fusion: Project). The
    projections follow the model. ``defining``: they also count as sketch geometry, so
    a pad can use them as its profile."""
    sk = _sketch(doc, sketch)
    if isinstance(elements, str):
        elements = [elements]
    before = len(sk.ExternalGeo)
    for ref in elements:
        name, _, sub = str(ref).partition(":")
        obj = _obj(doc, name)
        if not sub:
            raise HandlerError("elements look like 'Pad:Edge3', got %r" % ref)
        try:
            sk.addExternal(obj.Name, sub, bool(defining))
        except Exception as e:
            raise HandlerError("can't project %s: %s" % (ref, e))
    doc.recompute()
    # GeoId -1 is ExternalGeo[0] (the H axis), -2 the V axis, then the projections.
    result = _sketch_result(sk, sk.solve())
    result["external_indices"] = [-(i + 1) for i in range(before, len(sk.ExternalGeo))]
    return result


def _sketch_geometry(edge):
    """A sketch geometry for an edge of the offset wire (in the sketch's XY plane)."""
    import Part

    curve = edge.Curve
    if isinstance(curve, Part.Line):
        return Part.LineSegment(edge.Vertexes[0].Point, edge.Vertexes[-1].Point)
    if isinstance(curve, Part.Circle):
        circle = Part.Circle(curve.Center, V(0, 0, 1), curve.Radius)
        if edge.isClosed():
            return circle
        start, end = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        if curve.Axis.z < 0:  # sketch arcs run counter-clockwise about +Z
            start, end = end, start
        a0, a1 = circle.parameter(start), circle.parameter(end)
        if a1 <= a0:
            a1 += 2 * math.pi
        return Part.ArcOfCircle(circle, a0, a1)
    return edge.toNurbs().Edges[0].Curve


def _end_points(sk, geo):
    g = sk.Geometry[geo]
    if not hasattr(g, "StartPoint"):
        return []
    return [(1, sk.getPoint(geo, 1)), (2, sk.getPoint(geo, 2))]


def _join_ends(sk, indices):
    """Coincident constraints where the new geometry's ends meet."""
    import Sketcher

    ends = [(g, pos, p) for g in indices for pos, p in _end_points(sk, g)]
    for i, (g1, pos1, p1) in enumerate(ends):
        for g2, pos2, p2 in ends[i + 1:]:
            if g1 != g2 and (p1 - p2).Length < TOL * 1000:
                sk.addConstraint(Sketcher.Constraint("Coincident", g1, pos1, g2, pos2))


@_mutating("Offset sketch geometry")
def offset_sketch(doc, sketch, distance, geometry=None, join="arc"):
    """Offset closed or open chains of sketch geometry (Fusion: Offset). Positive
    distance goes outward from a closed profile. ``geometry``: indices to offset,
    default every non-construction element. ``join``: 'arc' rounds outside corners,
    'intersection' keeps them sharp."""
    import Part

    sk = _sketch(doc, sketch)
    if geometry is None:
        geometry = [i for i in range(len(sk.Geometry)) if not sk.getConstruction(i)]
    geometry = [int(g) for g in geometry]
    bad = [g for g in geometry if not 0 <= g < len(sk.Geometry)]
    if bad or not geometry:
        raise HandlerError("%s has no geometry %s" % (sk.Name, bad or "to offset"))
    if join not in ("arc", "intersection"):
        raise HandlerError("join must be arc or intersection")
    edges = [sk.Geometry[g].toShape() for g in geometry]
    added = []
    for chain in Part.sortEdges(edges):
        wire = Part.Wire(chain)
        try:
            result = wire.makeOffset2D(float(distance), 0 if join == "arc" else 2,
                                       False, not wire.isClosed(), False)
        except Exception as e:
            raise HandlerError("can't offset by %s: %s" % (distance, e))
        first = len(sk.Geometry)
        for edge in result.Edges:
            sk.addGeometry(_sketch_geometry(edge), False)
        added += list(range(first, len(sk.Geometry)))
    _join_ends(sk, added)
    out = _sketch_result(sk, sk.solve())
    out["geometry_indices"] = added
    return out


def _corners(sk):
    """Points where two non-construction line segments meet end to end."""
    seen = []
    ends = [(g, pos, p) for g in range(len(sk.Geometry))
            if type(sk.Geometry[g]).__name__ == "LineSegment" and not sk.getConstruction(g)
            for pos, p in _end_points(sk, g)]
    for i, (g1, _, p1) in enumerate(ends):
        for g2, _, p2 in ends[i + 1:]:
            if g1 != g2 and (p1 - p2).Length < TOL * 1000 \
                    and not any((p1 - s).Length < TOL * 1000 for s in seen):
                seen.append(p1)
    return seen


@_mutating("Sketch fillet")
def fillet_sketch(doc, sketch, radius, corners=None):
    """Round corners between lines in a sketch (Fusion: Sketch Fillet). ``corners``:
    [[x, y], ...] in sketch coordinates; default every corner where two lines meet."""
    sk = _sketch(doc, sketch)
    points = [_vec(c, "corner") for c in corners] if corners else _corners(sk)
    if not points:
        raise HandlerError("%s has no corners between lines" % sk.Name)
    arcs = []
    for point in points:
        # Look the corner up again each time: every fillet trims the lines.
        at = next(((g, pos) for g in range(len(sk.Geometry))
                   if type(sk.Geometry[g]).__name__ == "LineSegment"
                   for pos, p in _end_points(sk, g) if (p - point).Length < 1e-3), None)
        if at is None:
            raise HandlerError("no corner between lines at %s"
                               % [round(point.x, 3), round(point.y, 3)])
        before = len(sk.Geometry)
        try:
            sk.fillet(at[0], at[1], float(radius), True, False)
        except Exception as e:
            raise HandlerError("can't fillet the corner at %s with radius %s: %s"
                               % ([round(point.x, 3), round(point.y, 3)], radius, e))
        arcs += list(range(before, len(sk.Geometry)))
    out = _sketch_result(sk, sk.solve())
    out["geometry_indices"] = arcs
    return out


HANDLERS = {fn.__name__: fn for fn in [project_to_sketch, offset_sketch, fillet_sketch]}
