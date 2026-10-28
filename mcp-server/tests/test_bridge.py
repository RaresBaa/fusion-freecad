"""End-to-end tests: real FreeCAD (headless) <- RPC bridge <- client."""

import json
import math
import socket

import pytest

from fusion_freecad_mcp.client import BridgeError


def test_ping(freecad):
    info = freecad.call("ping")
    assert info["gui"] is False
    assert info["protocol"] == 1
    assert info["freecad_version"].startswith("1.")


def test_bracket_workflow(freecad, tmp_path):
    freecad.call("new_document", name="Bracket")

    sk = freecad.call("create_sketch", plane="XY", geometry=[
        {"type": "rectangle", "center": [0, 0], "width": 40, "height": 20}])
    assert sk["solver_ok"]
    assert len(sk["geometry_indices"][0]) == 4

    base = freecad.call("pad", sketch=sk["sketch"], length=5)
    assert "errors" not in base
    assert base["shape"]["volume"] == pytest.approx(40 * 20 * 5)

    # Find the top face and drill two holes through it.
    topo = freecad.call("get_topology", name=base["feature"])
    top = next(f for f in topo["faces"]
               if f.get("normal") == [0, 0, 1] and f["center"][2] == pytest.approx(5))
    holes = freecad.call("create_sketch", face="%s:%s" % (base["feature"], top["name"]),
                         geometry=[{"type": "circle", "center": [-12, 0], "radius": 2},
                                   {"type": "circle", "center": [12, 0], "radius": 2}])
    cut = freecad.call("pocket", sketch=holes["sketch"], through_all=True)
    assert "errors" not in cut
    expected = 40 * 20 * 5 - 2 * math.pi * 2 ** 2 * 5
    assert cut["shape"]["volume"] == pytest.approx(expected, rel=1e-6)

    # Round the four vertical corner edges.
    topo = freecad.call("get_topology", name=cut["feature"])
    vertical = [e["name"] for e in topo["edges"]
                if e["curve"] in ("Line", "LineSegment")
                and e["start"][:2] == e["end"][:2]
                and abs(e["start"][0]) == pytest.approx(20)]
    assert len(vertical) == 4
    rounded = freecad.call("fillet", edges=vertical, radius=3)
    assert "errors" not in rounded
    assert rounded["shape"]["volume"] < expected

    step = tmp_path / "bracket.step"
    exported = freecad.call("export", path=str(step))
    assert step.stat().st_size > 1000
    assert exported["format"] == "step"

    # One tool call = one undo step.
    undone = freecad.call("undo")
    assert undone["undone"] == ["Fillet"]
    body = freecad.call("get_object", name=rounded["body"])
    assert body["tip"] == cut["feature"]


def test_revolve(freecad):
    freecad.call("new_document", name="Knob")
    sk = freecad.call("create_sketch", plane="XZ", geometry=[
        {"type": "rectangle", "corner": [0, 0], "width": 10, "height": 4}])
    rev = freecad.call("revolve", sketch=sk["sketch"], axis="V")
    assert "errors" not in rev
    assert rev["shape"]["volume"] == pytest.approx(math.pi * 10 ** 2 * 4, rel=1e-6)


def test_set_property_recomputes(freecad):
    freecad.call("new_document", name="Param")
    sk = freecad.call("create_sketch", geometry=[{"type": "circle", "center": [0, 0],
                                                   "radius": 5}])
    feat = freecad.call("pad", sketch=sk["sketch"], length=10)
    freecad.call("set_property", name=feat["feature"], property="Length", value=20)
    info = freecad.call("get_object", name=feat["feature"])
    assert info["shape"]["volume"] == pytest.approx(math.pi * 25 * 20, rel=1e-6)


def test_midplane(freecad):
    freecad.call("new_document", name="Midplane")
    sk = freecad.call("create_sketch", geometry=[
        {"type": "rectangle", "center": [0, 0], "width": 20, "height": 20}])
    pad = freecad.call("pad", sketch=sk["sketch"], length=10, midplane=True)
    assert pad["shape"]["bound_box"]["min"][2] == pytest.approx(-5)
    assert pad["shape"]["bound_box"]["max"][2] == pytest.approx(5)
    # A symmetric pocket on XZ cuts 3 mm to each side of the plane, all inside the block.
    sk = freecad.call("create_sketch", plane="XZ", geometry=[
        {"type": "rectangle", "center": [0, 0], "width": 4, "height": 4}])
    cut = freecad.call("pocket", sketch=sk["sketch"], length=6, midplane=True)
    assert cut["shape"]["volume"] == pytest.approx(20 * 20 * 10 - 4 * 4 * 6)


def _plate_with_hole(freecad, name):
    """Pad (40x20x5) -> Pocket (through hole) -> Fillet; returns the feature names."""
    freecad.call("new_document", name=name)
    sk = freecad.call("create_sketch", geometry=[
        {"type": "rectangle", "center": [0, 0], "width": 40, "height": 20}])
    base = freecad.call("pad", sketch=sk["sketch"], length=5)
    hole = freecad.call("create_sketch", plane="XY", offset=5, geometry=[
        {"type": "circle", "center": [0, 0], "radius": 3}])
    cut = freecad.call("pocket", sketch=hole["sketch"], through_all=True)
    rounded = freecad.call("fillet", edges="all", radius=0.5)
    return base["feature"], cut["feature"], rounded["feature"]


def test_timeline_rollback_and_insert(freecad):
    pad_name, pocket_name, fillet_name = _plate_with_hole(freecad, "Timeline")

    tl = freecad.call("get_timeline")
    assert [e["kind"] for e in tl["entries"]] == ["sketch", "feature", "sketch", "feature",
                                                  "feature"]
    assert tl["tip"] == fillet_name
    assert not any(e["rolled_back"] for e in tl["entries"])
    # Each profile sketch shares its feature's slot in the timeline widget.
    assert [e["owner"] for e in tl["entries"]] == [pad_name, None, pocket_name, None, None]

    # Step back past the fillet and the pocket.
    rolled = freecad.call("roll_timeline", steps=-2)
    assert rolled["tip"] == pad_name
    tl = freecad.call("get_timeline")
    assert [e["rolled_back"] for e in tl["entries"]] == [False, False, True, True, True]
    body = freecad.call("get_object", name=tl["body"])
    assert body["shape"]["volume"] == pytest.approx(40 * 20 * 5)

    # A feature added now goes in at the marker, before the pocket.
    boss = freecad.call("create_sketch", plane="XY", offset=5, geometry=[
        {"type": "circle", "center": [12, 0], "radius": 2}])
    freecad.call("pad", sketch=boss["sketch"], length=3)
    order = [e["name"] for e in freecad.call("get_timeline")["entries"]]
    assert order.index("Pad001") < order.index(pocket_name)

    freecad.call("roll_timeline", to="end")
    tl = freecad.call("get_timeline")
    assert tl["tip"] == fillet_name
    assert not any(e["rolled_back"] or e["error"] for e in tl["entries"])

    freecad.call("roll_timeline", to="start")
    assert freecad.call("get_timeline")["tip"] is None
    freecad.call("roll_timeline", to=pocket_name)
    assert freecad.call("get_timeline")["tip"] == pocket_name


def test_move_feature(freecad):
    base = _block(freecad, "Reorder", height=5)
    hole_sk = freecad.call("create_sketch", offset=9, geometry=[
        {"type": "circle", "center": [0, 0], "radius": 3}])["sketch"]
    hole = freecad.call("pocket", sketch=hole_sk, through_all=True)["feature"]
    boss_sk = _hole_sketch(freecad, base, [[0, 0]], radius=5)
    boss = freecad.call("pad", sketch=boss_sk, length=4)["feature"]
    plate, boss_vol, hole_area = 40 * 20 * 5, math.pi * 25 * 4, math.pi * 9
    # The hole came first, so it doesn't go through the boss.
    assert freecad.call("get_object", name=boss)["shape"]["volume"] \
        == pytest.approx(plate - hole_area * 5 + boss_vol, rel=1e-6)

    # Move the hole (and its sketch) to the end: now it cuts the boss too.
    m = freecad.call("move_feature", name=hole, after="end")
    assert m["moved"] and m["order"][-2:] == [hole_sk, hole]
    assert m["tip"] == hole  # was at the end, stays at the end
    assert m["shape"]["volume"] == pytest.approx(plate - hole_area * 9 + boss_vol, rel=1e-6)
    assert not any(o["valid"] is False for o in freecad.call("list_objects")["objects"])

    # And back before the boss, with the marker rolled back to the plate.
    freecad.call("roll_timeline", to=base)
    m = freecad.call("move_feature", name=hole, before=boss_sk)
    assert m["order"].index(hole) < m["order"].index(boss_sk)
    assert m["tip"] == base
    freecad.call("roll_timeline", to="end")

    # The boss's sketch sits on the plate's top face: it can't go before the plate.
    with pytest.raises(BridgeError, match="built on"):
        freecad.call("move_feature", name=boss, after="start")
    with pytest.raises(BridgeError, match="uses"):
        freecad.call("move_feature", name=boss_sk, after="end", with_sketch=False)
    assert freecad.call("move_feature", name=boss, after=boss)["moved"] is False


