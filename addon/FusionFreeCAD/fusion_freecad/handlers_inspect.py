"""RPC handlers that check a model: geometry validity, interference between parts, mass
properties and materials. Shapes are taken in document coordinates (``Part.getShape``),
so links in an assembly are checked where they sit.
"""

import FreeCAD as App

from .handlers import (HandlerError, _doc, _mutating, _obj, _round, _shape_summary,
                       _vec_out)

TOUCH = 1e-6  # mm: closer than this counts as touching


def _shape(obj):
    import Part

    shape = Part.getShape(obj)
    if shape.isNull():
        raise HandlerError("%s has no shape" % obj.Label)
    return shape


def check_geometry(name, document=None):
    """Is the shape a valid, closed solid? Lists what OCC's checker finds otherwise."""
    doc = _doc(document)
    obj = _obj(doc, name)
    shape = _shape(obj)
    problems = []
    try:
        shape.check(True)  # also runs the boolean checker: self-intersections etc.
    except Exception as e:
        problems = [line.strip() for line in str(e).splitlines() if line.strip()]
    open_shells = [i for i, s in enumerate(shape.Shells, 1) if not s.isClosed()]
    if not shape.Solids:
        problems.append("no solid: the shape is %s" % shape.ShapeType.lower())
    if open_shells:
        problems.append("open shells (holes in the surface): %s"
                        % ", ".join("Shell%d" % i for i in open_shells))
    if "Invalid" in obj.State or "Error" in obj.State:
        problems.append("the object failed to recompute")
    return {"name": obj.Name, "ok": not problems and shape.isValid(),
            "valid": shape.isValid(), "solids": len(shape.Solids),
            "closed": not open_shells and bool(shape.Solids),
            "problems": problems}


def _solid_parts(doc):
    """Default set for interference: visible bodies and links to solids."""
    out = []
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Body" or obj.isDerivedFrom("App::Link"):
            if not getattr(obj, "Visibility", True):
                continue
            try:
                if _shape(obj).Solids:
                    out.append(obj)
            except HandlerError:
                pass
    return out


def _shell(shape):
    import Part

    return Part.Compound(shape.Shells) if shape.Shells else shape


def interference(names=None, document=None, include_touching=False):
    """Pairs of parts whose solids overlap, with the overlapping volume."""
    doc = _doc(document)
    parts = [_obj(doc, n) for n in names] if names else _solid_parts(doc)
    if len(parts) < 2:
        raise HandlerError("need at least two parts to compare (pass names=)")
    shapes = [(p, _shape(p)) for p in parts]
    clashes, touching = [], []
    for i, (a, sa) in enumerate(shapes):
        for b, sb in shapes[i + 1:]:
            if not sa.BoundBox.intersect(sb.BoundBox):
                continue
            common = sa.common(sb)
            volume = common.Volume if not common.isNull() else 0.0
            if volume > 1e-6:
                clash = {"a": a.Name, "b": b.Name, "volume": _round(volume)}
                bb = common.BoundBox
                clash["bound_box"] = {"min": [_round(bb.XMin), _round(bb.YMin),
                                              _round(bb.ZMin)],
                                      "max": [_round(bb.XMax), _round(bb.YMax),
                                              _round(bb.ZMax)]}
                clashes.append(clash)
            # Shells, not solids: OCCT 7.9's distance between touching solids
            # segfaults (seen with nixpkgs' FreeCAD 1.1.4). They don't overlap here,
            # so the shells' distance is the solids' distance.
            elif include_touching and _shell(sa).distToShape(_shell(sb))[0] < TOUCH:
                touching.append({"a": a.Name, "b": b.Name})
    result = {"parts": [p.Name for p in parts], "interferences": clashes}
    if include_touching:
        result["touching"] = touching
    return result


# Materials (FreeCAD's material library) and mass

def _find_material(name):
    import Materials

    manager = Materials.MaterialManager()
    materials = [m for m in manager.Materials.values()
                 if m.PhysicalProperties.get("Density")]
    wanted = name.lower()
    for test in (lambda m: m.Name.lower() == wanted,
                 lambda m: m.Name.lower() == wanted + "-generic",
                 lambda m: m.Name.lower().startswith(wanted)):
        found = sorted((m for m in materials if test(m)), key=lambda m: m.Name)
        if found:
            return found[0]
    close = sorted({m.Name for m in materials if wanted[:3] in m.Name.lower()})
    raise HandlerError("no material %r in FreeCAD's library%s" % (
        name, "; similar: " + ", ".join(close[:10]) if close else ""))


def _density(material):
    """kg/mm^3 -> g/cm^3."""
    q = App.Units.Quantity(material.PhysicalProperties["Density"])
    return q.getValueAs("g/cm^3").Value if hasattr(q, "getValueAs") else q.Value * 1e6


def _object_material(obj):
    material = getattr(obj, "ShapeMaterial", None)
    if material is None and obj.isDerivedFrom("App::Link") and obj.LinkedObject:
        material = getattr(obj.LinkedObject, "ShapeMaterial", None)
    return material


@_mutating("Set material")
def set_material(doc, name, material):
    obj = _obj(doc, name)
    if "ShapeMaterial" not in obj.PropertiesList:
        raise HandlerError("%s can't carry a material" % obj.Label)
    found = _find_material(material)
    obj.ShapeMaterial = found
    return {"name": obj.Name, "material": found.Name,
            "density": _round(_density(found))}


def mass_properties(name, material=None, density=None, document=None):
    """Volume, mass, centre of mass and inertia. Density in g/cm^3 comes from
    ``density``, else ``material`` (a library name like 'PLA' or 'Steel-Generic'), else
    the object's own material."""
    doc = _doc(document)
    obj = _obj(doc, name)
    solids = _shape(obj).Solids
    if not solids:
        raise HandlerError("%s has no solid" % obj.Label)
    if density is not None:
        source = "density"
        rho = float(density)
    else:
        found = _find_material(material) if material else _object_material(obj)
        if found is None:
            raise HandlerError("%s has no material; pass material= or density=" % obj.Label)
        source = found.Name
        rho = _density(found)

    volume = sum(s.Volume for s in solids)
    com = App.Vector()
    for s in solids:
        com += s.CenterOfMass * s.Volume
    com = com * (1.0 / volume)
    # Inertia about the overall centre of mass: each solid's own (unit density, about
    # its centre) moved there with the parallel axis theorem, then times density.
    inertia = [[0.0] * 3 for _ in range(3)]
    for s in solids:
        m = s.MatrixOfInertia
        own = [[m.A11, m.A12, m.A13], [m.A21, m.A22, m.A23], [m.A31, m.A32, m.A33]]
        d = s.CenterOfMass - com
        dv = [d.x, d.y, d.z]
        for i in range(3):
            for j in range(3):
                shift = (d.Length ** 2 if i == j else 0.0) - dv[i] * dv[j]
                inertia[i][j] += own[i][j] + s.Volume * shift
    g_per_mm3 = rho / 1000.0
    summary = _shape_summary(_shape(obj))
    return {"name": obj.Name, "density_g_cm3": _round(rho), "density_from": source,
            "volume_mm3": _round(volume), "area_mm2": summary["area"],
            "mass_g": _round(volume * g_per_mm3),
            "center_of_mass": _vec_out(com),
            "inertia_g_mm2": [[_round(v * g_per_mm3) for v in row] for row in inertia],
            "bound_box": summary["bound_box"]}


HANDLERS = {fn.__name__: fn for fn in [
    check_geometry, interference, set_material, mass_properties,
]}
