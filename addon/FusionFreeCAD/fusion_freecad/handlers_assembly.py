"""RPC handlers for assemblies, on FreeCAD 1.x's built-in Assembly workbench.

An assembly is an ``Assembly::AssemblyObject`` holding ``App::Link``s to the parts
(bodies elsewhere in the document) and a ``Joints`` group. Joints are the Assembly
workbench's own Python objects (``JointObject.Joint``) so they behave exactly like
ones made in the GUI; the workbench's solver then moves the parts. A joint refers to
an element of a part as ``[link, [sub, sub]]``: the element and the point on it used
as the joint's origin (the same element means its centre).
"""

import math

import FreeCAD as App

from .handlers import HandlerError, _doc, _mutating, _obj, _round, _vec, _vec_out

if App.GuiUp:
    import FreeCADGui as Gui
else:
    Gui = None

# Joints between two parts that need no extra inputs (RackPinion, Screw, Gears and
# Belt also need ratios; use run_python for those).
_JOINT_TYPES = ["Fixed", "Revolute", "Cylindrical", "Slider", "Ball", "Distance",
                "Parallel", "Perpendicular", "Angle"]


def _joint_module():
    try:
        import JointObject
    except ImportError as e:
        raise HandlerError("FreeCAD's Assembly workbench isn't available: %s" % e)
    return JointObject


def _assemblies(doc):
    return [o for o in doc.Objects if o.isDerivedFrom("Assembly::AssemblyObject")]


def _assembly(doc, name=None):
    if name:
        obj = _obj(doc, name)
        if not obj.isDerivedFrom("Assembly::AssemblyObject"):
            raise HandlerError("%r is a %s, not an assembly" % (name, obj.TypeId))
        return obj
    found = _assemblies(doc)
    if len(found) == 1:
        return found[0]
    if not found:
        raise HandlerError("document has no assembly; call create_assembly first")
    raise HandlerError("document has several assemblies (%s); pass assembly="
                       % ", ".join(a.Name for a in found))


def _joint_group(asm):
    for o in asm.Group:
        if o.TypeId == "Assembly::JointGroup":
            return o
    return asm.newObject("Assembly::JointGroup", "Joints")


def _parts(asm):
    # The group also holds the joint group and helper objects without a placement.
    return [o for o in asm.Group if o.TypeId != "Assembly::JointGroup"
            and "Placement" in o.PropertiesList and not hasattr(o, "JointType")]


def _joints(asm):
    return [j for j in _joint_group(asm).Group if hasattr(j, "JointType")]


def _grounded(asm):
    return [j.ObjectToGround for j in _joint_group(asm).Group
            if hasattr(j, "ObjectToGround")]


def _part(asm, name):
    """A part of the assembly by its own name/label, or by the body it links to."""
    doc = asm.Document
    parts = _parts(asm)
    obj = _obj(doc, name)
    if obj in parts:
        return obj
    linking = [p for p in parts if getattr(p, "LinkedObject", None) is obj]
    if len(linking) == 1:
        return linking[0]
    if linking:
        raise HandlerError("%s is in the assembly several times (%s); use one of those"
                           % (obj.Name, ", ".join(p.Name for p in linking)))
    raise HandlerError("%s is not part of %s; call insert_part first" % (obj.Name, asm.Name))


def _placement_out(plc):
    rot = plc.Rotation
    return {"position": _vec_out(plc.Base), "axis": _vec_out(rot.Axis),
            "angle": _round(math.degrees(rot.Angle))}


def _rotation(axis, angle):
    if not angle:
        return App.Rotation()
    return App.Rotation(_vec(axis or [0, 0, 1], "rotation_axis"), float(angle))


def _summary(asm):
    grounded = _grounded(asm)
    parts = [dict({"name": p.Name, "label": p.Label,
                   "part": getattr(getattr(p, "LinkedObject", None), "Name", None),
                   "grounded": p in grounded}, **_placement_out(p.Placement))
             for p in _parts(asm)]
    joints = []
    for j in _joints(asm):
        refs = []
        for ref in (j.Reference1, j.Reference2):
            if ref:
                sub = ref[1][0] if ref[1] else ""
                refs.append("%s:%s" % (ref[0].Name, sub) if sub else ref[0].Name)
        joints.append({"name": j.Name, "label": j.Label, "type": j.JointType,
                       "between": refs, "suppressed": bool(getattr(j, "Suppressed", False))})
    return {"assembly": asm.Name, "parts": parts, "joints": joints}


