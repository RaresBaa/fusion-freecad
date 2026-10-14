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
