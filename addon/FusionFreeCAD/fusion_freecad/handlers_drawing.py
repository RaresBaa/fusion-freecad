"""RPC handlers for 2D drawings (Fusion: Drawing; FreeCAD: TechDraw): a page with a
projection group of standard views, dimensions on them, and export to DXF / PDF / SVG.

View geometry is named like TechDraw names it: ``Edge0``, ``Vertex0`` (from 0, unlike
3D shapes). ``get_topology`` on a view lists it, in model millimetres.
"""

import glob
import os
import time

import FreeCAD as App

from .handlers import HandlerError, _doc, _mutating, _obj, _round

VIEWS = ["Front", "Rear", "Top", "Bottom", "Left", "Right", "FrontTopLeft",
         "FrontTopRight", "FrontBottomLeft", "FrontBottomRight"]
_VIEW_ALIASES = {"isometric": "FrontTopRight", "iso": "FrontTopRight", "back": "Rear"}
_DEFAULT_TEMPLATE = {"first": "A4_Landscape_TD", "third": "ANSIB_Landscape"}
_SCALES = [1 / 100, 1 / 50, 1 / 20, 1 / 10, 1 / 5, 1 / 2, 1, 2, 5, 10]
_MARGIN = 15.0  # mm kept clear inside the sheet's edges
_TITLE_BAND = 60.0  # mm at the bottom left to the title block (ISO and ANSI templates)
_GAP = 8.0  # mm between a view and its first dimension, and between stacked ones
_DIMENSION_TYPES = {"distance": "Distance", "distance_x": "DistanceX",
                    "distance_y": "DistanceY", "radius": "Radius",
                    "diameter": "Diameter", "angle": "Angle"}


def _template_dir():
    return os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates")


def _template(template, projection):
    """A template .svg path, or a template's name ('A3_Landscape_TD') from FreeCAD's
    TechDraw templates."""
    template = template or _DEFAULT_TEMPLATE[projection]
    if os.path.isfile(template):
        return template
    wanted = os.path.splitext(os.path.basename(template))[0].lower()
    found = glob.glob(os.path.join(_template_dir(), "**", "*.svg"), recursive=True)
    for path in found:
        if os.path.splitext(os.path.basename(path))[0].lower() == wanted:
            return path
    names = sorted({os.path.splitext(os.path.basename(p))[0] for p in found})
    raise HandlerError("template %r not found; pass an .svg path or one of: %s"
                       % (template, ", ".join(names)))


def _view_type(name):
    key = str(name).replace(" ", "").replace("_", "")
    for v in VIEWS:
        if v.lower() == key.lower():
            return v
    if key.lower() in _VIEW_ALIASES:
        return _VIEW_ALIASES[key.lower()]
    raise HandlerError("unknown view %r (use %s or Isometric)" % (name, ", ".join(VIEWS)))


def _check_shape(obj):
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        raise HandlerError("%s has no shape to draw" % obj.Label)


def _page_of(view):
    for o in view.InList:
        if o.isDerivedFrom("TechDraw::DrawPage"):
            return o
        if o.isDerivedFrom("TechDraw::DrawProjGroup"):
            return _page_of(o)
    raise HandlerError("%s is not on a drawing page" % view.Label)


def _part_view(doc, name):
    view = _obj(doc, name)
    if not view.isDerivedFrom("TechDraw::DrawViewPart"):
        raise HandlerError("%s is not a drawing view; use a view name from create_drawing"
                           % view.Label)
    return view


