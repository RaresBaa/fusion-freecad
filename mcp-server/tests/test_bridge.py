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


def test_press_pull_rejects_curved_faces(freecad):
    freecad.call("new_document", name="PressPullCurved")
    sk = freecad.call("create_sketch", geometry=[{"type": "circle", "center": [0, 0],
                                                   "radius": 5}])
    cyl = freecad.call("pad", sketch=sk["sketch"], length=5)
    topo = freecad.call("get_topology", name=cyl["feature"])
    curved = next(f["name"] for f in topo["faces"] if f["surface"] == "Cylinder")
    with pytest.raises(BridgeError, match="flat faces"):
        freecad.call("press_pull", face="%s:%s" % (cyl["feature"], curved), distance=2)


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
