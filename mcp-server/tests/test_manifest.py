"""addons.json is the source of truth for the add-ons we integrate with; package.xml,
flake.nix and integrations.py must agree with it. (No FreeCAD needed.)"""

import ast
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADDONS = json.loads((REPO / "addons.json").read_text(encoding="utf-8"))["addons"]


def test_manifest_entries_are_complete():
    names = [a["name"] for a in ADDONS]
    assert len(names) == len(set(names))
    for a in ADDONS:
        assert a["set"] in ("required", "recommended", "ui"), a
        assert re.fullmatch(r"[0-9a-f]{40}", a["rev"]), a
        assert a["url"].startswith("https://github.com/"), a
        assert isinstance(a["python"], list), a


def test_package_xml_depends_match():
    root = ET.parse(REPO / "addon" / "FusionFreeCAD" / "package.xml").getroot()
    depends = {e.text: e.attrib.get("optional") == "true"
               for e in root.iter() if e.tag.endswith("depend") and e.get("type") == "addon"}
    assert depends == {a["name"]: a["set"] != "required" for a in ADDONS}


def test_flake_inputs_match():
    flake = (REPO / "flake.nix").read_text(encoding="utf-8")
    inputs = dict(re.findall(r'^\s*([\w-]+) = \{ url = "github:([^"]+)"; flake = false; \};',
                             flake, re.M))
    expected = {}
    for a in ADDONS:
        owner_repo = a["url"].removeprefix("https://github.com/")
        expected[a["name"].replace(".", "-")] = "%s/%s" % (owner_repo, a["rev"])
    assert inputs == expected


def test_integrations_registry_matches():
    source = (REPO / "addon" / "FusionFreeCAD" / "fusion_freecad" / "integrations.py").read_text(
        encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Addon"
                and node.args and isinstance(node.args[0], ast.Constant)):
            names.add(node.args[0].value)
    assert names == {a["name"] for a in ADDONS}