@_mutating("Drawing")
def create_drawing(doc, objects, views=None, template=None, scale=None,
                   projection="first", label=None):
    """A drawing page with a projection group of ``views`` of ``objects`` (bodies or
    parts). Front is the anchor and always included. ``scale`` None fits the page."""
    if projection not in _DEFAULT_TEMPLATE:
        raise HandlerError("projection is 'first' (ISO) or 'third' (ANSI)")
    if isinstance(objects, str):
        objects = [objects]
    sources = [_obj(doc, n) for n in objects or []]
    if not sources:
        raise HandlerError("pass objects=['Body', ...] to draw")
    for o in sources:
        _check_shape(o)
    wanted = [_view_type(v) for v in (views or ["Front", "Top", "Right", "Isometric"])]
    wanted = ["Front"] + [v for v in dict.fromkeys(wanted) if v != "Front"]
    template_path = _template(template, projection)

    page = doc.addObject("TechDraw::DrawPage", "Drawing")
    if label:
        page.Label = label
    tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    tpl.Template = template_path
    page.Template = tpl
    group = doc.addObject("TechDraw::DrawProjGroup", "Views")
    page.addView(group)
    group.Source = sources
    group.ProjectionType = "First angle" if projection == "first" else "Third angle"
    group.ScaleType = "Custom"
    group.Scale = float(scale) if scale else 1.0
    for v in wanted:
        group.addProjection(v)
    doc.recompute()
    _lay_out(page, group, fit=not scale)
    return {"page": page.Name, "template": template_path, "scale": _round(group.Scale),
            "group": group.Name, "views": {v.Type: v.Name for v in group.Views}}


def _signature(view):
    box = App.BoundBox()
    edges = view.getVisibleEdges()
    for e in edges:
        box.add(e.BoundBox)
    return len(edges), round(box.XLength, 6), round(box.YLength, 6)


def _expected_size(view):
    """An orthographic view's width and height on the sheet, from the model's bounding
    box (exact for those views); None for others."""
    d = view.Direction
    if sum(1 for c in (d.x, d.y, d.z) if abs(c) > 1e-9) != 1:
        return None
    box = App.BoundBox()
    for src in view.Source:
        box.add(src.Shape.BoundBox)
    if not box.isValid():
        return None
    x = view.XDirection
    y = d.cross(x)
    corners = [App.Vector(box.getPoint(i)) for i in range(8)]
    us = [c.dot(x) for c in corners]
    vs = [c.dot(y) for c in corners]
    k = view.getScale()
    return round((max(us) - min(us)) * k, 3), round((max(vs) - min(vs)) * k, 3)


def _settle(views, timeout=20.0):
    """Wait for TechDraw's hidden-line removal. With the GUI up it runs in a thread and
    the new edges (and the group's spacing, which follows them) only arrive through
    the event loop; reading them straight after a recompute gives the old ones."""
    if not App.GuiUp:
        return
    import FreeCADGui as Gui
    views = list(views)
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        Gui.updateGui()
        now = [_signature(v) for v in views]
        ready = all(sig[0] and (exp is None or
                                (abs(sig[1] - exp[0]) < 1e-2 and abs(sig[2] - exp[1]) < 1e-2))
                    for sig, exp in zip(now, (_expected_size(v) for v in views)))
        if ready and now == last:
            return
        last = now
        time.sleep(0.1)


def _view_box(view):
    """The view's visible geometry, on the sheet (mm), around the view's own origin."""
    box = App.BoundBox()
    for e in view.getVisibleEdges():
        box.add(e.BoundBox)
    return box


def _group_box(group):
    box = App.BoundBox()
    for v in group.Views:
        b = _view_box(v)
        if b.isValid():
            b.move(App.Vector(v.X.Value, v.Y.Value, 0))
            box.add(b)
    return box


def _lay_out(page, group, fit):
    """Centre the views in the sheet above the title block; with ``fit``, at the
    largest standard scale that fits there (TechDraw's own automatic scale never
    enlarges, so small parts come out tiny)."""
    width, height = page.PageWidth, page.PageHeight
    area_w = width - 2 * _MARGIN
    area_h = height - _MARGIN - _TITLE_BAND

    def apply(scale):
        group.Scale = scale
        group.recompute(True)
        _settle(group.Views)
        group.recompute(True)  # spread the views by their new sizes
        _settle(group.Views)
        box = _group_box(group)
        return box, box.XLength <= area_w * 0.85 and box.YLength <= area_h * 0.85

    if fit:
        # Guess from the size at 1:1 (the gaps between views don't scale, so the guess
        # runs large), then step down to the first that fits.
        box, _ = apply(1.0)
        guess = min(area_w * 0.85 / max(box.XLength, 1e-6),
                    area_h * 0.85 / max(box.YLength, 1e-6))
        candidates = [s for s in reversed(_SCALES) if s <= guess] or _SCALES[:1]
        for s in candidates:
            box, ok = apply(s)
            if ok or s == candidates[-1]:
                break
    else:
        _settle(group.Views)
    box = _group_box(group)
    group.X = width / 2 - (box.XMin + box.XMax) / 2
    group.Y = _TITLE_BAND + area_h / 2 - (box.YMin + box.YMax) / 2
    group.recompute(True)