def test_timeline_groups(freecad, tmp_path):
    base = _block(freecad, "Groups", height=5)
    holes = []
    for x in (-12, 0, 12):
        sk = _hole_sketch(freecad, base, [[x, 0]])
        holes.append(freecad.call("pocket", sketch=sk, through_all=True)["feature"])
    g = freecad.call("group_timeline", first=holes[0], last=holes[1], name="Holes")
    order = [e["name"] for e in freecad.call("get_timeline")["entries"]]
    # Widened to whole slots: the first hole's sketch comes along.
    assert g["group"]["members"] == order[order.index(holes[0]) - 1:order.index(holes[1]) + 1]
    assert g["group"]["collapsed"] is False
    with pytest.raises(BridgeError, match="overlaps"):
        freecad.call("group_timeline", first=holes[1], last=holes[2])
    with pytest.raises(BridgeError, match="already"):
        freecad.call("group_timeline", first=holes[2], last=holes[2], name="Holes")

    # Moving a feature into the run makes it a member; moving one out drops it.
    freecad.call("move_feature", name=holes[2], before=holes[1])
    t = freecad.call("get_timeline")
    assert {e["name"]: e["group"] for e in t["entries"]}[holes[2]] == "Holes"
    freecad.call("move_feature", name=holes[0], after="end")
    t = freecad.call("get_timeline")
    groups = {e["name"]: e["group"] for e in t["entries"]}
    assert groups[holes[0]] is None and groups[holes[1]] == "Holes"

    e = freecad.call("edit_timeline_group", name="Holes", new_name="Bores", collapsed=True)
    assert [(x["name"], x["collapsed"]) for x in e["groups"]] == [("Bores", True)]
    freecad.call("undo")
    assert freecad.call("get_timeline")["groups"][0]["name"] == "Holes"

    # Deleting a member just shrinks the group; groups survive save and reopen.
    freecad.call("delete_object", name=holes[1])
    path = tmp_path / "groups.FCStd"
    freecad.call("save_document", path=str(path))
    freecad.call("close_document", document="Groups")
    freecad.call("open_document", path=str(path))
    (g,) = freecad.call("get_timeline")["groups"]
    assert holes[2] in g["members"] and holes[1] not in g["members"]
    assert freecad.call("edit_timeline_group", name="Holes", ungroup=True)["groups"] == []

def test_suppress_feature(freecad):
    pad_name, pocket_name, _ = _plate_with_hole(freecad, "Suppress")
    freecad.call("suppress_feature", name=pocket_name)
    entry = next(e for e in freecad.call("get_timeline")["entries"]
                 if e["name"] == pocket_name)
    assert entry["suppressed"]
    freecad.call("suppress_feature", name=pocket_name, suppressed=False)
    with pytest.raises(BridgeError, match="can't be suppressed"):
        freecad.call("suppress_feature", name="Sketch")


def _face(freecad, feature, normal):
    topo = freecad.call("get_topology", name=feature)
    return "%s:%s" % (feature, next(f["name"] for f in topo["faces"]
                                    if f.get("normal") == normal))


def test_press_pull(freecad):
    freecad.call("new_document", name="PressPull")
    sk = freecad.call("create_sketch", geometry=[
        {"type": "rectangle", "corner": [0, 0], "width": 20, "height": 10}])
    base = freecad.call("pad", sketch=sk["sketch"], length=5)

    pulled = freecad.call("press_pull", face=_face(freecad, base["feature"], [0, 0, 1]),
                          distance=3)
    assert "errors" not in pulled
    assert pulled["shape"]["volume"] == pytest.approx(20 * 10 * 8)
    assert pulled["shape"]["bound_box"]["max"][2] == pytest.approx(8)
    # Refine merges the new block into the old one: still a plain box.
    assert pulled["shape"]["faces"] == 6

    pushed = freecad.call("press_pull", face=_face(freecad, pulled["feature"], [1, 0, 0]),
                          distance=-4)
    assert pushed["shape"]["volume"] == pytest.approx(16 * 10 * 8)

    with pytest.raises(BridgeError, match="distance must not be zero"):
        freecad.call("press_pull", face=_face(freecad, pushed["feature"], [1, 0, 0]),
                     distance=0)


def _cylinder_face(freecad, feature, radius):
    topo = freecad.call("get_topology", name=feature)
    return "%s:%s" % (feature, next(f["name"] for f in topo["faces"]
                                    if f.get("radius") == pytest.approx(radius)
                                    and f["surface"] in ("Cylinder", "Toroid")))


def test_press_pull_cylinder_boss_and_pocket_hole(freecad):
    freecad.call("new_document", name="PressPullBoss")
    sk = freecad.call("create_sketch", geometry=[{"type": "circle", "center": [0, 0],
                                                   "radius": 5}])
    cyl = freecad.call("pad", sketch=sk["sketch"], length=10)["feature"]
    # Positive adds material: a boss gets bigger.
    r = freecad.call("press_pull", face=_cylinder_face(freecad, cyl, 5), distance=1)
    assert r["feature"] == cyl and r["radius"] == {"from": 5, "to": 6}
    assert r["shape"]["volume"] == pytest.approx(math.pi * 36 * 10, rel=1e-6)
    # The sketch's diameter dimension changed, so the model stays editable.
    dims = freecad.call("get_object", name=sk["sketch"])["sketch"]["constraints"]
    assert any(c["type"] == "Diameter" and c["value"] == pytest.approx(12) for c in dims)

    holes = _hole_sketch(freecad, cyl, [[0, 0]], radius=2)
    pocket = freecad.call("pocket", sketch=holes, through_all=True)["feature"]
    # ...and a hole gets smaller.
    r = freecad.call("press_pull", face=_cylinder_face(freecad, pocket, 2), distance=0.5)
    assert r["feature"] == pocket and r["radius"]["to"] == pytest.approx(1.5)
    assert r["shape"]["volume"] == pytest.approx(math.pi * (36 - 2.25) * 10, rel=1e-6)
    r = freecad.call("press_pull", face=_cylinder_face(freecad, pocket, 1.5), radius=3)
    assert r["shape"]["volume"] == pytest.approx(math.pi * (36 - 9) * 10, rel=1e-6)
    with pytest.raises(BridgeError, match="radius -"):
        freecad.call("press_pull", face=_cylinder_face(freecad, pocket, 3), distance=5)
    with pytest.raises(BridgeError, match="radius= is for cylindrical faces"):
        freecad.call("press_pull", face=_face(freecad, pocket, [0, 0, 1]), radius=2)


def test_press_pull_fillet_and_hole(freecad):
    base = _block(freecad, "PressPullFillet")
    sk = _hole_sketch(freecad, base, [[10, 0]], radius=2)
    hole = freecad.call("hole", sketch=sk, through_all=True, cut="counterbore",
                        cut_diameter=8, cut_depth=2)["feature"]
    r = freecad.call("press_pull", face=_cylinder_face(freecad, hole, 2), distance=-1)
    assert r["feature"] == hole and r["radius"]["to"] == pytest.approx(3)
    r = freecad.call("press_pull", face=_cylinder_face(freecad, hole, 4), radius=5)
    assert r["radius"] == {"from": 4, "to": 5}
    assert freecad.call("get_object", name=hole)["properties"]["HoleCutDiameter"] \
        .startswith("10")

    topo = freecad.call("get_topology", name=hole)
    vertical = [e["name"] for e in topo["edges"] if e["curve"] in ("Line", "LineSegment")
                and e["start"][:2] == e["end"][:2] and abs(e["start"][0]) == pytest.approx(20)]
    fillet = freecad.call("fillet", edges=vertical, radius=3)
    # Outside fillet: adding material makes it sharper.
    r = freecad.call("press_pull", face=_cylinder_face(freecad, fillet["feature"], 3),
                     distance=1)
    assert r["feature"] == fillet["feature"] and r["radius"]["to"] == pytest.approx(2)
    assert r["shape"]["volume"] > fillet["shape"]["volume"]

    # A threaded hole's size comes from the thread, so it can't be dragged.
    freecad.call("roll_timeline", to="end")
    tapped = freecad.call("hole", sketch=_hole_sketch(freecad, fillet["feature"],
                                                      [[-10, 0]], radius=2),
                          thread="M6", through_all=True)["feature"]
    with pytest.raises(BridgeError, match="thread size"):
        freecad.call("press_pull", face=_cylinder_face(freecad, tapped, 3.3), distance=1)


