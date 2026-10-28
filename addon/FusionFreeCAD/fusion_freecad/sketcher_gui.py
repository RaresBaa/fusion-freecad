"""Shaded sketch profiles while a sketch is being edited, like Fusion's.

`update()` runs from the Fusion mode poll: it rebuilds the shading when the sketch's
edges change (`sketcher.signature`) and drops it when the edit ends. The shading is a
transparent, unpickable Coin node in the 3D view's scene graph, placed with the
sketch's global placement and pulled slightly towards the camera so a face the sketch
sits on doesn't hide it.
"""

import FreeCADGui as Gui

from . import prefs, sketcher

COLOR = (0.38, 0.62, 0.95)
TRANSPARENCY = 0.75
TOLERANCE = 0.05  # tessellation, mm

_shown = None  # (view, node, sketch name, signature)


def enabled():
    return prefs().GetBool("ShadeProfiles", True)


def set_enabled(value):
    prefs().SetBool("ShadeProfiles", bool(value))
    if not value:
        clear()


def _node(sketch, faces):
    from pivy import coin

    root = coin.SoSeparator()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    material = coin.SoMaterial()
    material.diffuseColor.setValue(*COLOR)
    material.transparency.setValue(TRANSPARENCY)
    offset = coin.SoPolygonOffset()
    offset.factor.setValue(-1)
    offset.units.setValue(-1)
    placement = sketch.getGlobalPlacement()
    transform = coin.SoTransform()
    transform.translation.setValue(placement.Base.x, placement.Base.y, placement.Base.z)
    transform.rotation.setValue(*placement.Rotation.Q)
    for node in (pick, light, material, offset, transform):
        root.addChild(node)

    points, index = [], []
    for face in faces:
        verts, triangles = face.tessellate(TOLERANCE)
        base = len(points)
        points += [(v.x, v.y, v.z) for v in verts]
        for a, b, c in triangles:
            index += [base + a, base + b, base + c, -1]
    if points:
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(points), points)
        mesh = coin.SoIndexedFaceSet()
        mesh.coordIndex.setValues(0, len(index), index)
        root.addChild(coords)
        root.addChild(mesh)
    return root


def clear():
    global _shown
    if _shown is None:
        return
    view, node = _shown[:2]
    _shown = None
    try:
        view.getSceneGraph().removeChild(node)
    except Exception:
        pass  # the view was closed


def _sketch_in_edit():
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc is not None else None
    if vp is None or vp.Object.TypeId != "Sketcher::SketchObject":
        return None, None
    return gdoc.ActiveView, vp.Object


def update():
    global _shown
    view, sketch = _sketch_in_edit() if enabled() else (None, None)
    if sketch is None or not hasattr(view, "getSceneGraph"):
        clear()
        return
    key = (sketch.FullName, sketch.getGlobalPlacement().toMatrix().A,
           sketcher.signature(sketch))
    if _shown is not None and _shown[0] is view and _shown[2:] == key:
        return
    clear()
    try:
        node = _node(sketch, sketcher.profiles(sketch))
    except Exception as e:  # not again until the sketch changes
        import FreeCAD as App
        App.Console.PrintWarning("Fusion FreeCAD: can't shade profiles: %s\n" % e)
        node = _node(sketch, [])
    view.getSceneGraph().addChild(node)
    _shown = (view, node) + key