def view_topology(view, max_items=300):
    """A drawing view's visible edges and vertices, in model mm in the view's 2D frame
    (``get_topology`` on a view)."""
    _settle([view])
    scale = view.getScale() or 1.0

    def pt(v):
        return [_round(v.x / scale), _round(v.y / scale)]

    edges = []
    for i, e in enumerate(view.getVisibleEdges()[:max_items]):
        kind = type(e.Curve).__name__
        item = {"name": "Edge%d" % i, "curve": kind, "length": _round(e.Length / scale)}
        if kind in ("Line", "LineSegment"):
            item["start"], item["end"] = pt(e.Vertexes[0].Point), pt(e.Vertexes[-1].Point)
        elif hasattr(e.Curve, "Radius"):
            item["center"] = pt(e.Curve.Center)
            item["radius"] = _round(e.Curve.Radius / scale)
        else:
            item["center"] = pt(e.CenterOfMass)
        edges.append(item)
    vertices = [{"name": "Vertex%d" % i, "point": pt(v)}  # plain vectors
                for i, v in enumerate(view.getVisibleVertexes()[:max_items])]
    return {"name": view.Name, "view": getattr(view, "Type", view.Label),
            "scale": _round(scale), "edges": edges, "vertices": vertices}


def _point(view, ref):
    """Where a view element sits on the sheet (relative to the view), and for an edge
    its direction and radius."""
    kind, index = ref.rstrip("0123456789"), int(ref[len(ref.rstrip("0123456789")):] or -1)
    try:
        if kind == "Vertex":
            return view.getVisibleVertexes()[index], None, None
        edge = view.getVisibleEdges()[index]
    except IndexError:
        raise HandlerError("%s has no %s" % (view.Label, ref))
    if hasattr(edge.Curve, "Radius"):
        return edge.Curve.Center, None, edge.Curve.Radius
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    return (a + b) * 0.5, b - a, None


def _free_side(view, along_y):
    """+1 or -1: the side of the view (above/below, or right/left) with no neighbouring
    view of its projection group, so dimensions there don't run into it."""
    group = next((o for o in view.InList if o.isDerivedFrom("TechDraw::DrawProjGroup")),
                 None)
    if group is None:
        return 1
    me = view.Y.Value if along_y else view.X.Value
    other = view.X.Value if along_y else view.Y.Value
    blocked = set()
    for v in group.Views:
        if v is view:
            continue
        here = v.X.Value if along_y else v.Y.Value
        there = v.Y.Value if along_y else v.X.Value
        if abs(here - other) < 1e-6:
            blocked.add(1 if there > me else -1)
    return -1 if 1 in blocked and -1 not in blocked else 1


def _place(dim, view, page, kind, refs):
    """Put a new dimension's text outside the view, stacked after the ones already on
    that side (TechDraw leaves it at the view's centre)."""
    box = _view_box(view)
    points = [_point(view, r) for r in refs]
    if not box.isValid():
        return
    if kind in ("radius", "diameter") and points and points[0][2]:
        centre, _, radius = points[0]
        d = (radius + _GAP) * 0.7071
        dim.X, dim.Y = centre.x + d, centre.y + d
        return
    centre = (sum((p[0] for p in points), App.Vector()) * (1.0 / len(points))
              if points else box.Center)
    if kind == "angle":
        dim.X, dim.Y = centre.x + _GAP, centre.y + _GAP
        return
    if kind in ("distance_y", "extent_y"):
        horizontal = False
    elif kind in ("distance_x", "extent_x"):
        horizontal = True
    else:  # an edge or two points: dimension along whichever way they run most
        span = points[0][1] if len(points) == 1 else points[-1][0] - points[0][0]
        horizontal = span is None or abs(span.x) >= abs(span.y)
    side = _free_side(view, along_y=horizontal)
    others = [o for o in page.Views if o is not dim
              and o.isDerivedFrom("TechDraw::DrawViewDimension")
              and o.References2D and o.References2D[0][0] is view]
    if horizontal:
        edge = box.YMax if side > 0 else box.YMin
        taken = sum(1 for o in others if (o.Y.Value - edge) * side > 0)
        dim.X, dim.Y = centre.x, edge + side * _GAP * (taken + 1)
    else:
        edge = box.XMax if side > 0 else box.XMin
        taken = sum(1 for o in others if (o.X.Value - edge) * side > 0)
        dim.X, dim.Y = edge + side * _GAP * (taken + 1), centre.y