def test_press_pull_sign_flip_and_rollback(freecad):
    """The live tool flips Pad <-> Pocket and must leave history intact."""
    freecad.call("new_document", name="PressPullFlip")
    pad_name, pocket_name, fillet_name = _plate_with_hole(freecad, "PressPullFlip2")
    freecad.call("roll_timeline", to=pad_name)
    out = freecad.call("run_python", code="""
from fusion_freecad.presspull import PressPull
from fusion_freecad import history
pad = doc.getObject(%r)
top = next("Face%%d" %% i for i, f in enumerate(pad.Shape.Faces, 1)
           if f.Surface.__class__.__name__ == "Plane" and f.normalAt(0, 0).z > 0.99)
op = PressPull(pad, top)
seen = []
for d in (2, -1, 0, 3):
    op.set_distance(d)
    doc.recompute()
    seen.append((op.feature.TypeId if op.feature else None, op.body.Tip.Name))
history.roll_to_end(op.body)
doc.recompute()
result = {"seen": seen, "order": [o.Name for o in op.body.Group], "new": op.feature.Name,
          "invalid": [o.Name for o in doc.Objects if "Invalid" in o.State]}
""" % pad_name)["result"]
    types = [t for t, _ in out["seen"]]
    assert types == ["PartDesign::Pad", "PartDesign::Pocket", None, "PartDesign::Pad"]
    # At zero the feature is gone and the tip falls back to the original pad.
    assert out["seen"][2][1] == pad_name
    order = out["order"]
    assert order.index(pad_name) < order.index(out["new"]) < order.index(pocket_name)
    assert not out["invalid"]


def test_press_pull_handle_frame(freecad):
    """The drag arrow sits on the face and points where a positive distance moves it."""
    base = _block(freecad, "PressPullHandle")
    hole = freecad.call("pocket", sketch=_hole_sketch(freecad, base, [[10, 0]], radius=2),
                        through_all=True)["feature"]
    out = freecad.call("run_python", code="""
from fusion_freecad.presspull import start, handle_frame
def frame(feature, face):
    op = start(doc.getObject(feature), face)
    point, normal = handle_frame(op.face, op.base.Shape)
    return [list(point), list(normal)]
result = {name: frame(*name.split(":")) for name in %r}
""" % [_face(freecad, hole, [0, 0, 1]), _face(freecad, hole, [1, 0, 0]),
       _cylinder_face(freecad, hole, 2)])["result"]
    (top, side, bore) = out.values()
    # The top face has a hole in it, which pulls its centre of mass off the middle.
    assert top[1] == pytest.approx([0, 0, 1]) and top[0][2] == pytest.approx(10)
    assert side == [pytest.approx([20, 0, 5]), pytest.approx([1, 0, 0])]
    # In a hole the arrow points at the axis: pulling makes the hole smaller. It sits
    # on the rim, where it can be seen, not halfway down.
    (x, y, z), (nx, ny, nz) = bore
    assert math.hypot(x - 10, y) == pytest.approx(2) and z == pytest.approx(10)
    assert nz == pytest.approx(0) and nx * (x - 10) + ny * y == pytest.approx(-2)

    # A blind hole's rim is its open end, not its bottom, even when that's the lower
    # end (drilled from below); a boss's is its top.
    blind = freecad.call("pocket", sketch=_hole_sketch(freecad, hole, [[-10, 0]], radius=1.5),
                         length=4)["feature"]
    under = freecad.call("create_sketch", face=_face(freecad, blind, [0, 0, -1]), geometry=[
        {"type": "circle", "center": [0, 5], "radius": 1}])["sketch"]
    from_below = freecad.call("pocket", sketch=under, length=4)["feature"]
    boss = freecad.call("pad", sketch=_hole_sketch(freecad, from_below, [[0, 0]], radius=3),
                        length=5)["feature"]
    out = freecad.call("run_python", code="""
from fusion_freecad.presspull import start, handle_frame
result = []
for feature, face in %r:
    op = start(doc.getObject(feature), face)
    result.append(handle_frame(op.face, op.base.Shape)[0].z)
""" % [_cylinder_face(freecad, blind, 1.5).split(":"),
       _cylinder_face(freecad, from_below, 1).split(":"),
       _cylinder_face(freecad, boss, 3).split(":")])["result"]
    assert out == [pytest.approx(10), pytest.approx(0), pytest.approx(15)]


def test_sketch_profiles(freecad):
    """Fusion's profiles: overlapping loops split into regions, holes left open,
    construction and dangling lines ignored."""
    freecad.call("new_document", name="Profiles")
    sketch = freecad.call("create_sketch", geometry=[
        {"type": "circle", "center": [0, 0], "radius": 10},
        {"type": "circle", "center": [12, 0], "radius": 10},
        {"type": "rectangle", "corner": [40, -10], "width": 20, "height": 20},
        {"type": "circle", "center": [50, 0], "radius": 3},
        {"type": "line", "start": [-30, -30], "end": [-20, -30]},
        {"type": "circle", "center": [0, 30], "radius": 5, "construction": True}])["sketch"]
    out = freecad.call("run_python", code="""
from fusion_freecad import sketcher
sk = doc.getObject(%r)
before = sketcher.signature(sk)
result = {"areas": sorted(round(f.Area, 1) for f in sketcher.profiles(sk))}
sk.moveGeometry(1, 3, App.Vector(13, 0, 0))
result["changed"] = sketcher.signature(sk) != before
""" % sketch)["result"]
    lens = 2 * (100 * math.acos(0.6) - 6 * 8)
    crescent = math.pi * 100 - lens
    assert out["areas"] == sorted(round(a, 1) for a in
                                  [lens, crescent, crescent, 400 - 9 * math.pi, 9 * math.pi])
    assert out["changed"]


def test_sketcher_settings_saved_and_restored(freecad):
    """Fusion mode sets the sketcher settings and puts the user's back afterwards:
    unset ones are removed again, ones the user changed meanwhile are kept."""
    out = freecad.call("run_python", code="""
import FreeCAD as App
from fusion_freecad import sketcher
root = "User parameter:BaseApp/Preferences/Mod/FusionFreeCAD/TestSketcher/"
settings = [("A", "Esc", False), ("A", "Auto", True), ("B", "Ovp", 1), ("B", "Snap", True)]
a, b = App.ParamGet(root + "A"), App.ParamGet(root + "B")
store = App.ParamGet(root + "Store")
a.SetBool("Esc", True)
b.SetInt("Ovp", 2)
sketcher.apply(settings, root, store)
sketcher.apply(settings, root, store)  # again (crash leftover): originals stay
inside = (a.GetContents(), b.GetContents())
b.SetBool("Snap", False)  # the user turns snapping off in Fusion mode
sketcher.restore(settings, root, store)
result = {"inside": [sorted(c) for c in inside],
          "after": [sorted(a.GetContents() or []), sorted(b.GetContents() or [])],
          "saved": store.GetString(sketcher.SAVED, "")}
App.ParamGet("User parameter:BaseApp/Preferences/Mod/FusionFreeCAD").RemGroup("TestSketcher")
""")["result"]
    assert out["inside"] == [[["Boolean", "Auto", True], ["Boolean", "Esc", False]],
                             [["Boolean", "Snap", True], ["Integer", "Ovp", 1]]]
    assert out["after"] == [[["Boolean", "Esc", True]],
                            [["Boolean", "Snap", False], ["Integer", "Ovp", 2]]]
    assert out["saved"] == ""


def _block(freecad, name, width=40, depth=20, height=10):
    """A centred width x depth x height box; returns its Pad's name."""
    freecad.call("new_document", name=name)
    sk = freecad.call("create_sketch", geometry=[
        {"type": "rectangle", "center": [0, 0], "width": width, "height": depth}])
    return freecad.call("pad", sketch=sk["sketch"], length=height)["feature"]


def _hole_sketch(freecad, base, centers, radius=1):
    return freecad.call("create_sketch", face=_face(freecad, base, [0, 0, 1]), geometry=[
        {"type": "circle", "center": c, "radius": radius} for c in centers])["sketch"]


def test_hole_plain_takes_sketch_diameter(freecad):
    base = _block(freecad, "HolePlain")
    sk = _hole_sketch(freecad, base, [[-10, 0], [10, 0]], radius=3)
    h = freecad.call("hole", sketch=sk, depth=5, flat_bottom=True)
    assert "errors" not in h
    assert h["holes"] == 2 and h["diameter"] == pytest.approx(6)
    assert h["shape"]["volume"] == pytest.approx(8000 - 2 * math.pi * 9 * 5, rel=1e-6)
    # Drilled into the solid, not out of the top.
    assert h["shape"]["bound_box"]["max"][2] == pytest.approx(10)


