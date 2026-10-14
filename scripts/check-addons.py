"""Check that the integrated add-ons work in a running FreeCAD (GUI, bridge started).

Run it after changing the pinned commits in addons.json:

    cd mcp-server
    uv run python ../scripts/check-addons.py

It creates scratch documents in FreeCAD and closes them at the end.
"""

import sys
import traceback

from fusion_freecad_mcp.client import BridgeError, FreeCADClient

c = FreeCADClient()
results = []


def check(name):
    def wrap(fn):
        try:
            detail = fn()
            results.append((name, True, detail or ""))
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0] if str(e) else traceback.format_exc(limit=1)
            results.append((name, False, msg))
        return fn
    return wrap


def py(code):
    return c.call("run_python", code=code)["result"]


info = c.call("ping")
if not info["gui"]:
    sys.exit("FreeCAD is running headless; these checks need the GUI.")
installed = {a["name"] for a in c.call("list_addons")["addons"] if a["installed"]}
docs = []


def new_doc(name):
    docs.append(c.call("new_document", name=name)["document"])


@check("Fusion toolbars include add-on groups")
def _():
    bars = py("from PySide import QtWidgets\n"
              "result = sorted(t.objectName() for t in Gui.getMainWindow()"
              ".findChildren(QtWidgets.QToolBar) if t.isVisible())")
    wanted = {"fasteners": "Fasteners", "sheetmetal": "Sheet Metal",
              "freecad.gears": "Gears", "FusedFilamentDesign": "3D Print"}
    missing = [bar for addon, bar in wanted.items() if addon in installed and bar not in bars]
    assert not missing, "missing toolbars: %s (in the Fusion workbench?)" % missing
    return "%d toolbars visible" % len(bars)


@check("SearchBar first-use patch")
def _():
    if "SearchBar" not in installed:
        return "not installed"
    state = py("import inspect, ResultsToolbar\n"
               "result = 'workbench.name()' not in inspect.getsource(ResultsToolbar.getAllToolbars)")
    assert state, "SearchBar's getAllToolbars is unpatched"
    return "patched (or fixed upstream)"


@check("Fasteners: screw into a hole")
def _():
    new_doc("CheckFasteners")
    sk = c.call("create_sketch", geometry=[{"type": "rectangle", "center": [0, 0],
                                            "width": 30, "height": 20}])
    c.call("pad", sketch=sk["sketch"], length=6)
    hole = c.call("create_sketch", plane="XY", offset=6,
                  geometry=[{"type": "circle", "center": [0, 0], "radius": 2.25}])
    pk = c.call("pocket", sketch=hole["sketch"], through_all=True)
    edge = next(e["name"] for e in c.call("get_topology", name=pk["feature"])["edges"]
                if e.get("radius") == 2.25 and abs(e["center"][2] - 6) < 1e-6)
    s = c.call("insert_fastener", type="ISO4762", diameter="M4", length=10,
               hole="%s:%s" % (pk["feature"], edge))
    bb = s["shape"]["bound_box"]
    assert abs((bb["min"][0] + bb["max"][0]) / 2) < 0.1, "screw not centred on the hole"
    return "%s %s" % (s["label"], s["shape"]["volume"])


@check("Gears: standalone involute gear")
def _():
    g = c.call("create_gear", teeth=20, module=1, height=5, position=[60, 0, 0])
    assert g["shape"]["solids"] == 1, "gear merged into another body"
    assert g["properties"]["pitch_diameter"].startswith("20"), g["properties"]
    return "pitch diameter %s" % g["properties"]["pitch_diameter"]


@check("SheetMetal: base, flange, unfold")
def _():
    new_doc("CheckSheetMetal")
    sk = c.call("create_sketch", geometry=[{"type": "rectangle", "corner": [0, 0],
                                            "width": 60, "height": 30}])
    base = c.call("sheet_metal_base", sketch=sk["sketch"], thickness=1)
    edge = next(e["name"] for e in c.call("get_topology", name=base["feature"])["edges"]
                if e["curve"] in ("Line", "LineSegment") and e["length"] == 60
                and e["start"][2] == 1 and e["start"][1] == 0)
    wall = c.call("sheet_metal_flange", edges=["%s:%s" % (base["feature"], edge)], length=15)
    flat = c.call("sheet_metal_unfold", base=wall["feature"])
    dims = flat["shape"]["bound_box"]
    thickness = dims["max"][2] - dims["min"][2]
    assert abs(thickness - 1) < 1e-6, "flat pattern isn't flat"
    return "flat pattern %.1f x %.1f" % (dims["max"][0] - dims["min"][0],
                                         dims["max"][1] - dims["min"][1])


@check("FusedFilamentDesign via run_command")
def _():
    if "FusedFilamentDesign" not in installed:
        return "not installed"
    new_doc("CheckFFD")
    sk = c.call("create_sketch", geometry=[{"type": "rectangle", "center": [0, 0],
                                            "width": 20, "height": 20}])
    p = c.call("pad", sketch=sk["sketch"], length=10)
    r = c.call("run_command", command="ffDesign_AutoFillet", selection=[p["feature"]])
    assert r["new_objects"] and all(o["valid"] for o in r["new_objects"])
    return r["new_objects"][0]["type"]


@check("Still in the Fusion workbench")
def _():
    wb = py("result = Gui.activeWorkbench().name()")
    assert wb == "FusionWorkbench", wb
    return wb


for d in docs:
    try:
        c.call("close_document", document=d)
    except BridgeError:
        pass

width = max(len(name) for name, _, _ in results)
for name, ok, detail in results:
    print("%s  %s  %s" % ("PASS" if ok else "FAIL", name.ljust(width), detail))
print("\nInstalled add-ons: %s" % ", ".join(sorted(installed)))
sys.exit(0 if all(ok for _, ok, _ in results) else 1)