def _solve(asm):
    status = asm.solve()
    asm.Document.recompute()
    result = _summary(asm)
    result["solved"] = status == 0
    if status != 0:
        result["solver_status"] = status
    return result


@_mutating("Create assembly")
def create_assembly(doc, label="Assembly"):
    asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
    asm.Label = label
    asm.Type = "Assembly"
    asm.newObject("Assembly::JointGroup", "Joints")
    return {"assembly": asm.Name, "label": asm.Label}


@_mutating("Insert part")
def insert_part(doc, part, assembly=None, position=None, rotation_axis=None,
                rotation_angle=0.0, ground=None, label=None):
    asm = _assembly(doc, assembly)
    source = _obj(doc, part)
    if source in _parts(asm) or source is asm:
        raise HandlerError("%s is already in %s" % (source.Name, asm.Name))
    if not hasattr(source, "Shape"):
        raise HandlerError("%s has no shape to assemble" % source.Name)
    link = asm.newObject("App::Link", source.Name)
    link.LinkedObject = source
    link.Label = label or source.Label
    link.Placement = App.Placement(_vec(position or [0, 0, 0], "position"),
                                   _rotation(rotation_axis, rotation_angle))
    if Gui:
        source.Visibility = False  # the link shows it now
    if ground is None:
        ground = not _grounded(asm)  # like Fusion: the first component is grounded
    if ground:
        joint_module = _joint_module()
        g = _joint_group(asm).newObject("App::FeaturePython", "GroundedJoint")
        joint_module.GroundedJoint(g, link)
        if Gui:
            joint_module.ViewProviderGroundedJoint(g.ViewObject)
    doc.recompute()
    return {"part": link.Name, "label": link.Label, "assembly": asm.Name,
            "grounded": bool(ground)}


def _connector(asm, ref):
    name, _, sub = str(ref).partition(":")
    part = _part(asm, name)
    if sub:
        try:
            part.Shape.getElement(sub)
        except Exception:
            raise HandlerError("%s has no %s (see get_topology on %s)"
                               % (part.Name, sub, part.Name))
    return [part, [sub, sub]]


@_mutating("Create joint")
def create_joint(doc, type, a, b, assembly=None, offset=None, rotation=0.0,
                 distance=None, angle=None, label=None):
    asm = _assembly(doc, assembly)
    joint_type = next((t for t in _JOINT_TYPES if t.lower() == str(type).lower()), None)
    if joint_type is None:
        raise HandlerError("type must be one of %s" % ", ".join(_JOINT_TYPES))
    refs = [_connector(asm, a), _connector(asm, b)]
    if refs[0][0] is refs[1][0]:
        raise HandlerError("a and b must be on two different parts")
    joint_module = _joint_module()
    joint = _joint_group(asm).newObject("App::FeaturePython", "Joint")
    joint_module.Joint(joint, joint_module.JointTypes.index(joint_type))
    if label:
        joint.Label = label
    if Gui:
        joint_module.ViewProviderJoint(joint.ViewObject)
    # Offset1 sits on a's connector, so it moves b relative to a.
    if offset or rotation:
        joint.Offset1 = App.Placement(_vec(offset or [0, 0, 0], "offset"),
                                      App.Rotation(App.Vector(0, 0, 1), float(rotation)))
    if distance is not None:
        joint.Distance = float(distance)
    if angle is not None:
        joint.Angle = float(angle)
    joint.Proxy.setJointConnectors(joint, refs)
    result = _solve(asm)
    result["joint"] = joint.Name
    return result


@_mutating("Solve assembly")
def solve_assembly(doc, assembly=None):
    return _solve(_assembly(doc, assembly))


def get_assembly(assembly=None, document=None):
    return _summary(_assembly(_doc(document), assembly))


HANDLERS = {fn.__name__: fn for fn in [
    create_assembly, insert_part, create_joint, solve_assembly, get_assembly,
]}