def test_hole_thread_presets(freecad):
    base = _block(freecad, "HoleThread")
    sk = _hole_sketch(freecad, base, [[0, 0]])
    clearance = freecad.call("hole", sketch=sk, thread="M6", through_all=True)
    assert clearance["thread"] == "ISOMetricProfile M6x1.0"
    assert clearance["diameter"] == pytest.approx(6.6)  # medium fit clearance
    assert clearance["shape"]["volume"] == pytest.approx(8000 - math.pi * 3.3 ** 2 * 10,
                                                         rel=1e-6)

    freecad.call("undo")
    tapped = freecad.call("hole", sketch=sk, thread="M6", tapped=True, through_all=True,
                          cut="counterbore")
    assert tapped["diameter"] == pytest.approx(5.0)  # tap drill
    assert tapped["cut"]["type"] == "Counterbore" and tapped["cut"]["diameter"] > 6

    freecad.call("undo")
    fine = freecad.call("hole", sketch=sk, thread="M8x1.0", through_all=True)
    assert fine["thread"] == "ISOMetricFineProfile M8x1.0"
    freecad.call("undo")
    unc = freecad.call("hole", sketch=sk, thread="UNC 1/4", through_all=True)
    assert unc["thread"] == "UNC 1/4"

    with pytest.raises(BridgeError, match="unknown thread size"):
        freecad.call("hole", sketch=sk, thread="M7.3")
    with pytest.raises(BridgeError, match="no circles"):
        freecad.call("hole", sketch="Sketch")


def test_shell(freecad):
    base = _block(freecad, "Shell")
    top = _face(freecad, base, [0, 0, 1]).split(":")[1]
    inward = freecad.call("shell", faces=[top], thickness=1)
    assert "errors" not in inward
    assert inward["shape"]["volume"] == pytest.approx(8000 - 38 * 18 * 9, rel=1e-6)
    assert inward["shape"]["bound_box"]["max"][0] == pytest.approx(20)

    freecad.call("undo")
    outward = freecad.call("shell", faces=[top], thickness=1, outward=True)
    assert outward["shape"]["bound_box"]["max"][0] == pytest.approx(21)


def _boss(freecad, base, center, radius=2, height=5):
    sk = freecad.call("create_sketch", face=_face(freecad, base, [0, 0, 1]), geometry=[
        {"type": "circle", "center": center, "radius": radius}])
    return freecad.call("pad", sketch=sk["sketch"], length=height)["feature"]


def test_mirror(freecad):
    base = _block(freecad, "Mirror")
    boss = _boss(freecad, base, [12, 0])
    one_boss = 8000 + math.pi * 4 * 5
    m = freecad.call("mirror", plane="YZ")
    assert "errors" not in m
    assert m["shape"]["volume"] == pytest.approx(one_boss + math.pi * 4 * 5, rel=1e-6)
    assert m["shape"]["solids"] == 1

    freecad.call("undo")
    m = freecad.call("mirror", plane="XY", whole_body=True)
    assert m["shape"]["bound_box"]["min"][2] == pytest.approx(-15)
    assert m["shape"]["volume"] == pytest.approx(2 * one_boss, rel=1e-6)

    freecad.call("undo")
    # Mirror across a face of the solid: the boss copied below the bottom face.
    bottom = _face(freecad, base, [0, 0, -1])
    m = freecad.call("mirror", plane=bottom, features=[boss])
    assert m["shape"]["solids"] == 2  # the copy floats below, not touching the body


def test_linear_pattern(freecad):
    base = _block(freecad, "Linear", width=60)
    _boss(freecad, base, [-25, -5], radius=1)
    boss_volume = math.pi * 5
    p = freecad.call("linear_pattern", direction="X", count=6, spacing=10)
    assert "errors" not in p
    assert p["shape"]["volume"] == pytest.approx(60 * 20 * 10 + 6 * boss_volume, rel=1e-6)

    freecad.call("undo")
    grid = freecad.call("linear_pattern", direction="X", count=3, length=40,
                        direction2="Y", count2=2, spacing2=10)
    assert grid["shape"]["volume"] == pytest.approx(60 * 20 * 10 + 6 * boss_volume, rel=1e-6)
    assert grid["shape"]["bound_box"]["max"][1] == pytest.approx(10)

    with pytest.raises(BridgeError, match="spacing= .* or length="):
        freecad.call("linear_pattern", direction="X", count=3)


def test_polar_pattern(freecad):
    freecad.call("new_document", name="Polar")
    disc = freecad.call("create_sketch", geometry=[{"type": "circle", "center": [0, 0],
                                                    "radius": 20}])
    base = freecad.call("pad", sketch=disc["sketch"], length=5)["feature"]
    holes = _hole_sketch(freecad, base, [[15, 0]], radius=2)
    freecad.call("pocket", sketch=holes, through_all=True)
    p = freecad.call("polar_pattern", count=6)
    assert "errors" not in p
    assert p["shape"]["volume"] == pytest.approx(math.pi * 5 * (400 - 6 * 4), rel=1e-6)

    freecad.call("undo")
    half = freecad.call("polar_pattern", count=3, angle=180, axis="Z")
    assert half["shape"]["volume"] == pytest.approx(math.pi * 5 * (400 - 3 * 4), rel=1e-6)


def test_loft(freecad):
    freecad.call("new_document", name="Loft")
    square = freecad.call("create_sketch", geometry=[
        {"type": "rectangle", "center": [0, 0], "width": 20, "height": 20}])["sketch"]
    small = freecad.call("create_sketch", offset=10, geometry=[
        {"type": "rectangle", "center": [0, 0], "width": 10, "height": 10}])["sketch"]
    lo = freecad.call("loft", sketches=[square, small], ruled=True)
    assert "errors" not in lo
    # Ruled loft between squares = frustum: h/3 (A1 + A2 + sqrt(A1 A2)).
    assert lo["shape"]["volume"] == pytest.approx(10 / 3 * (400 + 100 + 200), rel=1e-6)

    top = freecad.call("create_sketch", offset=10, geometry=[
        {"type": "circle", "center": [0, 0], "radius": 2}])["sketch"]
    bottom = freecad.call("create_sketch", offset=5, geometry=[
        {"type": "circle", "center": [0, 0], "radius": 1}])["sketch"]
    cut = freecad.call("loft", sketches=[top, bottom], cut=True, ruled=True)
    assert "errors" not in cut
    cone = math.pi * 5 / 3 * (4 + 1 + 2)
    assert cut["shape"]["volume"] == pytest.approx(lo["shape"]["volume"] - cone, rel=1e-6)

    with pytest.raises(BridgeError, match="at least two"):
        freecad.call("loft", sketches=[square])


def test_sweep(freecad):
    freecad.call("new_document", name="Sweep")
    profile = freecad.call("create_sketch", geometry=[
        {"type": "circle", "center": [0, 0], "radius": 2}])["sketch"]
    # Path in XZ: straight up 20, then a quarter turn of radius 10.
    path = freecad.call("create_sketch", plane="XZ", geometry=[
        {"type": "line", "start": [0, 0], "end": [0, 20]},
        {"type": "arc", "center": [10, 20], "radius": 10, "start_angle": 90,
         "end_angle": 180}])["sketch"]
    sw = freecad.call("sweep", sketch=profile, path=path)
    assert "errors" not in sw
    assert sw["shape"]["volume"] == pytest.approx(math.pi * 4 * (20 + math.pi * 5), rel=1e-6)

    freecad.call("undo")
    straight = freecad.call("sweep", sketch=profile, path=path + ":Edge1")
    assert straight["shape"]["volume"] == pytest.approx(math.pi * 4 * 20, rel=1e-6)


def test_measure(freecad):
    base = _block(freecad, "Measure")
    hole = freecad.call("hole", sketch=_hole_sketch(freecad, base, [[10, 0]], radius=2),
                        through_all=True)
    feat = hole["feature"]
    top, bottom = _face(freecad, feat, [0, 0, 1]), _face(freecad, feat, [0, 0, -1])
    gap = freecad.call("measure", a=top, b=bottom)
    assert gap["distance"] == pytest.approx(10)
    assert gap["plane_distance"] == pytest.approx(10)
    assert gap["angle"] == pytest.approx(180)

    side = _face(freecad, feat, [1, 0, 0])
    assert freecad.call("measure", a=top, b=side)["angle"] == pytest.approx(90)

    topo = freecad.call("get_topology", name=feat)
    rim = next(e["name"] for e in topo["edges"] if e.get("radius") == pytest.approx(2))
    edge = freecad.call("measure", a="%s:%s" % (feat, rim))
    assert edge["diameter"] == pytest.approx(4)
    # Hole axis at x=10 to the side face at x=20, measured from the rim edge.
    assert freecad.call("measure", a="%s:%s" % (feat, rim), b=side)["distance"] \
        == pytest.approx(8)

    whole = freecad.call("measure", a=feat)
    assert whole["volume"] == pytest.approx(8000 - math.pi * 4 * 10, rel=1e-6)
    with pytest.raises(BridgeError, match="has no Face99"):
        freecad.call("measure", a=feat + ":Face99")


