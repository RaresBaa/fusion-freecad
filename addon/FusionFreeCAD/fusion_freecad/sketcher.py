"""Fusion's sketcher feel: sketcher settings in Fusion mode, and sketch profiles. No Qt.

FreeCAD's sketcher already infers constraints while drawing (auto-constraints) and
turns values typed into the on-view parameters into dimensions, like Fusion. Fusion
mode makes sure those are on and that Esc only cancels the current tool instead of
closing the sketch. Like the navigation style, the user's settings are kept in our
preferences and come back when Fusion mode ends (also after a crash).

Profiles are the closed regions Fusion shades in a sketch: every area bounded by
non-construction edges, with overlapping loops split into separate regions.
`sketcher_gui` draws them.
"""

import json

import FreeCAD as App

from . import prefs

ROOT = "User parameter:BaseApp/Preferences/"
SETTINGS = [  # (group, name, value in Fusion mode), applied and restored in this order
    ("Mod/Sketcher/General", "AutoConstraints", True),
    # FreeCAD 1.1 reads this one from Mod/Sketcher, but only when it changes in
    # Mod/Sketcher/General: set the value first, then the trigger.
    ("Mod/Sketcher", "LeaveSketchWithEscape", False),
    ("Mod/Sketcher/General", "LeaveSketchWithEscape", False),
    ("Mod/Sketcher/Tools", "OnViewParameterVisibility", 1),  # dimensional only
    ("Mod/Sketcher/Snap", "SnapToObjects", True),
]
SAVED = "SavedSketcherSettings"
_KINDS = {bool: ("Boolean", "Bool"), int: ("Integer", "Int")}


def enabled():
    return prefs().GetBool("FusionSketcher", True)


def set_enabled(value):
    prefs().SetBool("FusionSketcher", bool(value))
    if value:
        apply()
    else:
        restore()


def _get(group, name, value):
    """The stored value of that kind, or None if it isn't set."""
    kind, _ = _KINDS[type(value)]
    for k, n, v in group.GetContents() or []:
        if k == kind and n == name:
            return v
    return None


def _set(group, name, value):
    getattr(group, "Set" + _KINDS[type(value)][1])(name, value)


def apply(settings=SETTINGS, root=ROOT, store=None):
    if store is None:
        if not enabled():
            return
        store = prefs()
    saved = json.loads(store.GetString(SAVED, "") or "{}")
    for path, name, value in settings:
        group = App.ParamGet(root + path)
        key = path + "/" + name
        if key not in saved:
            saved[key] = _get(group, name, value)
        _set(group, name, value)
    store.SetString(SAVED, json.dumps(saved))


def restore(settings=SETTINGS, root=ROOT, store=None):
    store = prefs() if store is None else store
    saved = json.loads(store.GetString(SAVED, "") or "{}")
    store.RemString(SAVED)
    for path, name, value in settings:
        key = path + "/" + name
        if key not in saved:
            continue
        group = App.ParamGet(root + path)
        if _get(group, name, value) != value:
            continue  # changed by the user in Fusion mode: keep theirs
        if saved[key] is None:
            getattr(group, "Rem" + _KINDS[type(value)][1])(name)
        else:
            _set(group, name, type(value)(saved[key]))


def _edges(sketch):
    for i, geo in enumerate(sketch.Geometry):
        if not hasattr(geo, "FirstParameter") or sketch.getConstruction(i):
            continue  # points, construction geometry
        yield geo


def signature(sketch):
    """Changes when the profiles may have: a few points along each edge."""
    sig = []
    for geo in _edges(sketch):
        a, b = geo.FirstParameter, geo.LastParameter
        for t in (0, 0.25, 0.5, 0.75, 1):
            p = geo.value(a + (b - a) * t)
            sig.append((round(p.x, 6), round(p.y, 6)))
    return tuple(sig)


def profiles(sketch):
    """The sketch's closed regions as faces, in sketch coordinates (z = 0).

    The edges split a plane larger than the sketch (General Fuse); every piece that
    doesn't reach the plane's border is a region. Dangling edges split nothing.
    """
    import Part

    edges = [geo.toShape() for geo in _edges(sketch)]
    if not edges:
        return []
    box = Part.Compound(edges).BoundBox
    margin = max(box.XLength, box.YLength, 1.0)
    plane = Part.makePlane(box.XLength + 2 * margin, box.YLength + 2 * margin,
                           App.Vector(box.XMin - margin, box.YMin - margin, 0))
    try:
        pieces, _ = plane.generalFuse(edges)
    except Part.OCCError:
        return []
    border = box.XMin - margin / 2
    return [f for f in pieces.Faces if f.BoundBox.XMin > border]
