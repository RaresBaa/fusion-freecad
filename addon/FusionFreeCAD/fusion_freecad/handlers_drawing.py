"""RPC handlers for 2D drawings (Fusion: Drawing; FreeCAD: TechDraw): a page with a
projection group of standard views, dimensions on them, and export to DXF / PDF / SVG.

View geometry is named like TechDraw names it: ``Edge0``, ``Vertex0`` (from 0, unlike
3D shapes). ``get_topology`` on a view lists it, in model millimetres.
"""

import glob
import os

import FreeCAD as App

from .handlers import HandlerError, _doc, _mutating, _obj, _round

VIEWS = ["Front", "Rear", "Top", "Bottom", "Left", "Right", "FrontTopLeft",
         "FrontTopRight", "FrontBottomLeft", "FrontBottomRight"]
_VIEW_ALIASES = {"isometric": "FrontTopRight", "iso": "FrontTopRight", "back": "Rear"}
_DEFAULT_TEMPLATE = {"first": "A4_Landscape_TD", "third": "ANSIB_Landscape"}
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
    if scale:
        group.ScaleType = "Custom"
        group.Scale = float(scale)
    else:
        group.ScaleType = "Automatic"
    for v in wanted:
        group.addProjection(v)
    doc.recompute()
    return {"page": page.Name, "template": template_path, "scale": _round(group.Scale),
            "group": group.Name, "views": {v.Type: v.Name for v in group.Views}}


def view_topology(view, max_items=300):
    """A drawing view's visible edges and vertices, in model mm in the view's 2D frame
    (``get_topology`` on a view)."""
    scale = view.getScale() if hasattr(view, "getScale") else view.Scale
    scale = scale or 1.0

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


@_mutating("Dimension")
def drawing_dimension(doc, view, type, references=None, label=None):
    """A dimension on a drawing view. ``references`` are the view's ``Edge0`` /
    ``Vertex0`` names (see ``get_topology`` on the view): one edge for a length, radius
    or diameter, two vertices for a distance, two edges for an angle. ``extent_x`` /
    ``extent_y`` give the view's overall width / height (of ``references`` if given)."""
    import TechDraw

    part_view = _part_view(doc, view)
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