def test_sketch_editing(freecad):
    freecad.call("new_document", name="SketchEdit")
    sk = freecad.call("create_sketch", geometry=[
        {"type": "rectangle", "center": [0, 0], "width": 40, "height": 20},
        {"type": "circle", "center": [0, 0], "radius": 3},
        {"type": "line", "start": [30, 0], "end": [40, 0]}])
    name = sk["sketch"]
    info = freecad.call("get_object", name=name)["sketch"]
    width = next(c["index"] for c in info["constraints"]
                 if c["type"] == "DistanceX" and c["value"] == pytest.approx(40))

    r = freecad.call("set_dimension", sketch=name, constraint=width, value=50, name="width")
    assert r["solver_ok"]
    widths = [c for c in r["sketch_info"]["constraints"] if c["name"] == "width"]
    assert widths[0]["value"] == pytest.approx(50)

    # By name now; the stray line goes, the circle moves.
    freecad.call("delete_sketch_geometry", sketch=name, geometry=[5])
    moved = freecad.call("move_sketch_geometry", sketch=name, index=4, point="center",
                         to=[10, 2])
    circle = moved["sketch_info"]["geometry"][4]
    assert len(moved["sketch_info"]["geometry"]) == 5
    assert circle["center"] == pytest.approx([10, 2])

    pad = freecad.call("pad", sketch=name, length=5)
    assert pad["shape"]["volume"] == pytest.approx((50 * 20 - math.pi * 9) * 5, rel=1e-6)

    with pytest.raises(BridgeError, match="no constraint named 'nope'"):
        freecad.call("set_dimension", sketch=name, constraint="nope", value=1)
    with pytest.raises(BridgeError, match="not a dimension"):
        freecad.call("set_dimension", sketch=name, constraint=0, value=1)


def test_parameters_drive_the_model(freecad):
    freecad.call("new_document", name="Params")
    p = freecad.call("set_parameters", parameters={
        "width": 40, "thickness": "5 mm", "half": "=width / 2", "tilt": "30 deg",
        "count": {"value": 4, "kind": "number"}})
    by_name = {x["name"]: x for x in p["parameters"]}
    assert by_name["half"]["expression"] == "width / 2"
    assert by_name["half"]["value"] == pytest.approx(20) and by_name["half"]["unit"] == "mm"
    assert by_name["tilt"]["value"] == pytest.approx(30) and by_name["tilt"]["unit"] == "deg"
    assert by_name["count"]["value"] == 4 and by_name["count"]["unit"] is None

    sk = freecad.call("create_sketch", geometry=[
        {"type": "rectangle", "corner": [0, 0], "width": 40, "height": 20}])
    info = freecad.call("get_object", name=sk["sketch"])["sketch"]
    width = next(c["index"] for c in info["constraints"] if c["type"] == "DistanceX")
    freecad.call("set_dimension", sketch=sk["sketch"], constraint=width, name="w",
                 expression="Parameters.width")
    pad = freecad.call("pad", sketch=sk["sketch"], length=1)
    e = freecad.call("set_expression", name=pad["feature"], property="Length",
                     expression="Parameters.thickness")
    assert e["value"] == pytest.approx(5)
    assert freecad.call("get_object", name=pad["feature"])["shape"]["volume"] \
        == pytest.approx(40 * 20 * 5)

    # Change a parameter: the sketch and the pad follow.
    freecad.call("set_parameters", parameters={"width": 60, "thickness": 2})
    body = freecad.call("get_object", name=pad["body"])
    assert body["shape"]["volume"] == pytest.approx(60 * 20 * 2)
    exprs = freecad.call("get_parameters")["expressions"]
    assert {"object": sk["sketch"], "property": "Constraints.w",
            "expression": "Parameters.width"} in exprs
    assert next(x for x in freecad.call("get_parameters")["parameters"]
                if x["name"] == "half")["value"] == pytest.approx(30)

    # A plain value replaces an expression.
    freecad.call("set_dimension", sketch=sk["sketch"], constraint="w", value=10)
    assert freecad.call("get_object", name=pad["body"])["shape"]["volume"] \
        == pytest.approx(10 * 20 * 2)

    with pytest.raises(BridgeError, match="reserved"):
        freecad.call("set_parameters", parameters={"Label": 3})
    freecad.call("delete_parameter", name="count")
    assert "count" not in [x["name"] for x in freecad.call("get_parameters")["parameters"]]
    with pytest.raises(BridgeError, match="unit name"):
        freecad.call("set_parameters", parameters={"h": 3})

    # Renaming carries the expressions that use it along.
    freecad.call("set_expression", name=pad["feature"], property="Length",
                 expression="Parameters.width / 20")
    p = freecad.call("rename_parameter", name="width", new_name="plate_width")
    assert next(x for x in p["parameters"] if x["name"] == "half")["expression"]         == "plate_width / 2"
    exprs = freecad.call("get_parameters")["expressions"]
    assert {"object": pad["feature"], "property": "Length",
            "expression": "Parameters.plate_width / 20"} in exprs
    with pytest.raises(BridgeError, match="taken"):
        freecad.call("rename_parameter", name="half", new_name="tilt")


def test_parameter_dialog_helpers(freecad):
    """The Change Parameters dialog's text handling and kind switching."""
    freecad.call("new_document", name="ParamText")
    freecad.call("set_parameters", parameters={"width": 40, "tilt": "30 deg"})
    freecad.call("run_python", code="""
box = doc.addObject("Part::Box", "Box")
box.setExpression("Length", "Parameters.width + 1 mm")
""")
    out = freecad.call("run_python", code="""
from fusion_freecad import parameters as P
vs = P.varset(doc)
r = {"texts": [P.from_text(t) for t in ("40", "30 deg", " width / 2 ", "=width", "")]}
P.set_one(vs, "half", P.from_text("width / 2"))
doc.recompute()
r["half"] = (P.as_text(vs, "half"), P.value_text(vs, "half"))
r["width"] = P.as_text(vs, "width")
P.set_one(vs, "width", {"value": P.from_text("50"), "comment": "outer"})
P.set_kind(vs, "tilt", "number")
r["tilt"] = (P.kind(vs, "tilt"), vs.tilt)
P.set_kind(vs, "tilt", "angle")
r["tilt_back"] = (P.kind(vs, "tilt"), vs.tilt.Value)
P.set_kind(vs, "width", "number")
P.set_kind(vs, "width", "length")
doc.recompute()
r["box"] = (doc.Box.Length.Value, dict(doc.Box.ExpressionEngine), "Invalid" in doc.Box.State)
r["comment"] = vs.getDocumentationOfProperty("width")
r["users"] = [(o.Name, p) for o, p in P.users(doc, "width")]
result = r
""")["result"]
    assert out["texts"] == ["40", "30 deg", "=width / 2", "=width", ""]
    assert out["half"][0] == "width / 2" and out["half"][1].startswith("20")
    assert out["width"].startswith("40")
    assert out["tilt"] == ["number", 30]
    assert out["tilt_back"] == ["angle", 30]
    # Changing a parameter's kind keeps what uses it working.
    assert out["box"] == [51, {"Length": "Parameters.width + 1 mm"}, False]
    assert out["comment"] == "outer"
    assert out["users"] == [["Box", "Length"]]

    # What the dialog's Cancel does: abort, then restore what the abort missed.
    out = freecad.call("run_python", code="""
from fusion_freecad import parameters as P
vs = P.varset(doc)
saved = P.snapshot(vs)
doc.openTransaction("dialog")
P.set_one(vs, "width", P.from_text("20"))
r = {"typed": P.kind(vs, "width")}
P.set_kind(vs, "width", "number")
P.rename(vs, "half", "half_width")
doc.recompute()
doc.abortTransaction()
r["aborted"] = sorted(P.names(vs))
P.restore(vs, saved)
doc.recompute()
r["restored"] = P.snapshot(vs) == saved
r["names"] = sorted(P.names(vs))
r["box"] = doc.Box.Length.Value
result = r
""")["result"]
    assert out["typed"] == "length"  # a unitless value keeps the kind
    assert out["restored"] and out["names"] == ["half", "tilt", "width"]
    assert out["box"] == pytest.approx(51)


