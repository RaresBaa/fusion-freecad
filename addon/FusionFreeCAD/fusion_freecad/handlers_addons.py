"""RPC handlers that drive other add-ons (Fasteners, Gears, SheetMetal, ...).

These add-ons are built around GUI commands and task panels, so the handlers work the
way a user would: select, run the command, accept its dialog, then set properties.
They need the FreeCAD GUI. See integrations.py for the add-on registry.
"""

import contextlib

import FreeCAD as App

from . import integrations
from .handlers import (HandlerError, _describe, _doc, _mutating, _obj, _shape_summary,
                       _vec)

if App.GuiUp:
    import FreeCADGui as Gui
else:
    Gui = None


def _require_gui():
    if Gui is None:
        raise HandlerError("add-on tools need the FreeCAD GUI (running headless)")


def _require(workbench, command, addon):
    _require_gui()
    if not integrations.ensure_command(workbench, command):
        raise HandlerError("the %s add-on isn't installed (or has no %s command); "
                           "install it with the Addon Manager or scripts/install-addon"
                           % (addon, command))


def _select(doc, refs):
    Gui.Selection.clearSelection()
    for ref in refs or []:
        name, _, sub = ref.partition(":")
        obj = _obj(doc, name)
        if sub:
            Gui.Selection.addSelection(doc.Name, obj.Name, sub)
        else:
            Gui.Selection.addSelection(obj)


def _accept_dialog():
    """Accept whatever task panel the command opened, like pressing OK."""
    if not Gui.Control.activeDialog():
        return False
    dialog = Gui.Control.activeTaskDialog() if hasattr(Gui.Control, "activeTaskDialog") else None
    accept = getattr(dialog, "accept", None)
    if callable(accept):
        accept()
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    return True


def _run(doc, command, selection=None, accept=True):
    if command not in Gui.listCommands():
        raise HandlerError("unknown command %r" % command)
    _select(doc, selection)
    if not Gui.Command.get(command).isActive():
        raise HandlerError("%s isn't available with this selection (%s)"
                           % (command, ", ".join(selection or []) or "nothing selected"))
    before = set(o.Name for o in doc.Objects)
    Gui.runCommand(command, 0)
    Gui.updateGui()
    dialog = _accept_dialog() if accept else bool(Gui.Control.activeDialog())
    doc.recompute()
    Gui.Selection.clearSelection()
    new = [o for o in doc.Objects if o.Name not in before]
    return new, dialog


# ---------------------------------------------------------------------------

def list_addons():
    _require_gui()
    found = {a.name for a in integrations.installed()}
    return {"addons": [{"name": a.name, "installed": a.name in found, "notes": a.notes,
                        "toolbars": [t for t, _ in a.toolbars]}
                       for a in integrations.ADDONS]}


def list_commands(filter="", limit=100):
    """Search registered GUI commands by name or menu text (to use with run_command)."""
    _require_gui()
    needle = filter.lower()
    out = []
    for name in sorted(Gui.listCommands()):
        try:
            info = Gui.Command.get(name).getInfo()
        except Exception:
            continue
        text = (info.get("menuText") or "").replace("&", "")
        if needle in name.lower() or needle in text.lower():
            out.append({"command": name, "text": text})
            if len(out) >= int(limit):
                break
    return {"commands": out}


@_mutating("Run command")
def run_command(doc, command, selection=None, accept_dialog=True):
    _require_gui()
    new, dialog = _run(doc, command, selection, accept_dialog)
    return {"command": command, "dialog_opened": dialog,
            "new_objects": [_describe(o) for o in new]}


# --- Fasteners ---------------------------------------------------------------

@_mutating("Insert fastener")
def insert_fastener(doc, type="ISO4762", diameter=None, length=None, hole=None,
                    position=None, invert=False):
    command = "FS" + type
    _require("FastenersWorkbench", command, "Fasteners")
    new, _ = _run(doc, command, [hole] if hole else None)
    fasteners = [o for o in new if "Diameter" in o.PropertiesList]
    if not fasteners:
        raise HandlerError("%s created no fastener" % command)
    f = fasteners[-1]
    if diameter:
        options = f.getEnumerationsOfProperty("Diameter")
        if diameter not in options:
            raise HandlerError("diameter %r not available for %s; options: %s"
                               % (diameter, type, ", ".join(o for o in options if o != "Auto")))
        f.Diameter = diameter
    if length is not None and "Length" in f.PropertiesList:
        doc.recompute()  # the length list depends on the diameter
        options = f.getEnumerationsOfProperty("Length")
        value = ("%g" % float(length)) if not isinstance(length, str) else length
        if value not in options:
            raise HandlerError("length %s not available for %s %s; options: %s"
                               % (value, type, f.Diameter, ", ".join(options)))
        f.Length = value
    if invert and "Invert" in f.PropertiesList:
        f.Invert = True
    if position is not None and not hole:
        f.Placement.Base = _vec(position, "position")
    doc.recompute()
    result = {"fastener": f.Name, "label": f.Label, "type": type,
              "diameter": str(f.Diameter), "shape": _shape_summary(f.Shape)}
    if "Length" in f.PropertiesList:
        result["length"] = str(f.Length)
    return result