@_mutating("Dimension")
def drawing_dimension(doc, view, type, references=None, label=None):
    """A dimension on a drawing view. ``references`` are the view's ``Edge0`` /
    ``Vertex0`` names (see ``get_topology`` on the view): one edge for a length, radius
    or diameter, two vertices for a distance, two edges for an angle. ``extent_x`` /
    ``extent_y`` give the view's overall width / height (of ``references`` if given)."""
    import TechDraw

    part_view = _part_view(doc, view)
    _settle([part_view])
    page = _page_of(part_view)
    refs = [references] if isinstance(references, str) else list(references or [])
    if type in ("extent_x", "extent_y"):
        before = set(o.Name for o in doc.Objects)
        TechDraw.makeExtentDim(part_view, refs, 0 if type == "extent_x" else 1)
        dim = next(o for o in doc.Objects
                   if o.Name not in before and o.isDerivedFrom("TechDraw::DrawViewDimension"))
    elif type in _DIMENSION_TYPES:
        if not refs:
            raise HandlerError("pass references, e.g. ['Edge3'] or ['Vertex0', 'Vertex2']")
        dim = doc.addObject("TechDraw::DrawViewDimension", "Dimension")
        dim.Type = _DIMENSION_TYPES[type]
        dim.MeasureType = "Projected"
        dim.References2D = [(part_view, refs)]
        page.addView(dim)
    else:
        raise HandlerError("unknown dimension type %r (use %s, extent_x, extent_y)"
                           % (type, ", ".join(_DIMENSION_TYPES)))
    if label:
        dim.Label = label
    _place(dim, part_view, page, type, refs)
    doc.recompute()
    value = dim.getRawValue()
    if "Invalid" in dim.State or value != value:  # NaN: the references don't fit the type
        raise HandlerError("can't make a %s dimension from %s on %s"
                           % (type, ", ".join(refs) or "the whole view", part_view.Label))
    return {"dimension": dim.Name, "page": page.Name, "value": _round(value),
            "text": dim.getText() if hasattr(dim, "getText") else None}


def export_drawing(page, path, document=None):
    """Write a drawing page: ``.dxf`` (works headless), ``.pdf`` or ``.svg`` (GUI)."""
    doc = _doc(document)
    pg = _obj(doc, page)
    if not pg.isDerivedFrom("TechDraw::DrawPage"):
        raise HandlerError("%s is not a drawing page" % pg.Label)
    ext = os.path.splitext(path)[1].lower()
    doc.recompute()
    if ext == ".dxf":
        import TechDraw
        TechDraw.writeDXFPage(pg, path)
    elif ext in (".pdf", ".svg"):
        if not App.GuiUp:
            raise HandlerError("PDF and SVG export need FreeCAD's GUI (this one is "
                               "headless); .dxf works here")
        import FreeCADGui as Gui
        import TechDrawGui
        pg.ViewObject.show()  # the export renders the page's scene, which needs its view
        Gui.updateGui()
        if ext == ".pdf":
            TechDrawGui.exportPageAsPdf(pg, path)
        else:
            TechDrawGui.exportPageAsSvg(pg, path)
    else:
        raise HandlerError("unsupported extension %r (use .dxf, .pdf or .svg)" % ext)
    return {"path": path, "page": pg.Name, "bytes": os.path.getsize(path)}


HANDLERS = {fn.__name__: fn for fn in [create_drawing, drawing_dimension, export_drawing]}