def test_combine_and_split_body(freecad):
    pad = _block(freecad, "Bodies")  # 40 x 20 x 10, centred
    first = "Body"
    second = freecad.call("create_body", label="Tool")["body"]
    sk = freecad.call("create_sketch", body=second, geometry=[
        {"type": "rectangle", "corner": [10, -10], "width": 20, "height": 20}])
    freecad.call("pad", sketch=sk["sketch"], length=10)

    c = freecad.call("combine", target=pad, tools=[second], operation="cut")
    assert "errors" not in c and c["body"] == first
    assert c["shape"]["volume"] == pytest.approx(8000 - 10 * 20 * 10)
    with pytest.raises(BridgeError, match="itself"):
        freecad.call("combine", target=first, tools=[first])
    freecad.call("undo")

    s = freecad.call("split_body", body=first, tool="YZ", offset=5)
    assert "errors" not in s
    volumes = sorted(b["shape"]["volume"] for b in s["bodies"])
    assert volumes == pytest.approx([15 * 20 * 10, 25 * 20 * 10])
    # The pieces follow the original body.
    freecad.call("set_property", name=pad, property="Length", value=4)
    volumes = sorted(freecad.call("get_object", name=b["body"])["shape"]["volume"]
                     for b in s["bodies"])
    assert volumes == pytest.approx([15 * 20 * 4, 25 * 20 * 4])
    # A piece takes new features like any body.
    piece = next(b["body"] for b in s["bodies"] if b["shape"]["bound_box"]["min"][0] < 0)
    sk = freecad.call("create_sketch", body=piece, plane="XY", geometry=[
        {"type": "circle", "center": [-15, 0], "radius": 2}])
    p = freecad.call("pad", sketch=sk["sketch"], length=10, reversed=True)
    assert "errors" not in p
    assert p["shape"]["volume"] == pytest.approx(25 * 20 * 4 + math.pi * 4 * 10)

    # Along another body's face: the tool block's side at x = 10.
    other = next(b["body"] for b in s["bodies"] if b["body"] != piece)
    s2 = freecad.call("split_body", body=other, tool=_face(freecad, "Pad001", [-1, 0, 0]))
    assert sorted(b["shape"]["volume"] for b in s2["bodies"]) ==         pytest.approx([5 * 20 * 4, 10 * 20 * 4])

    with pytest.raises(BridgeError, match="doesn't cut"):
        freecad.call("split_body", body=first, tool="YZ", offset=500)


def test_inspect_tools(freecad):
    pad = _block(freecad, "Inspect")  # 40 x 20 x 10 centred on the origin, z 0..10
    c = freecad.call("check_geometry", name="Body")
    assert c["ok"] and c["closed"] and c["problems"] == []
    freecad.call("run_python", code="""
import Part
V = App.Vector
bow = Part.Face(Part.makePolygon([V(0, 0, 0), V(10, 10, 0), V(10, 0, 0), V(0, 10, 0),
                                  V(0, 0, 0)]))
doc.addObject("Part::Feature", "Bow").Shape = bow
""")
    c = freecad.call("check_geometry", name="Bow")
    assert not c["ok"] and not c["valid"] and not c["closed"]
    assert any("Self-intersecting" in p for p in c["problems"])
    freecad.call("delete_object", name="Bow")

    m = freecad.call("mass_properties", name="Body", density=2)
    assert m["volume_mm3"] == pytest.approx(8000)
    assert m["mass_g"] == pytest.approx(16)
    assert m["center_of_mass"] == pytest.approx([0, 0, 5])
    ixx = 16 * (20 ** 2 + 10 ** 2) / 12  # box about its centre: m (b^2 + c^2) / 12
    assert m["inertia_g_mm2"][0][0] == pytest.approx(ixx)
    assert m["inertia_g_mm2"][0][1] == pytest.approx(0, abs=1e-6)
    with pytest.raises(BridgeError, match="no material"):
        freecad.call("mass_properties", name="Body", material="unobtainium")
    s = freecad.call("set_material", name="Body", material="PLA")
    assert s["material"] == "PLA-Generic" and s["density"] == pytest.approx(1.24)
    m = freecad.call("mass_properties", name="Body")
    assert m["density_from"] == "PLA-Generic" and m["mass_g"] == pytest.approx(9.92)

    # A second block overlapping the first by 10 x 20 x 10, and a third just touching.
    for x0 in (10, 30):
        body = freecad.call("create_body", label="B%d" % x0)["body"]
        sk = freecad.call("create_sketch", body=body, geometry=[
            {"type": "rectangle", "corner": [x0, -10], "width": 20, "height": 20}])
        freecad.call("pad", sketch=sk["sketch"], length=10)
    i = freecad.call("interference", include_touching=True)
    assert len(i["parts"]) == 3
    assert [(c["a"], c["b"]) for c in i["interferences"]] == [("Body", "Body001")]
    assert i["interferences"][0]["volume"] == pytest.approx(10 * 20 * 10)
    assert i["interferences"][0]["bound_box"]["min"] == pytest.approx([10, -10, 0])
    assert {"a": "Body001", "b": "Body002"} in i["touching"]
    assert freecad.call("interference", names=["Body", "Body002"])["interferences"] == []


def _edge(freecad, feature, center):
    topo = freecad.call("get_topology", name=feature)
    return "%s:%s" % (feature, next(e["name"] for e in topo["edges"]
                                    if e["center"] == pytest.approx(center)))


def test_construction_geometry(freecad):
    pad = _block(freecad, "Construct")  # 40 x 20 x 10 centred, z 0..10
    cos30, sin30 = math.cos(math.radians(30)), 0.5

    p = freecad.call("datum_plane", on="XY", offset=25)
    assert p["mode"] == "FlatFace"
    assert p["placement"]["base"] == pytest.approx([0, 0, 25])
    assert p["placement"]["axis"] == pytest.approx([0, 0, 1])
    # Sketch on it and pad down to the block: the body grows to z = 25.
    sk = freecad.call("create_sketch", plane=p["feature"], geometry=[
        {"type": "circle", "center": [0, 0], "radius": 3}])
    pad2 = freecad.call("pad", sketch=sk["sketch"], up_to_face=_face(freecad, pad, [0, 0, 1]),
                        reversed=True)
    assert "errors" not in pad2
    assert pad2["shape"]["bound_box"]["max"][2] == pytest.approx(25)

    # Tilted 30 degrees about the top face's back edge (along X at y = 10, z = 10).
    top = _face(freecad, pad, [0, 0, 1])
    edge = _edge(freecad, pad, [0, 10, 10])
    t = freecad.call("datum_plane", on=top, angle=30, about=edge)
    assert abs(t["placement"]["axis"][2]) == pytest.approx(cos30)
    assert abs(t["placement"]["axis"][1]) == pytest.approx(sin30)
    # Still through the edge: its midpoint lies in the plane.
    base, axis = t["placement"]["base"], t["placement"]["axis"]
    assert sum((c - b) * n for c, b, n in zip([0, 10, 10], base, axis))         == pytest.approx(0, abs=1e-5)  # results are rounded to 1e-6
    with pytest.raises(BridgeError, match="lie in the plane"):
        freecad.call("datum_plane", on="XY", angle=10, about=edge)

    three = freecad.call("datum_plane", on=[
        "%s:%s" % (pad, v) for v in ("Vertex1", "Vertex2", "Vertex3")])
    assert three["mode"] == "ThreePointsPlane"

    a = freecad.call("datum_axis", through=["XY", "YZ"])
    assert a["mode"] == "IntersectionLine"
    assert [abs(c) for c in a["placement"]["axis"]] == pytest.approx([0, 1, 0])
    a = freecad.call("datum_axis", through=edge)
    assert [abs(c) for c in a["placement"]["axis"]] == pytest.approx([1, 0, 0])
    side = next(f["name"] for f in freecad.call("get_topology", name=pad2["feature"])["faces"]
                if f["surface"] == "Cylinder")
    hole = freecad.call("datum_axis", through="%s:%s" % (pad2["feature"], side))
    assert hole["mode"] == "AxisOfCurvature"
    assert [abs(c) for c in hole["placement"]["axis"]] == pytest.approx([0, 0, 1])

    pt = freecad.call("datum_point", at=top, offset=[0, 0, 5])
    assert pt["point"] == pytest.approx([0, 0, 15])
    pt = freecad.call("datum_point", at="%s:Vertex1" % pad)
    assert pt["mode"] == "Vertex"


