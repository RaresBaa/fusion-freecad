"""Fusion's body tools: Combine (join / cut / intersect bodies) and Split Body.

Both stay parametric: Combine is a PartDesign Boolean in the target body; Split Body
slices the body with a plane attached to the splitting face or plane, and each piece
becomes a new body whose base feature is that piece, so editing the original body
updates the pieces.
"""

import FreeCAD as App

from .rpc import HandlerError

OPERATIONS = {"join": "Fuse", "cut": "Cut", "intersect": "Common"}


class BodyError(HandlerError):
    pass


def _hide(obj):
    if App.GuiUp:
        obj.Visibility = False


def body_of(obj):
    if obj.TypeId == "PartDesign::Body":
        return obj
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def combine(target, tools, operation="join", keep_tools=False):
    """Join, cut or intersect ``tools`` (bodies) with ``target``; returns the Boolean."""
    if operation not in OPERATIONS:
        raise BodyError("operation must be join, cut or intersect")
    tools = list(tools)
    if not tools:
        raise BodyError("pass at least one tool body")
    for tool in tools:
        if tool.TypeId != "PartDesign::Body":
            raise BodyError("%s is a %s, not a body" % (tool.Label, tool.TypeId))
        if tool is target:
            raise BodyError("a body can't be combined with itself")
    if target.Tip is None:
        raise BodyError("%s is empty" % target.Label)
    boolean = target.newObject("PartDesign::Boolean", "Combine")
    boolean.Type = OPERATIONS[operation]
    boolean.addObjects(tools)
    if App.GuiUp:
        for tool in tools:
            tool.Visibility = bool(keep_tools)
    return boolean


def split(body, support, offset=0.0):
    """Split ``body`` by the plane of ``support`` ((object, subelement): a planar face,
    a datum or origin plane), moved ``offset`` mm along its normal. Returns the new
    bodies, one per piece; the original body is hidden."""
    import BOPTools.SplitFeatures as split_features
    import CompoundTools.CompoundFilter as compound_filter

    if body.Shape.isNull() or not body.Shape.Solids:
        raise BodyError("%s has no solid to split" % body.Label)
    doc = body.Document
    size = body.Shape.BoundBox.DiagonalLength * 4
    cutter = doc.addObject("Part::Plane", "SplitPlane")
    cutter.Label = "%s split plane" % body.Label
    cutter.Length = cutter.Width = size
    cutter.AttachmentSupport = [support]
    cutter.MapMode = "FlatFace"
    cutter.AttachmentOffset = App.Placement(App.Vector(-size / 2, -size / 2, float(offset)),
                                            App.Rotation())
    cutter.recompute()
    if "Invalid" in cutter.State or not cutter.Shape.Faces:
        doc.removeObject(cutter.Name)
        raise BodyError("can't split along %s%s: pick a planar face or a plane"
                        % (support[0].Label, "." + support[1] if support[1] else ""))
    sliced = split_features.makeSlice("Split")
    sliced.Label = "%s split" % body.Label
    sliced.Base = body
    sliced.Tools = [cutter]
    sliced.Mode = "Split"
    sliced.recompute()
    count = len(sliced.Shape.Solids)
    if count < 2:
        for obj in (sliced, cutter):
            doc.removeObject(obj.Name)
        raise BodyError("the plane doesn't cut through %s" % body.Label)
    pieces = []
    for i in range(count):
        piece = compound_filter.makeCompoundFilter("SplitPiece")
        piece.Label = "%s piece %d" % (body.Label, i + 1)
        piece.Base = sliced
        piece.FilterType = "specific items"
        piece.items = str(i)
        new_body = doc.addObject("PartDesign::Body", "Body")
        new_body.Label = "%s (%d)" % (body.Label, i + 1)
        new_body.BaseFeature = piece
        pieces.append(new_body)
        _hide(piece)
    for obj in (cutter, sliced, body):
        _hide(obj)
    return pieces
