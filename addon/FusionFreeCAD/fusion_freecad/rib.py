"""Rib: a thin wall grown from an open sketch profile until it meets the solid.

FreeCAD has no rib feature, so this is a ``PartDesign::FeatureAdditivePython``. Each
open wire of the profile is swept away from itself into a ribbon, the ribbon is
thickened, and the part of it between the profile and the solid is kept:

- ``Parallel to sketch``: the ribbon lies in the sketch plane (a gusset); the
  thickness is split about the sketch plane.
- ``Normal to sketch``: the ribbon leaves the sketch plane (a wall standing on a
  floor); the thickness is split about the profile.

Of the two ways to sweep, the one that is stopped by the solid wins (the smaller one
if both are); ``Reversed`` takes the other.
"""

import FreeCAD as App
import Part

V = App.Vector
MODES = ["Parallel to sketch", "Normal to sketch"]


class RibError(Exception):
    pass


def _slab(wire, direction, normal, thickness, mode, reach):
    """The profile swept ``reach`` along ``direction``, ``thickness`` thick."""
    if mode == MODES[0]:  # a ribbon in the sketch plane, thickened across it
        ribbon = wire.extrude(direction * reach)
        return ribbon.translated(normal * (-thickness / 2)).extrude(normal * thickness)
    # The profile widened in the sketch plane (sharp corners, square ends), then pushed out
    outline = wire.makeOffset2D(thickness / 2, 2, False, False, False)
    return Part.Face(outline).extrude(direction * reach)


def _pieces(base, wire, direction, normal, thickness, mode, reach):
    """The bits of the slab outside ``base`` that touch the profile, their volume, and
    whether ``base`` stopped them before the slab's far end."""
    slab = _slab(wire, direction, normal, thickness, mode, reach)
    keep = [s for s in slab.cut(base).Solids if s.distToShape(wire)[0] < 1e-6]
    start = wire.Vertexes[0].Point.dot(direction)
    far = max((v.Point.dot(direction) - start for s in keep for v in s.Vertexes),
              default=reach)
    return keep, sum(s.Volume for s in keep), far < reach * 0.99


def rib_shape(base, profile, normal, thickness, mode=MODES[0], reversed=False):
    """The rib solids for ``profile`` (wires, in body coordinates) against ``base``."""
    if thickness <= 0:
        raise RibError("thickness must be positive")
    wires = profile.Wires
    if not wires or any(w.isClosed() for w in wires):
        raise RibError("a rib needs an open profile (lines or arcs that don't close); "
                       "pad a closed one")
    reach = base.BoundBox.DiagonalLength * 2 + profile.BoundBox.DiagonalLength
    solids = []
    for wire in wires:
        if mode == MODES[0]:
            chord = wire.Vertexes[-1].Point - wire.Vertexes[0].Point
            if chord.Length < 1e-6:
                raise RibError("the profile's ends meet; can't tell which side the rib goes")
            direction = normal.cross(chord).normalize()
        else:
            direction = V(normal)
        tries = []
        for sign in (1, -1):
            keep, volume, stopped = _pieces(base, wire, direction * sign, normal,
                                            thickness, mode, reach)
            tries.append((not stopped, volume, keep))
        tries.sort(key=lambda t: t[:2])
        if tries[0][0]:
            raise RibError("the rib doesn't reach the solid on either side of the profile")
        unbounded, _, keep = tries[1] if reversed else tries[0]
        if unbounded or not keep:
            raise RibError("the rib doesn't reach the solid on the reversed side")
        solids += keep
    return Part.makeCompound(solids)


class Rib:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "Profile", "Rib", "Sketch with open profiles")
        obj.addProperty("App::PropertyLength", "Thickness", "Rib", "Wall thickness")
        obj.addProperty("App::PropertyEnumeration", "Mode", "Rib",
                        "Grow the rib in the sketch plane or out of it")
        obj.addProperty("App::PropertyBool", "Reversed", "Rib",
                        "Grow towards the other side of the profile")
        obj.Mode = MODES
        obj.Thickness = 2.0
        obj.Proxy = self

    def execute(self, obj):
        if obj.BaseFeature is None or obj.BaseFeature.Shape.isNull():
            raise RibError("a rib needs a solid before it in the body")
        if obj.Profile is None:
            raise RibError("no profile sketch")
        base = obj.BaseFeature.Shape
        normal = obj.Profile.Placement.Rotation.multVec(V(0, 0, 1))
        tool = rib_shape(base, obj.Profile.Shape, normal, obj.Thickness.Value, obj.Mode,
                         obj.Reversed)
        result = base.fuse(tool).removeSplitter()
        if len(result.Solids) != 1:
            raise RibError("the rib doesn't touch the solid")
        obj.AddSubShape = tool
        obj.Shape = result.Solids[0]

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderRib:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return ":/icons/PartDesign_Pad.svg"

    def claimChildren(self):
        profile = self.Object.Profile
        return [profile] if profile else []

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make_rib(body, profile, thickness, mode=MODES[0], reversed=False, name="Rib"):
    feat = body.newObject("PartDesign::FeatureAdditivePython", name)
    Rib(feat)
    feat.Profile = profile
    feat.Thickness = thickness
    feat.Mode = mode
    feat.Reversed = reversed
    if App.GuiUp:
        ViewProviderRib(feat.ViewObject)
    return feat