def test_sketch_tools(freecad):
    pad = _block(freecad, "SketchTools")  # 40 x 20 x 10 centred, z 0..10
    top = _face(freecad, pad, [0, 0, 1])

    # Project the top face's outline and pad it: the block grows by 5.
    sk = freecad.call("create_sketch", face=top, geometry=[])["sketch"]
    p = freecad.call("project_to_sketch", sketch=sk, elements=[top], defining=True)
    assert len(p["external_indices"]) == 4 and p["external_indices"][0] == -3
    info = freecad.call("get_object", name=sk)["sketch"]
    assert [e["index"] for e in info["external"]] == p["external_indices"]
    grown = freecad.call("pad", sketch=sk, length=5)
    assert "errors" not in grown
    assert grown["shape"]["volume"] == pytest.approx(40 * 20 * 15)

    # Offset a 30 x 20 rectangle outward by 2: padding both makes a 2 mm wall.
    freecad.call("new_document", name="SketchOffset")
    sk = freecad.call("create_sketch", geometry=[
        {"type": "rectangle", "corner": [0, 0], "width": 30, "height": 20}])["sketch"]
    o = freecad.call("offset_sketch", sketch=sk, distance=2)
    assert len(o["geometry_indices"]) == 8 and o["solver_ok"]  # 4 lines, 4 corner arcs
    wall = freecad.call("pad", sketch=sk, length=1)
    outer = 30 * 20 + 2 * 2 * (30 + 20) + math.pi * 2 ** 2
    assert wall["shape"]["volume"] == pytest.approx(outer - 30 * 20)
    sharp = freecad.call("offset_sketch", sketch=sk, distance=-1, geometry=[0, 1, 2, 3],
                         join="intersection")
    assert len(sharp["geometry_indices"]) == 4

    # Round every corner of a rectangle.
    freecad.call("new_document", name="SketchFillet")
    sk = freecad.call("create_sketch", geometry=[
        {"type": "rectangle", "corner": [0, 0], "width": 30, "height": 20}])["sketch"]
    f = freecad.call("fillet_sketch", sketch=sk, radius=3)
    assert len(f["geometry_indices"]) == 4 and f["solver_ok"]
    plate = freecad.call("pad", sketch=sk, length=1)
    assert plate["shape"]["volume"] == pytest.approx(30 * 20 - (4 - math.pi) * 3 ** 2)
    with pytest.raises(BridgeError, match="no corner"):
        freecad.call("fillet_sketch", sketch=sk, radius=1, corners=[[15, 10]])


def test_move_and_copy_body(freecad):
    pad = _block(freecad, "MoveCopy")  # 40 x 20 x 10 centred, z 0..10
    m = freecad.call("move_body", name="Body", translate=[100, 0, 0])
    assert m["shape"]["bound_box"]["min"] == pytest.approx([80, -10, 0])
    # A quarter turn about Z through the body's centre at (100, 0): 20 wide, 40 deep.
    m = freecad.call("move_body", name="Body", axis="Z", angle=90, center=[100, 0, 0])
    assert m["shape"]["bound_box"]["min"] == pytest.approx([90, -20, 0])
    assert m["placement"]["angle"] == pytest.approx(90)

    c = freecad.call("copy_body", name="Body", translate=[0, 100, 0], label="Twin")
    assert c["label"] == "Twin" and not c["linked"]
    assert c["shape"]["bound_box"]["min"] == pytest.approx([90, 80, 0])
    assert c["shape"]["volume"] == pytest.approx(8000)
    # Independent: changing the original leaves the copy alone; a link follows it.
    link = freecad.call("copy_body", name="Body", linked=True, translate=[0, -100, 0])
    freecad.call("set_property", name=pad, property="Length", value=5)
    assert freecad.call("get_object", name=c["name"])["shape"]["volume"]         == pytest.approx(8000)
    assert freecad.call("get_object", name=link["name"])["shape"]["volume"]         == pytest.approx(4000)
    with pytest.raises(BridgeError, match="headless"):
        freecad.call("appearance", name="Body", color="#ff8800")


def test_extrude_options_draft_and_text(freecad):
    freecad.call("new_document", name="ExtrudeOptions")
    rect = [{"type": "rectangle", "corner": [0, 0], "width": 30, "height": 20}]
    sk = freecad.call("create_sketch", geometry=rect)["sketch"]
    p = freecad.call("pad", sketch=sk, length=10, length2=5)
    assert p["shape"]["bound_box"]["min"][2] == pytest.approx(-5)
    assert p["shape"]["volume"] == pytest.approx(30 * 20 * 15)
    with pytest.raises(BridgeError, match="not both"):
        freecad.call("pad", sketch=sk, midplane=True, length2=5)
    freecad.call("undo")
    freecad.call("new_document", name="Taper")
    sk = freecad.call("create_sketch", geometry=rect)["sketch"]
    t = freecad.call("pad", sketch=sk, length=10, taper=10)
    assert "errors" not in t
    assert t["shape"]["bound_box"]["min"][0] < -1  # wider at the top
    assert t["shape"]["volume"] > 30 * 20 * 10

    pad = _block(freecad, "DraftText")  # 40 x 20 x 10 centred, z 0..10
    side = _face(freecad, pad, [-1, 0, 0])
    d = freecad.call("draft", faces=[side], angle=5,
                     neutral_plane=_face(freecad, pad, [0, 0, -1]))
    assert "errors" not in d
    # The left side leans in by 10 * tan(5) at the top: a wedge of 20 mm depth comes off.
    wedge = 0.5 * 10 * 10 * math.tan(math.radians(5)) * 20
    assert d["shape"]["volume"] == pytest.approx(8000 - wedge, rel=1e-4)

    top = _face(freecad, d["feature"], [0, 0, 1])
    raised = freecad.call("text", text="FC", on=top, depth=1, size=6)
    assert "errors" not in raised
    assert raised["shape"]["bound_box"]["max"][2] == pytest.approx(11)
    grown = raised["shape"]["volume"] - d["shape"]["volume"]
    assert 5 < grown < 6 * 6 * 2  # some letters, about 6 mm tall
    top = _face(freecad, raised["feature"], [0, 0, 1])
    cut = freecad.call("text", text="FC", on=_face(freecad, raised["feature"], [0, 0, -1]),
                       depth=-0.5, size=6)
    assert "errors" not in cut
    assert cut["shape"]["volume"] < raised["shape"]["volume"]
    assert cut["shape"]["bound_box"]["min"][2] == pytest.approx(0)
    with pytest.raises(BridgeError, match="font"):
        freecad.call("text", text="x", on=top, font="no-such-font-anywhere")


def test_rib(freecad, tmp_path):
    freecad.call("new_document", name="Rib")
    # An L-bracket in XZ (sketch y is Z), 20 mm deep about the sketch plane.
    l_shape = [{"type": "polygon", "points": [[0, 0], [50, 0], [50, 5], [5, 5], [5, 50],
                                              [0, 50]]}]
    sk = freecad.call("create_sketch", plane="XZ", geometry=l_shape)["sketch"]
    bracket = freecad.call("pad", sketch=sk, length=20, midplane=True)
    gusset = freecad.call("create_sketch", plane="XZ", geometry=[
        {"type": "line", "start": [5, 40], "end": [40, 5]}])["sketch"]
    with pytest.raises(BridgeError, match="other side|reversed side"):
        freecad.call("rib", sketch=gusset, thickness=4, reversed=True)
    r = freecad.call("rib", sketch=gusset, thickness=4)
    assert "errors" not in r
    # The corner triangle (legs 35) between the line and the walls, 4 mm thick.
    assert r["shape"]["volume"] - bracket["shape"]["volume"] == pytest.approx(
        35 * 35 / 2 * 4)
    assert r["shape"]["solids"] == 1
    freecad.call("set_property", name=r["feature"], property="Thickness", value=2)
    assert freecad.call("get_object", name=r["feature"])["shape"]["volume"]         - bracket["shape"]["volume"] == pytest.approx(35 * 35 / 2 * 2)

    # Parametric across save and reopen (the feature is a Python object).
    path = tmp_path / "rib.FCStd"
    freecad.call("save_document", path=str(path))
    freecad.call("close_document", document="Rib")
    freecad.call("open_document", path=str(path))
    freecad.call("set_property", name=r["feature"], property="Thickness", value=4)
    assert "errors" not in freecad.call("recompute")
    assert freecad.call("get_object", name=r["feature"])["shape"]["volume"]         == pytest.approx(r["shape"]["volume"])

    # An open box (60 x 40 x 20, 2 mm walls); an L-shaped wall grows down to the floor.
    freecad.call("new_document", name="RibBox")
    sk = freecad.call("create_sketch", geometry=[
        {"type": "rectangle", "corner": [0, 0], "width": 60, "height": 40}])["sketch"]
    freecad.call("pad", sketch=sk, length=20)
    sk = freecad.call("create_sketch", offset=20, geometry=[
        {"type": "rectangle", "corner": [2, 2], "width": 56, "height": 36}])["sketch"]
    box = freecad.call("pocket", sketch=sk, length=18)
    walls = freecad.call("create_sketch", offset=15, geometry=[
        {"type": "line", "start": [30, 2], "end": [30, 20]},
        {"type": "line", "start": [30, 20], "end": [58, 20]}])["sketch"]
    w = freecad.call("rib", sketch=walls, thickness=2, mode="normal")
    assert "errors" not in w
    assert w["shape"]["volume"] - box["shape"]["volume"] == pytest.approx((18 + 28) * 2 * 13)

    closed = freecad.call("create_sketch", offset=15, geometry=[
        {"type": "polygon", "points": [[10, 10], [20, 10], [20, 20]]}])["sketch"]
    with pytest.raises(BridgeError, match="open profile"):
        freecad.call("rib", sketch=closed, thickness=2)
    with pytest.raises(BridgeError, match="mode"):
        freecad.call("rib", sketch=walls, thickness=2, mode="sideways")

