"""RPC handlers for PartDesign features beyond the basics: draft and text (Fusion:
Draft, Text + Extrude)."""

import glob
import os

import FreeCAD as App

from .handlers import (HandlerError, _body_of, _feature_result, _hide, _mutating, _obj,
                       _reference, _resolve_body, _vec)

V = App.Vector


def _faces_of_one_feature(doc, faces):
    if isinstance(faces, str):
        faces = [faces]
    feature, subs = None, []
    for ref in faces:
        name, _, sub = str(ref).partition(":")
        obj = _obj(doc, name)
        if not sub.startswith("Face"):
            raise HandlerError("faces look like 'Pad:Face3', got %r" % ref)
        if feature is not None and obj is not feature:
            raise HandlerError("all faces must come from the same feature")
        feature = obj
        subs.append(sub)
    if feature is None:
        raise HandlerError("pass faces=['Pad:Face3', ...]")
    body = _body_of(feature)
    if body is None:
        raise HandlerError("%s is not in a PartDesign body" % feature.Label)
    return body, feature, subs


@_mutating("Draft")
def draft(doc, faces, angle, neutral_plane, pull_direction=None, reversed=False,
          label=None):
    """Tilt side faces by ``angle`` degrees (Fusion: Draft), for moulding or printing.
    They pivot on ``neutral_plane`` (a plane or planar face); the pull direction is its
    normal unless ``pull_direction`` (an edge) is given."""
    body, feature, subs = _faces_of_one_feature(doc, faces)
    feat = body.newObject("PartDesign::Draft", "Draft")
    if label:
        feat.Label = label
    feat.Base = (feature, subs)
    feat.Angle = float(angle)
    obj, sub = _reference(doc, body, neutral_plane)
    feat.NeutralPlane = (obj, sub)
    if pull_direction:
        obj, sub = _reference(doc, body, pull_direction)
        feat.PullDirection = (obj, sub)
    feat.Reversed = bool(reversed)
    doc.recompute()
    return _feature_result(feat, body)


# Text

_FONT_DIRS = [
    r"C:\Windows\Fonts",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
    "/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.local/share/fonts"),
    os.path.expanduser("~/.fonts"), "/run/current-system/sw/share/X11/fonts",
    "/System/Library/Fonts", "/Library/Fonts",
]


def _bundled_font():
    return os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Resources", "fonts",
                        "osifont-lgpl3fe.ttf")


def _font(font):
    """A font file path, or a font file's name ('arial', 'DejaVuSans') looked up in the
    usual font folders. Default: osifont, which FreeCAD ships."""
    if not font:
        path = _bundled_font()
        if os.path.isfile(path):
            return path
        raise HandlerError("no default font found; pass font= (a .ttf path or name)")
    if os.path.isfile(font):
        return font
    wanted = os.path.splitext(os.path.basename(font))[0].lower()
    for folder in _FONT_DIRS:
        if not os.path.isdir(folder):
            continue
        for path in glob.glob(os.path.join(folder, "**", "*.*"), recursive=True):
            stem, ext = os.path.splitext(os.path.basename(path))
            if ext.lower() in (".ttf", ".otf", ".ttc") and stem.lower() == wanted:
                return path
    raise HandlerError("font %r not found; pass a .ttf path" % font)


@_mutating("Text")
def text(doc, text, on="XY", depth=1.0, size=5.0, position=None, font=None,
         body=None, label=None):
    """Text on a face or plane, raised (``depth`` > 0) or cut in (< 0), centred on the
    face (or the plane's origin) plus ``position`` [x, y] in its own coordinates."""
    import Draft

    if not str(text).strip():
        raise HandlerError("text is empty")
    if not depth:
        raise HandlerError("depth must not be 0: positive embosses, negative engraves")
    name, _, sub = str(on).partition(":")
    body_obj = _body_of(_obj(doc, name)) if sub else _resolve_body(doc, body)
    if body_obj is None:
        raise HandlerError("%s is not in a PartDesign body" % name)
    support, subs = _reference(doc, body_obj, on)
    shape = Draft.make_shapestring(String=str(text), FontFile=_font(font), Size=float(size))
    body_obj.addObject(shape)
    shape.Justification = "Middle-Center"
    shape.AttachmentSupport = [(support, subs[0])]
    shape.MapMode = "FlatFace"
    shape.recompute()
    if "Invalid" in shape.State:
        raise HandlerError("can't put text on %s: pick a planar face or a plane" % on)
    centre = V()
    if subs[0]:  # a face: centre on it, in the text's own frame
        face = support.Shape.getElement(subs[0])
        centre = shape.Placement.inverse().multVec(face.CenterOfMass)
        centre.z = 0
    if position is not None:
        centre += _vec(position, "position")
    shape.AttachmentOffset = App.Placement(centre, App.Rotation())
    _hide(shape)
    type_id = "PartDesign::Pad" if depth > 0 else "PartDesign::Pocket"
    feat = body_obj.newObject(type_id, "Text")
    feat.Label = label or ("Text %s" % text)
    feat.Profile = shape
    feat.Length = abs(float(depth))
    doc.recompute()
    out = _feature_result(feat, body_obj)
    out["shape_string"] = shape.Name
    return out


HANDLERS = {fn.__name__: fn for fn in [draft, text]}