# --- Gears -------------------------------------------------------------------

_GEARS = {"involute": "FCGear_InvoluteGear", "internal": "FCGear_InternalInvoluteGear",
          "rack": "FCGear_InvoluteRack", "bevel": "FCGear_BevelGear",
          "worm": "FCGear_WormGear", "timing": "FCGear_TimingGear",
          "cycloid": "FCGear_CycloidGear", "crown": "FCGear_CrownGear"}


@contextlib.contextmanager
def _no_active_body(doc):
    """Gears (and others) add themselves to the active PartDesign body, fusing with
    whatever is there. Temporarily clear it to get a standalone part."""
    view = Gui.getDocument(doc.Name).ActiveView
    body = view.getActiveObject("pdbody") if hasattr(view, "getActiveObject") else None
    if body is not None:
        view.setActiveObject("pdbody", None)
    try:
        yield
    finally:
        if body is not None:
            view.setActiveObject("pdbody", body)


@_mutating("Create gear")
def create_gear(doc, kind="involute", teeth=None, module=None, height=None,
                position=None, in_body=False):
    command = _GEARS.get(kind)
    if command is None:
        raise HandlerError("kind must be one of: %s" % ", ".join(_GEARS))
    _require("GearWorkbench", command, "Gears")
    if in_body:
        new, _ = _run(doc, command)
    else:
        with _no_active_body(doc):
            new, _ = _run(doc, command)
    if not new:
        raise HandlerError("%s created nothing" % command)
    gear = new[-1]
    for prop, value in (("num_teeth", teeth), ("module", module), ("height", height)):
        if value is not None:
            if prop not in gear.PropertiesList:
                raise HandlerError("%s gears have no %s" % (kind, prop))
            setattr(gear, prop, int(value) if prop == "num_teeth" else float(value))
    if position is not None:
        gear.Placement.Base = _vec(position, "position")
    doc.recompute()
    props = {p: str(getattr(gear, p)) for p in ("num_teeth", "module", "height",
                                                   "pitch_diameter", "addendum_diameter")
             if p in gear.PropertiesList}
    return {"gear": gear.Name, "kind": kind, "properties": props,
            "shape": _shape_summary(gear.Shape)}


# --- Sheet metal -------------------------------------------------------------

@_mutating("Sheet metal base")
def sheet_metal_base(doc, sketch, thickness=None, radius=None):
    _require("SMWorkbench", "SheetMetal_AddBase", "SheetMetal")
    new, _ = _run(doc, "SheetMetal_AddBase", [sketch])
    base = next((o for o in new if "Thickness" in o.PropertiesList), None)
    if base is None:
        raise HandlerError("SheetMetal created no base wall from %s" % sketch)
    if thickness is not None:
        base.Thickness = float(thickness)
    if radius is not None:
        base.Radius = float(radius)
    doc.recompute()
    return {"feature": base.Name, "thickness": str(base.Thickness),
            "shape": _shape_summary(base.Shape)}


@_mutating("Sheet metal flange")
def sheet_metal_flange(doc, edges, length=None, angle=None, radius=None):
    _require("SMWorkbench", "SheetMetal_AddWall", "SheetMetal")
    if isinstance(edges, str):
        edges = [edges]
    new, _ = _run(doc, "SheetMetal_AddWall", edges)
    wall = next((o for o in new if "length" in o.PropertiesList), None)
    if wall is None:
        raise HandlerError("SheetMetal created no wall on %s" % ", ".join(edges))
    for prop, value in (("length", length), ("angle", angle), ("radius", radius)):
        if value is not None:
            setattr(wall, prop, float(value))
    doc.recompute()
    return {"feature": wall.Name, "length": str(wall.length), "angle": str(wall.angle),
            "shape": _shape_summary(wall.Shape)}


@_mutating("Sheet metal unfold")
def sheet_metal_unfold(doc, face=None, base=None):
    _require("SMWorkbench", "SheetMetal_Unfold", "SheetMetal")
    if face is None:
        if base is None:
            raise HandlerError("pass face='Bend:Face3' (the face to keep flat) or base=")
        obj = _obj(doc, base)
        planar = [(f.Area, i) for i, f in enumerate(obj.Shape.Faces, 1)
                  if type(f.Surface).__name__ == "Plane"]
        if not planar:
            raise HandlerError("%s has no flat face to unfold from" % obj.Name)
        face = "%s:Face%d" % (obj.Name, max(planar)[1])
    new, _ = _run(doc, "SheetMetal_Unfold", [face])
    flat = next((o for o in new if "KFactor" in o.PropertiesList), None)
    if flat is None:
        raise HandlerError("SheetMetal created no flat pattern from %s" % face)
    return {"flat_pattern": flat.Name, "from_face": face, "shape": _shape_summary(flat.Shape)}


HANDLERS = {fn.__name__: fn for fn in [
    list_addons, list_commands, run_command, insert_fastener, create_gear,
    sheet_metal_base, sheet_metal_flange, sheet_metal_unfold,
]}