def test_drawing(freecad, tmp_path):
    pad = _block(freecad, "Drawing")  # 40 x 20 x 10, centred on the origin
    freecad.call("hole", sketch=_hole_sketch(freecad, pad, [[0, 0]], radius=3),
                 diameter=6, through_all=True)
    d = freecad.call("create_drawing", objects=["Body"], views=["Top", "iso"])
    assert set(d["views"]) == {"Front", "Top", "FrontTopRight"}
    assert 0 < d["scale"] <= 10
    with pytest.raises(BridgeError, match="unknown view"):
        freecad.call("create_drawing", objects=["Body"], views=["Sideways"])
    with pytest.raises(BridgeError, match="template"):
        freecad.call("create_drawing", objects=["Body"], template="no-such-sheet")

    top = d["views"]["Top"]
    topo = freecad.call("get_topology", name=top)
    assert topo["scale"] == d["scale"]
    circle = next(e for e in topo["edges"] if e.get("radius"))
    assert circle["radius"] == pytest.approx(3)
    long_edge = next(e for e in topo["edges"]
                     if "start" in e and e["length"] == pytest.approx(40))
    assert long_edge["name"].startswith("Edge")

    dia = freecad.call("drawing_dimension", view=top, type="diameter",
                       references=[circle["name"]])
    assert dia["value"] == pytest.approx(6)
    length = freecad.call("drawing_dimension", view=top, type="distance",
                          references=[long_edge["name"]])
    assert length["value"] == pytest.approx(40)
    ends = [v["name"] for v in topo["vertices"]
            if v["point"] in (long_edge["start"], long_edge["end"])]
    assert len(ends) == 2
    apart = freecad.call("drawing_dimension", view=top, type="distance_x", references=ends)
    assert apart["value"] == pytest.approx(40)
    height = freecad.call("drawing_dimension", view=d["views"]["Front"], type="extent_y")
    assert height["value"] == pytest.approx(10)
    with pytest.raises(BridgeError, match="can't make"):
        freecad.call("drawing_dimension", view=top, type="radius",
                     references=[long_edge["name"]])

    out = tmp_path / "drawing.dxf"
    e = freecad.call("export_drawing", page=d["page"], path=str(out))
    assert e["bytes"] > 1000
    with pytest.raises(BridgeError, match="GUI"):
        freecad.call("export_drawing", page=d["page"], path=str(tmp_path / "d.pdf"))

def test_mcp_resources_read_the_model(freecad, monkeypatch):
    import asyncio
    import json

    from fusion_freecad_mcp import server

    monkeypatch.setattr(server, "client", freecad)
    _block(freecad, "Resources")
    freecad.call("set_parameters", parameters={"width": 40})

    def read(uri):
        contents = list(asyncio.run(server.mcp.read_resource(uri)))
        return json.loads(contents[0].content)

    assert "Resources" in [d["name"] for d in read("freecad://documents")["documents"]]
    names = [o["name"] for o in read("freecad://Resources/objects")["objects"]]
    assert "Pad" in names
    assert read("freecad://Resources/timeline")["tip"] == "Pad"
    assert read("freecad://Resources/parameters")["parameters"][0]["name"] == "width"


def test_export_dxf_outline(freecad, tmp_path):
    base = _block(freecad, "Dxf", height=2)
    freecad.call("hole", sketch=_hole_sketch(freecad, base, [[10, 0]], radius=3),
                 through_all=True)
    out = tmp_path / "plate.dxf"
    freecad.call("export", path=str(out))
    lines = [s.strip() for s in out.read_text().splitlines()]
    start = lines.index("ENTITIES")
    lines = lines[start:lines.index("ENDSEC", start)]
    entities = [lines[i + 1] for i, s in enumerate(lines[:-1]) if s == "0"]
    assert entities.count("LINE") == 4 and entities.count("CIRCLE") == 1
    # 2D: one outline at z=0, not the top and bottom of the plate.
    zs = {float(lines[i + 1]) for i, s in enumerate(lines[:-1]) if s == "30"}
    assert zs <= {0.0}
    # The temporary export object is gone again.
    assert not any(o["name"].startswith("DXFExport")
                   for o in freecad.call("list_objects")["objects"])


def _circle_edge(freecad, obj, radius, z):
    topo = freecad.call("get_topology", name=obj)
    return "%s:%s" % (obj, next(e["name"] for e in topo["edges"]
                                if e.get("radius") == pytest.approx(radius)
                                and e["center"][2] == pytest.approx(z)))


def test_assembly_pin_in_plate(freecad):
    freecad.call("new_document", name="Asm")
    plate = freecad.call("create_body", label="Plate")["body"]
    sk = freecad.call("create_sketch", body=plate, geometry=[
        {"type": "rectangle", "center": [0, 0], "width": 40, "height": 20},
        {"type": "circle", "center": [10, 0], "radius": 2}])
    freecad.call("pad", sketch=sk["sketch"], length=5)
    pin = freecad.call("create_body", label="Pin")["body"]
    sk = freecad.call("create_sketch", body=pin, geometry=[
        {"type": "circle", "center": [0, 0], "radius": 2}])
    freecad.call("pad", sketch=sk["sketch"], length=12)

    freecad.call("create_assembly")
    p = freecad.call("insert_part", part=plate)
    assert p["grounded"]  # the first part is grounded, like in Fusion
    q = freecad.call("insert_part", part=pin, position=[50, 30, 7])
    assert not q["grounded"]

    # Seat the pin's bottom rim on the hole's top rim, then 5 mm down into it.
    j = freecad.call("create_joint", type="revolute",
                     a=_circle_edge(freecad, p["part"], 2, 5),
                     b=_circle_edge(freecad, q["part"], 2, 7), offset=[0, 0, -5])
    assert j["solved"], j
    parts = {x["name"]: x for x in j["parts"]}
    assert parts[q["part"]]["position"] == pytest.approx([10, 0, 0])
    assert parts[p["part"]]["position"] == pytest.approx([0, 0, 0])
    assert j["joints"][0]["type"] == "Revolute"

    # The body name works as well as the link's; a fixed joint at the origins with a
    # 90 degree turn.
    freecad.call("delete_object", name=j["joint"])
    f = freecad.call("create_joint", type="Fixed", a=plate, b=pin, rotation=90)
    pin_part = next(x for x in f["parts"] if x["name"] == q["part"])
    assert pin_part["position"] == pytest.approx([0, 0, 0])
    assert pin_part["angle"] == pytest.approx(90)

    info = freecad.call("get_assembly")
    assert [x["grounded"] for x in info["parts"]] == [True, False]
    with pytest.raises(BridgeError, match="type must be one of"):
        freecad.call("create_joint", type="glue", a=plate, b=pin)
    with pytest.raises(BridgeError, match="two different parts"):
        freecad.call("create_joint", type="fixed", a=plate, b=plate + ":Face1")
    with pytest.raises(BridgeError, match="already in"):
        freecad.call("insert_part", part=p["part"])


def test_run_python(freecad):
    out = freecad.call("run_python", code="print('hi')\nresult = {'n': len(App.listDocuments())}")
    assert out["stdout"] == "hi\n"
    assert out["result"]["n"] >= 1


def test_run_python_can_close_its_document(freecad):
    freecad.call("new_document", name="Closing")
    freecad.call("run_python", code="App.closeDocument(doc.Name)")
    names = [d["name"] for d in freecad.call("list_documents")["documents"]]
    assert "Closing" not in names


def test_user_errors_are_reported(freecad):
    freecad.call("new_document", name="Errors")
    with pytest.raises(BridgeError, match="no object 'Nope'"):
        freecad.call("get_object", name="Nope")
    with pytest.raises(BridgeError, match="unknown geometry type"):
        freecad.call("create_sketch", geometry=[{"type": "spline"}])
    # The failed call must not leave a half-made sketch behind.
    names = [o["name"] for o in freecad.call("list_objects")["objects"]]
    assert not any(n.startswith("Sketch") for n in names)


def test_rejects_bad_token(freecad):
    info = freecad._connection_info()
    with socket.create_connection((info["host"], info["port"]), timeout=5) as s:
        s.sendall(b'{"id": 1, "token": "wrong", "method": "ping"}\n')
        reply = json.loads(s.makefile().readline())
    assert reply["error"]["type"] == "AuthError"
