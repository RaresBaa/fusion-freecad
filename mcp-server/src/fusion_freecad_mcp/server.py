"""MCP server exposing FreeCAD modelling tools.

Each tool forwards to the RPC bridge inside a running FreeCAD (see client.py);
the real work happens in addon/FusionFreeCAD/fusion_freecad/handlers.py.
"""

import base64
import json
from typing import Annotated, Any, Literal

try:  # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer
except ImportError:  # mcp 1.x (e.g. older nixpkgs)
    from mcp.server.fastmcp import FastMCP as MCPServer, Image
from pydantic import Field

from .client import FreeCADClient

INSTRUCTIONS = """\
Drive a live FreeCAD session for parametric part modelling (PartDesign).

Units are millimetres and degrees. Typical flow:
  new_document -> create_sketch (on XY/XZ/YZ or on a face like "Pad:Face6")
  -> pad / pocket / revolve / hole -> get_topology to find edge names -> fillet / chamfer
  (shell, mirror, linear_pattern, polar_pattern copy or hollow features) -> screenshot to check the result -> export (STEP/STL).

Sketch geometry indices start at 0 in the order shapes are added; a rectangle or
polygon adds one line per side. Face and edge names (Face1, Edge7) come from
get_topology and can change after earlier features are edited, so look them up again
rather than reusing old names. Each modelling tool is one undo step in FreeCAD.
If a tool result contains "errors", a feature failed to recompute: inspect it, then
undo or fix it. Drive sizes from set_parameters so the user can change them later.
For sketches on angled or offset planes, make a datum_plane first. Before exporting,
check_geometry (and interference for assemblies); mass_properties gives the weight.
Use run_python only when no dedicated tool fits.
"""

mcp = MCPServer("freecad", instructions=INSTRUCTIONS)
client = FreeCADClient()

Doc = Annotated[str | None, Field(description="Document name; defaults to the active document")]
Point2 = list[float]


# --- session and documents --------------------------------------------------

@mcp.tool()
def freecad_status() -> dict[str, Any]:
    """Check the FreeCAD connection: version, GUI or headless, active document."""
    return client.call("ping")


@mcp.tool()
def list_documents() -> dict[str, Any]:
    """List open FreeCAD documents."""
    return client.call("list_documents")


@mcp.tool()
def new_document(name: str = "Unnamed") -> dict[str, Any]:
    """Create a new, empty document and make it active."""
    return client.call("new_document", name=name)


@mcp.tool()
def open_document(path: str) -> dict[str, Any]:
    """Open an existing .FCStd file."""
    return client.call("open_document", path=path)


@mcp.tool()
def save_document(path: Annotated[str | None, Field(
                      description="Save as this .FCStd path; omit to save in place")] = None,
                  document: Doc = None) -> dict[str, Any]:
    """Save a document."""
    return client.call("save_document", path=path, document=document)


@mcp.tool()
def close_document(document: str) -> dict[str, Any]:
    """Close a document without saving."""
    return client.call("close_document", document=document)


@mcp.tool()
def activate_document(document: str) -> dict[str, Any]:
    """Make another open document the active one."""
    return client.call("activate_document", document=document)


# --- inspection --------------------------------------------------------------

@mcp.tool()
def list_objects(document: Doc = None) -> dict[str, Any]:
    """List all objects in a document: name, label, type, owning body, validity."""
    return client.call("list_objects", document=document)


@mcp.tool()
def get_object(name: str, document: Doc = None) -> dict[str, Any]:
    """Details of one object: properties, shape summary (volume, bounding box), and for
    sketches the geometry and constraints."""
    return client.call("get_object", name=name, document=document)


@mcp.tool()
def get_topology(name: str, document: Doc = None,
                 max_items: int = 300) -> dict[str, Any]:
    """Faces and edges of an object's shape with type, size, centre, and normal (planar
    faces). Use it to choose edges for fillet/chamfer or a face to sketch on."""
    return client.call("get_topology", name=name, document=document, max_items=max_items)


@mcp.tool()
def measure(a: Annotated[str, Field(
                description="Object or element, e.g. 'Pad', 'Pad:Face6', 'Pad:Edge3', "
                            "'Pad:Vertex1'")],
            b: Annotated[str | None, Field(description="Second element to measure to")] = None,
            document: Doc = None) -> dict[str, Any]:
    """Measure (Fusion: Inspect > Measure). One element: length, area, radius/diameter,
    point or volume. Two: minimum distance, closest points, and the angle between
    planar faces / straight edges (plus plane_distance when the faces are parallel)."""
    return client.call("measure", a=a, b=b, document=document)


@mcp.tool()
def check_geometry(name: Annotated[str, Field(description="Body, feature or part")],
                   document: Doc = None) -> dict[str, Any]:
    """Check a shape before exporting or printing: valid, a closed solid, and what's
    wrong otherwise (self-intersections, open shells, failed recompute)."""
    return client.call("check_geometry", name=name, document=document)


@mcp.tool()
def interference(names: Annotated[list[str] | None, Field(
                     description="Parts to compare (bodies or assembly links); default "
                                 "every visible body and link")] = None,
                 include_touching: bool = False,
                 document: Doc = None) -> dict[str, Any]:
    """Find parts that overlap (Fusion: Inspect > Interference), with the overlapping
    volume and where it is. Checks parts where they sit, e.g. in an assembly."""
    return client.call("interference", names=names, include_touching=include_touching,
                       document=document)


@mcp.tool()
def set_material(name: str,
                 material: Annotated[str, Field(
                     description="From FreeCAD's material library: 'PLA', 'ABS', "
                                 "'PETG', 'Aluminum-6061-T6', 'Steel-Generic'...")],
                 document: Doc = None) -> dict[str, Any]:
    """Give a body its material (used by mass_properties)."""
    return client.call("set_material", name=name, material=material, document=document)


@mcp.tool()
def mass_properties(name: str,
                    material: Annotated[str | None, Field(
                        description="Library material to assume, e.g. 'PLA'")] = None,
                    density: Annotated[float | None, Field(
                        description="g/cm^3, instead of a material")] = None,
                    document: Doc = None) -> dict[str, Any]:
    """Mass, volume, area, centre of mass and inertia tensor (g*mm^2, about the centre of
    mass). Density from `density`, else `material`, else the body's own material."""
    return client.call("mass_properties", name=name, material=material, density=density,
                       document=document)


@mcp.tool()
def project_to_sketch(sketch: str,
                      elements: Annotated[list[str], Field(
                          description="Model edges, faces or vertices, e.g. "
                                      "['Pad:Edge3', 'Pad:Face6']")],
                      defining: Annotated[bool, Field(
                          description="Also use them as sketch geometry, e.g. as a "
                                      "profile to pad")] = False,
                      document: Doc = None) -> dict[str, Any]:
    """Project model geometry into a sketch (Fusion: Project). The projections follow
    the model; constrain to them with their negative indices (external_indices)."""
    return client.call("project_to_sketch", sketch=sketch, elements=elements,
                       defining=defining, document=document)


@mcp.tool()
def offset_sketch(sketch: str,
                  distance: Annotated[float, Field(
                      description="mm; positive goes outward from a closed profile")],
                  geometry: Annotated[list[int] | None, Field(
                      description="Indices to offset; default all non-construction")] = None,
                  join: Literal["arc", "intersection"] = "arc",
                  document: Doc = None) -> dict[str, Any]:
    """Offset sketch geometry (Fusion: Offset), e.g. a wall around a profile."""
    return client.call("offset_sketch", sketch=sketch, distance=distance,
                       geometry=geometry, join=join, document=document)


@mcp.tool()
def fillet_sketch(sketch: str, radius: float,
                  corners: Annotated[list[list[float]] | None, Field(
                      description="[[x, y], ...] corner points in sketch coordinates; "
                                  "default every corner between two lines")] = None,
                  document: Doc = None) -> dict[str, Any]:
    """Round sketch corners (Fusion: Sketch Fillet)."""
    return client.call("fillet_sketch", sketch=sketch, radius=radius, corners=corners,
                       document=document)


@mcp.tool()
def move_body(name: Annotated[str, Field(description="Body, assembly link or part")],
              translate: Annotated[list[float] | None, Field(
                  description="[x, y, z] mm")] = None,
              axis: Annotated[str | list[float] | None, Field(
                  description="Rotation axis: 'X', 'Y', 'Z' or [x, y, z]; default Z")] = None,
              angle: Annotated[float, Field(description="Degrees")] = 0.0,
              center: Annotated[list[float] | None, Field(
                  description="Point the axis goes through; default the origin")] = None,
              document: Doc = None) -> dict[str, Any]:
    """Move a whole body (Fusion: Move/Copy): rotate, then translate, relative to where
    it is."""
    return client.call("move_body", name=name, translate=translate, axis=axis,
                       angle=angle, center=center, document=document)


@mcp.tool()
def copy_body(name: str,
              linked: Annotated[bool, Field(
                  description="A link that always shows the original's shape, instead of "
                              "an independent copy of its features")] = False,
              translate: Annotated[list[float] | None, Field(
                  description="[x, y, z] mm to move the copy")] = None,
              label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Copy a body."""
    return client.call("copy_body", name=name, linked=linked, translate=translate,
                       label=label, document=document)


@mcp.tool()
def appearance(name: str,
               color: Annotated[str | list[float] | None, Field(
                   description="'#rrggbb', or [r, g, b] as 0-1 or 0-255")] = None,
               transparency: Annotated[int | None, Field(description="0-100")] = None,
               document: Doc = None) -> dict[str, Any]:
    """Colour of a body or part in the 3D view (GUI only)."""
    return client.call("appearance", name=name, color=color, transparency=transparency,
                       document=document)


# --- construction geometry -------------------------------------------------

@mcp.tool()
def datum_plane(on: Annotated[str | list[str], Field(
                    description="A plane or planar face, e.g. 'XY' or 'Pad:Face6'; or "
                                "three vertices/points for a plane through them")] = "XY",
                offset: Annotated[float, Field(
                    description="mm along the plane's normal")] = 0.0,
                angle: Annotated[float, Field(
                    description="Tilt in degrees about `about`")] = 0.0,
                about: Annotated[str | None, Field(
                    description="Straight edge or axis lying in the plane to tilt "
                                "about; default the plane's X direction")] = None,
                body: str | None = None, label: str | None = None,
                document: Doc = None) -> dict[str, Any]:
    """Construction plane (Fusion: Offset Plane, Plane at Angle, Plane Through Three
    Points), attached so it follows the model. Sketch on it with
    create_sketch(plane=<its name>)."""
    return client.call("datum_plane", on=on, offset=offset, angle=angle, about=about,
                       body=body, label=label, document=document)


@mcp.tool()
def datum_axis(through: Annotated[str | list[str], Field(
                   description="A straight edge; two points; two planes (their "
                               "intersection); or a circular edge / cylindrical face "
                               "(its axis)")],
               body: str | None = None, label: str | None = None,
               document: Doc = None) -> dict[str, Any]:
    """Construction axis, e.g. for polar patterns, revolves or tilting a plane."""
    return client.call("datum_axis", through=through, body=body, label=label,
                       document=document)


@mcp.tool()
def datum_point(at: Annotated[str | list[str], Field(
                    description="A vertex, or an edge/face/circle (its centre)")],
                offset: Annotated[list[float] | None, Field(
                    description="[x, y, z] mm from there")] = None,
                body: str | None = None, label: str | None = None,
                document: Doc = None) -> dict[str, Any]:
    """Construction point."""
    return client.call("datum_point", at=at, offset=offset, body=body, label=label,
                       document=document)


# --- modelling ---------------------------------------------------------------

@mcp.tool()
def create_body(label: str = "Body", document: Doc = None) -> dict[str, Any]:
    """Create a PartDesign body (a single solid part) and make it active."""
    return client.call("create_body", label=label, document=document)


GEOMETRY_HELP = """\
List of shapes in sketch coordinates (mm). Each item is an object with a "type":
  {"type": "rectangle", "corner": [x, y], "width": w, "height": h}
  {"type": "rectangle", "center": [x, y], "width": w, "height": h}
  {"type": "circle", "center": [x, y], "radius": r}
  {"type": "line", "start": [x, y], "end": [x, y]}
  {"type": "arc", "center": [x, y], "radius": r, "start_angle": deg, "end_angle": deg}
  {"type": "polygon", "points": [[x, y], ...]}   (closed)
Optional on any item: "construction": true. Rectangles and circles get size
dimensions automatically; pass "dimensioned": false to skip them."""

CONSTRAINTS_HELP = """\
Extra Sketcher constraints, passed straight to Sketcher.Constraint(type, *args).
Geometry indices refer to this sketch; point positions are 1=start, 2=end, 3=centre;
-1 is the sketch X axis, -2 the Y axis, and point (-1, 1) is the origin. Examples:
  {"type": "Coincident", "args": [0, 1, -1, 1]}   pin geometry 0's start to the origin
  {"type": "Distance", "args": [4, 10.0]}        length of line 4
  {"type": "Radius", "args": [5, 3.0]}
  {"type": "Symmetric", "args": [0, 1, 0, 2, -1, 1]}"""


@mcp.tool()
def create_sketch(
    geometry: Annotated[list[dict[str, Any]], Field(description=GEOMETRY_HELP)],
    plane: Annotated[str, Field(
        description="'XY', 'XZ', 'YZ' (body origin) or a datum plane from datum_plane "
                    "(ignored when face is given)")] = "XY",
    face: Annotated[str | None, Field(
        description="Sketch on a planar face instead, e.g. 'Pad:Face6' (see get_topology)")] = None,
    offset: Annotated[float, Field(description="Offset along the plane normal, mm")] = 0.0,
    constraints: Annotated[list[dict[str, Any]] | None, Field(description=CONSTRAINTS_HELP)] = None,
    body: Annotated[str | None, Field(
        description="Body to add to; defaults to the active/only body, created if none")] = None,
    label: str | None = None,
    document: Doc = None,
) -> dict[str, Any]:
    """Create a sketch in a PartDesign body and draw closed profiles in it.
    Returns the sketch name and, per input item, the created geometry indices."""
    return client.call("create_sketch", geometry=geometry, plane=plane, face=face,
                       offset=offset, constraints=constraints, body=body, label=label,
                       document=document)


@mcp.tool()
def add_sketch_geometry(
    sketch: str,
    geometry: Annotated[list[dict[str, Any]], Field(description=GEOMETRY_HELP)],
    constraints: Annotated[list[dict[str, Any]] | None, Field(description=CONSTRAINTS_HELP)] = None,
    document: Doc = None,
) -> dict[str, Any]:
    """Add more geometry and/or constraints to an existing sketch."""
    return client.call("add_sketch_geometry", sketch=sketch, geometry=geometry,
                       constraints=constraints, document=document)


Constraint = Annotated[int | str, Field(
    description="Constraint index or name (see get_object on the sketch)")]


@mcp.tool()
def set_dimension(sketch: str, constraint: Constraint,
                  value: Annotated[float | None, Field(
                      description="New size: mm, or degrees for angles")] = None,
                  expression: Annotated[str | None, Field(
                      description="Drive it by an expression instead, e.g. "
                                  "'Parameters.width / 2'")] = None,
                  name: Annotated[str | None, Field(
                      description="Name the constraint, so expressions can use "
                                  "Sketch.Constraints.<name>")] = None,
                  document: Doc = None) -> dict[str, Any]:
    """Change, name, or bind to an expression a sketch dimension (Fusion: edit a sketch
    dimension). A plain value replaces any expression. Returns the solved sketch."""
    return client.call("set_dimension", sketch=sketch, constraint=constraint, value=value,
                       expression=expression, name=name, document=document)


@mcp.tool()
def delete_sketch_geometry(sketch: str,
                           geometry: Annotated[list[int] | None, Field(
                               description="Geometry indices to delete (their "
                                           "constraints go too)")] = None,
                           constraints: Annotated[list[int | str] | None, Field(
                               description="Constraint indices or names to delete")] = None,
                           document: Doc = None) -> dict[str, Any]:
    """Delete geometry and/or constraints from a sketch. Later indices shift down;
    the result lists the sketch's geometry and constraints afterwards."""
    return client.call("delete_sketch_geometry", sketch=sketch, geometry=geometry,
                       constraints=constraints, document=document)


@mcp.tool()
def move_sketch_geometry(sketch: str, index: int,
                         to: Annotated[Point2, Field(description="[x, y] in sketch mm")],
                         point: Annotated[Literal["edge", "start", "end", "center"], Field(
                             description="Which point to drag; 'edge' moves the whole "
                                         "shape")] = "edge",
                         relative: Annotated[bool, Field(
                             description="Move by `to` instead of to it")] = False,
                         document: Doc = None) -> dict[str, Any]:
    """Drag sketch geometry, like dragging it in the sketcher: the solver keeps the
    constraints, so constrained geometry moves only where it is free to."""
    return client.call("move_sketch_geometry", sketch=sketch, index=index, to=to,
                       point=point, relative=relative, document=document)


# --- parameters --------------------------------------------------------------

@mcp.tool()
def set_parameters(parameters: Annotated[dict[str, Any], Field(
        description="name -> value. Numbers are mm; strings can carry units ('30 deg', "
                    "'5 mm') or start with '=' for an expression of other parameters "
                    "('=width / 2'). For a plain number use {'value': 4, 'kind': "
                    "'number'}; kind is length, angle or number. Add 'comment' too if "
                    "useful.")],
        document: Doc = None) -> dict[str, Any]:
    """Create or change user parameters (Fusion: Change Parameters). They live in the
    document's 'Parameters' object; use them in expressions as Parameters.<name>,
    via set_expression or set_dimension(expression=...)."""
    return client.call("set_parameters", parameters=parameters, document=document)


@mcp.tool()
def get_parameters(document: Doc = None) -> dict[str, Any]:
    """List user parameters and every expression in the document (what drives what)."""
    return client.call("get_parameters", document=document)


@mcp.tool()
def delete_parameter(name: str, document: Doc = None) -> dict[str, Any]:
    """Delete a user parameter."""
    return client.call("delete_parameter", name=name, document=document)


@mcp.tool()
def rename_parameter(name: str, new_name: str, document: Doc = None) -> dict[str, Any]:
    """Rename a user parameter; expressions that use it follow the new name."""
    return client.call("rename_parameter", name=name, new_name=new_name,
                       document=document)


@mcp.tool()
def set_expression(name: Annotated[str, Field(description="Object, e.g. 'Pad'")],
                   property: Annotated[str, Field(
                       description="Property, e.g. 'Length', 'Radius', "
                                   "'Placement.Base.x', or a sketch's "
                                   "'Constraints.width'")],
                   expression: Annotated[str | None, Field(
                       description="e.g. 'Parameters.thickness * 2' or "
                                   "'Sketch.Constraints.width / 3'; null removes "
                                   "it")] = None,
                   document: Doc = None) -> dict[str, Any]:
    """Make a property follow an expression so it updates when parameters change."""
    return client.call("set_expression", name=name, property=property,
                       expression=expression, document=document)


Length2 = Annotated[float | None, Field(
    description="Also extrude this many mm the other way (Fusion: Two Sides)")]
Taper = Annotated[float, Field(
    description="Taper angle in degrees; positive widens the extrude away from the "
                "sketch")]


@mcp.tool()
def pad(sketch: str, length: float = 10.0, reversed: bool = False, midplane: bool = False,
        up_to_face: Annotated[str | None, Field(
            description="Extrude up to this face instead of a length, e.g. 'Pad:Face3'")] = None,
        length2: Length2 = None, taper: Taper = 0.0,
        label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Extrude a sketch to add material (Fusion: Extrude / Join)."""
    return client.call("pad", sketch=sketch, length=length, reversed=reversed,
                       midplane=midplane, up_to_face=up_to_face, length2=length2,
                       taper=taper, label=label, document=document)


@mcp.tool()
def pocket(sketch: str, length: float = 10.0, through_all: bool = False,
           reversed: bool = False, midplane: bool = False,
           length2: Length2 = None, taper: Taper = 0.0, label: str | None = None,
           document: Doc = None) -> dict[str, Any]:
    """Extrude a sketch to cut material (Fusion: Extrude / Cut). By default cuts into the
    solid, opposite the sketch normal; use reversed if it cuts into empty space."""
    return client.call("pocket", sketch=sketch, length=length, through_all=through_all,
                       reversed=reversed, midplane=midplane, length2=length2, taper=taper,
                       label=label, document=document)


@mcp.tool()
def revolve(sketch: str, angle: float = 360.0,
            axis: Annotated[Literal["V", "H", "X", "Y", "Z"], Field(
                description="V/H = sketch vertical/horizontal axis; X/Y/Z = body axes")] = "V",
            groove: Annotated[bool, Field(description="Cut instead of adding material")] = False,
            label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Revolve a sketch around an axis (Fusion: Revolve)."""
    return client.call("revolve", sketch=sketch, angle=angle, axis=axis, groove=groove,
                       label=label, document=document)


@mcp.tool()
def loft(sketches: Annotated[list[str], Field(
             description="Profile sketches in order, e.g. on parallel planes made with "
                         "create_sketch(offset=...)")],
         cut: Annotated[bool, Field(description="Remove material instead")] = False,
         ruled: Annotated[bool, Field(
             description="Straight sides between sections instead of smooth")] = False,
         closed: Annotated[bool, Field(description="Loop back to the first profile")] = False,
         label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Blend between two or more profiles (Fusion: Loft)."""
    return client.call("loft", sketches=sketches, cut=cut, ruled=ruled, closed=closed,
                       label=label, document=document)


@mcp.tool()
def sweep(sketch: Annotated[str, Field(description="Closed profile sketch")],
          path: Annotated[str, Field(
              description="Path: a sketch of connected lines/arcs (all its edges), or one "
                          "edge like 'Sketch001:Edge1' or 'Pad:Edge3'")],
          path_edges: Annotated[list[str] | None, Field(
              description="More edges of the path object, e.g. ['Edge2', 'Edge3']")] = None,
          cut: Annotated[bool, Field(description="Remove material instead")] = False,
          mode: Annotated[Literal["standard", "fixed", "frenet"], Field(
              description="How the profile turns along the path; frenet for helices")]
              = "standard",
          transition: Annotated[Literal["transformed", "right", "round"], Field(
              description="Corner handling where path segments meet at an angle")]
              = "transformed",
          label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Sweep a profile along a path (Fusion: Sweep). Draw the path in a sketch on a
    plane perpendicular to the profile, starting where the profile is."""
    return client.call("sweep", sketch=sketch, path=path, path_edges=path_edges, cut=cut,
                       mode=mode, transition=transition, label=label, document=document)


@mcp.tool()
def press_pull(face: Annotated[str, Field(
                   description="Face to move, e.g. 'Pad:Face6' (see get_topology): flat, "
                               "or the cylindrical face of a hole, boss or fillet")],
               distance: Annotated[float | None, Field(
                   description="mm along the face's outward normal: positive adds "
                               "material (a hole gets smaller, a boss bigger, an outside "
                               "fillet sharper), negative removes it")] = None,
               radius: Annotated[float | None, Field(
                   description="Cylindrical faces only: the new radius, instead of "
                               "distance")] = None,
               label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Push or pull a face of the solid (Fusion: Press Pull). Flat faces: the quickest
    way to make a part thicker, extend a side, or recess a face, with no sketch. Curved
    faces: resizes the hole, fillet or sketch circle that made the face, keeping the
    history editable."""
    return client.call("press_pull", face=face, distance=distance, radius=radius,
                       label=label, document=document)


@mcp.tool()
def combine(target: Annotated[str, Field(description="Body that keeps the result")],
            tools: Annotated[list[str], Field(
                description="Bodies to join with, cut from or intersect with the target")],
            operation: Literal["join", "cut", "intersect"] = "join",
            keep_tools: Annotated[bool, Field(
                description="Leave the tool bodies visible")] = False,
            label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Combine bodies (Fusion: Combine): a Boolean feature in the target body's history,
    so changing a tool body updates the result."""
    return client.call("combine", target=target, tools=tools, operation=operation,
                       keep_tools=keep_tools, label=label, document=document)


@mcp.tool()
def split_body(body: str,
               tool: Annotated[str, Field(
                   description="Splitting plane: 'XY'/'XZ'/'YZ' (the body's origin), a "
                               "planar face like 'Pad:Face3', or a datum plane")],
               offset: Annotated[float, Field(
                   description="mm to move the plane along its normal")] = 0.0,
               document: Doc = None) -> dict[str, Any]:
    """Split a body in pieces along a plane (Fusion: Split Body). Each piece becomes a
    new body you can keep modelling; the original is hidden and still drives them."""
    return client.call("split_body", body=body, tool=tool, offset=offset,
                       document=document)


@mcp.tool()
def draft(faces: Annotated[list[str], Field(
              description="Faces of one feature to tilt, e.g. ['Pad:Face1', 'Pad:Face3']")],
          angle: Annotated[float, Field(description="Degrees")],
          neutral_plane: Annotated[str, Field(
              description="Plane or planar face they pivot on, e.g. 'Pad:Face5' or 'XY'")],
          pull_direction: Annotated[str | None, Field(
              description="Edge giving the pull direction; default the neutral plane's "
                          "normal")] = None,
          reversed: bool = False, label: str | None = None,
          document: Doc = None) -> dict[str, Any]:
    """Tilt side faces (Fusion: Draft), e.g. so a part comes out of a mould."""
    return client.call("draft", faces=faces, angle=angle, neutral_plane=neutral_plane,
                       pull_direction=pull_direction, reversed=reversed, label=label,
                       document=document)


@mcp.tool()
def text(text: str,
         on: Annotated[str, Field(
             description="Planar face ('Pad:Face6') or plane ('XY', a datum plane)")] = "XY",
         depth: Annotated[float, Field(
             description="mm; positive raises the text, negative engraves it")] = 1.0,
         size: Annotated[float, Field(description="Letter height, mm")] = 5.0,
         position: Annotated[list[float] | None, Field(
             description="[x, y] offset from the face's centre (or the plane's origin)")] = None,
         font: Annotated[str | None, Field(
             description="A .ttf path or a font file name like 'arial'; default osifont "
                         "(ships with FreeCAD)")] = None,
         body: str | None = None, label: str | None = None,
         document: Doc = None) -> dict[str, Any]:
    """Raised or engraved text on a face (Fusion: Text + Extrude), e.g. labels on 3D
    prints. Stays parametric: editing the text's ShapeString updates it."""
    return client.call("text", text=text, on=on, depth=depth, size=size,
                       position=position, font=font, body=body, label=label,
                       document=document)


@mcp.tool()
def rib(sketch: Annotated[str, Field(
            description="Sketch with an open profile (lines/arcs that don't close)")],
        thickness: Annotated[float, Field(description="Wall thickness, mm")],
        mode: Annotated[Literal["parallel", "normal"], Field(
            description="'parallel': fill the sketch plane between the profile and the "
                        "solid, thickness across the plane (a gusset in a corner); "
                        "'normal': thicken the profile in the plane and grow it out of "
                        "the plane until it meets the solid (a wall on a floor)")] = "parallel",
        reversed: Annotated[bool, Field(
            description="Grow towards the other side; by default the side where the "
                        "solid stops it")] = False,
        label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Thin support wall from an open sketch profile up to the solid (Fusion: Rib),
    e.g. a gusset in an L-bracket's corner: sketch one diagonal line on a plane through
    the bracket. Stays parametric (edit the sketch or Thickness)."""
    return client.call("rib", sketch=sketch, thickness=thickness, mode=mode,
                       reversed=reversed, label=label, document=document)


Edges = Annotated[list[str] | Literal["all"], Field(
    description="Edge names from get_topology, e.g. ['Edge1', 'Edge5'], or 'all'")]


@mcp.tool()
def fillet(edges: Edges, radius: float,
           base: Annotated[str | None, Field(
               description="Feature whose edges these are; defaults to the body tip")] = None,
           label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Round edges of the solid."""
    return client.call("fillet", edges=edges, radius=radius, base=base, label=label,
                       document=document)


@mcp.tool()
def chamfer(edges: Edges, size: float,
            base: Annotated[str | None, Field(
                description="Feature whose edges these are; defaults to the body tip")] = None,
            label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Bevel edges of the solid."""
    return client.call("chamfer", edges=edges, size=size, base=base, label=label,
                       document=document)


@mcp.tool()
def hole(sketch: Annotated[str, Field(
             description="Sketch with circles; a hole is drilled at each circle's centre "
                         "(sketch on the face to drill into)")],
         diameter: Annotated[float | None, Field(
             description="Drill diameter; defaults to the thread's size, else the first "
                         "circle's")] = None,
         depth: float = 10.0,
         through_all: bool = False,
         thread: Annotated[str | None, Field(
             description="Thread preset: 'M6' (ISO coarse), 'M8x1.0' (ISO fine), "
                         "'UNC 1/4', 'UNF #10', 'NPT 1/8', ... Without tapped this sizes "
                         "a clearance hole for that screw")] = None,
         tapped: Annotated[bool, Field(
             description="Threaded hole (tap drill size, thread marked) instead of a "
                         "clearance hole")] = False,
         modeled_thread: Annotated[bool, Field(
             description="Model the thread geometry (slow; for 3D printing)")] = False,
         fit: Annotated[str | None, Field(
             description="Clearance fit: Medium/Fine/Coarse for metric, "
                         "Normal/Close/Loose for inch")] = None,
         cut: Literal["counterbore", "countersink", "counterdrill"] | None = None,
         cut_diameter: Annotated[float | None, Field(
             description="Counterbore/countersink diameter; standard for the thread "
                         "when omitted")] = None,
         cut_depth: float | None = None,
         countersink_angle: Annotated[float | None, Field(description="Degrees")] = None,
         flat_bottom: Annotated[bool, Field(
             description="Flat instead of a 118° drill point")] = False,
         reversed: bool = False,
         label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Drill holes (Fusion: Hole): simple, clearance or tapped, optionally counterbored
    or countersunk."""
    return client.call("hole", sketch=sketch, diameter=diameter, depth=depth,
                       through_all=through_all, thread=thread, tapped=tapped,
                       modeled_thread=modeled_thread, fit=fit, cut=cut,
                       cut_diameter=cut_diameter, cut_depth=cut_depth,
                       countersink_angle=countersink_angle, flat_bottom=flat_bottom,
                       reversed=reversed, label=label, document=document)


@mcp.tool()
def shell(faces: Annotated[list[str], Field(
              description="Faces to remove (leave open), e.g. ['Face6'] (get_topology)")],
          thickness: float,
          base: Annotated[str | None, Field(
              description="Feature whose faces these are; defaults to the body tip")] = None,
          outward: Annotated[bool, Field(
              description="Add the wall outside instead of keeping the outer size")] = False,
          label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Hollow out the solid with walls of the given thickness (Fusion: Shell)."""
    return client.call("shell", faces=faces, thickness=thickness, base=base,
                       outward=outward, label=label, document=document)


REFERENCE_HELP = ("'X', 'Y', 'Z' (body axes), 'XY', 'XZ', 'YZ' (body planes), an edge or "
                  "face like 'Pad:Edge3' / 'Pad:Face6', or a sketch axis like "
                  "'Sketch:H_Axis'")
Features = Annotated[list[str] | None, Field(
    description="Features to copy, e.g. ['Pocket001']; defaults to the body's last feature")]
WholeBody = Annotated[bool, Field(
    description="Copy the whole body's solid instead of individual features")]


@mcp.tool()
def mirror(plane: Annotated[str, Field(description="Mirror plane: " + REFERENCE_HELP)] = "YZ",
           features: Features = None, whole_body: WholeBody = False,
           label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Mirror features across a plane (Fusion: Mirror)."""
    return client.call("mirror", plane=plane, features=features, whole_body=whole_body,
                       label=label, document=document)


@mcp.tool()
def linear_pattern(
    direction: Annotated[str, Field(description="Direction: " + REFERENCE_HELP)],
    count: Annotated[int, Field(description="Number of instances, including the original")],
    spacing: Annotated[float | None, Field(description="Distance between instances")] = None,
    length: Annotated[float | None, Field(
        description="Or: distance from first to last instance")] = None,
    features: Features = None,
    reversed: bool = False,
    direction2: Annotated[str | None, Field(
        description="Second direction for a grid")] = None,
    count2: int | None = None, spacing2: float | None = None, length2: float | None = None,
    whole_body: WholeBody = False,
    label: str | None = None, document: Doc = None,
) -> dict[str, Any]:
    """Copy features in a row or grid (Fusion: Rectangular Pattern)."""
    return client.call("linear_pattern", direction=direction, count=count, spacing=spacing,
                       length=length, features=features, reversed=reversed,
                       direction2=direction2, count2=count2, spacing2=spacing2,
                       length2=length2, whole_body=whole_body, label=label,
                       document=document)


@mcp.tool()
def polar_pattern(
    count: Annotated[int, Field(description="Number of instances, including the original")],
    axis: Annotated[str, Field(description="Axis: " + REFERENCE_HELP)] = "Z",
    angle: Annotated[float, Field(
        description="Total angle; 360 spreads the instances evenly around")] = 360.0,
    features: Features = None, reversed: bool = False, whole_body: WholeBody = False,
    label: str | None = None, document: Doc = None,
) -> dict[str, Any]:
    """Copy features around an axis (Fusion: Circular Pattern)."""
    return client.call("polar_pattern", count=count, axis=axis, angle=angle,
                       features=features, reversed=reversed, whole_body=whole_body,
                       label=label, document=document)


@mcp.tool()
def set_property(name: str, property: str, value: Any, document: Doc = None) -> dict[str, Any]:
    """Change a property of an object, e.g. a Pad's Length, then recompute. Use
    get_object to see available properties."""
    return client.call("set_property", name=name, property=property, value=value,
                       document=document)


@mcp.tool()
def delete_object(name: str, document: Doc = None) -> dict[str, Any]:
    """Delete an object (removing it from its body first)."""
    return client.call("delete_object", name=name, document=document)


# --- timeline ----------------------------------------------------------------

Body = Annotated[str | None, Field(
    description="Body whose timeline to use; defaults to the active body")]


@mcp.tool()
def get_timeline(body: Body = None, document: Doc = None) -> dict[str, Any]:
    """The body's feature history in order, Fusion-timeline style: each entry's kind
    (sketch/feature/datum), whether it is rolled back, suppressed or failing, and where
    the rollback marker is (right after the tip feature)."""
    return client.call("get_timeline", body=body, document=document)


@mcp.tool()
def roll_timeline(to: Annotated[str | None, Field(
                      description="Feature name to roll to (marker goes right after it), "
                                  "or 'start' / 'end'")] = None,
                  steps: Annotated[int | None, Field(
                      description="Instead of to: move the marker by this many solid "
                                  "features; negative goes back")] = None,
                  body: Body = None, document: Doc = None) -> dict[str, Any]:
    """Move the timeline marker (Fusion: drag the rollback marker). Features after it are
    temporarily excluded from the model, and new features are inserted at the marker,
    so rolling back lets you add something earlier in the history. Roll to 'end'
    afterwards."""
    return client.call("roll_timeline", to=to, steps=steps, body=body, document=document)


@mcp.tool()
def move_feature(name: Annotated[str, Field(description="Feature (or sketch) to move")],
                 after: Annotated[str | None, Field(
                     description="Put it right after this feature, or 'start' / 'end'")]
                     = None,
                 before: Annotated[str | None, Field(
                     description="Or: right before this feature")] = None,
                 with_sketch: Annotated[bool, Field(
                     description="Move the feature's own profile sketch along")] = True,
                 document: Doc = None) -> dict[str, Any]:
    """Reorder the history (Fusion: drag a feature in the timeline). Refused if the
    feature would come before something it is built on (e.g. the face its sketch sits
    on). Returns the new order and the body's shape."""
    return client.call("move_feature", name=name, after=after, before=before,
                       with_sketch=with_sketch, document=document)


@mcp.tool()
def suppress_feature(name: str, suppressed: bool = True,
                     document: Doc = None) -> dict[str, Any]:
    """Suppress (temporarily disable) or unsuppress a feature without deleting it."""
    return client.call("suppress_feature", name=name, suppressed=suppressed,
                       document=document)


@mcp.tool()
def recompute(document: Doc = None) -> dict[str, Any]:
    """Recompute the document and report objects that failed."""
    return client.call("recompute", document=document)


@mcp.tool()
def undo(steps: int = 1, document: Doc = None) -> dict[str, Any]:
    """Undo the last steps (each modelling tool call is one step)."""
    return client.call("undo", steps=steps, document=document)


@mcp.tool()
def redo(steps: int = 1, document: Doc = None) -> dict[str, Any]:
    """Redo undone steps."""
    return client.call("redo", steps=steps, document=document)


# --- assemblies --------------------------------------------------------------

Assembly = Annotated[str | None, Field(
    description="Assembly to use; defaults to the document's only assembly")]
JointRef = Annotated[str, Field(
    description="A part of the assembly (its name from insert_part, or the body it "
                "shows) plus an element of it, e.g. 'Pin:Edge2' (a circular edge = its "
                "centre and axis) or 'Plate:Face6'; the part alone means its origin. "
                "Use get_topology on the part to find element names")]


@mcp.tool()
def create_assembly(label: str = "Assembly", document: Doc = None) -> dict[str, Any]:
    """Create an assembly (FreeCAD's Assembly workbench) to put parts together with
    joints. Model each part as its own body first."""
    return client.call("create_assembly", label=label, document=document)


@mcp.tool()
def insert_part(part: Annotated[str, Field(description="Body (or other solid) to add")],
                position: Annotated[list[float] | None, Field(
                    description="[x, y, z] start position; joints move it later")] = None,
                rotation_axis: list[float] | None = None,
                rotation_angle: Annotated[float, Field(description="Degrees")] = 0.0,
                ground: Annotated[bool | None, Field(
                    description="Fix it in place; by default the first part is "
                                "grounded")] = None,
                assembly: Assembly = None, label: str | None = None,
                document: Doc = None) -> dict[str, Any]:
    """Add a part to an assembly, as a link (Fusion: insert a component). The same body
    can be inserted several times."""
    return client.call("insert_part", part=part, position=position,
                       rotation_axis=rotation_axis, rotation_angle=rotation_angle,
                       ground=ground, assembly=assembly, label=label, document=document)


@mcp.tool()
def create_joint(type: Annotated[Literal["fixed", "revolute", "cylindrical", "slider",
                                         "ball", "distance", "parallel", "perpendicular",
                                         "angle"], Field(
                     description="fixed = rigid, revolute = hinge, cylindrical = turns "
                                 "and slides, slider = slides, ball = pivots; distance / "
                                 "parallel / perpendicular / angle relate two elements")],
                 a: JointRef, b: JointRef,
                 offset: Annotated[list[float] | None, Field(
                     description="[x, y, z] shift of b relative to a's joint origin "
                                 "(z is along a's axis/normal)")] = None,
                 rotation: Annotated[float, Field(
                     description="Turn b about the joint axis, degrees")] = 0.0,
                 distance: Annotated[float | None, Field(
                     description="For distance joints")] = None,
                 angle: Annotated[float | None, Field(description="For angle joints")] = None,
                 assembly: Assembly = None, label: str | None = None,
                 document: Doc = None) -> dict[str, Any]:
    """Join two parts (Fusion: Joint): b is moved so its element lines up with a's, then
    the assembly is solved. Returns every part's new position."""
    return client.call("create_joint", type=type, a=a, b=b, offset=offset,
                       rotation=rotation, distance=distance, angle=angle,
                       assembly=assembly, label=label, document=document)


@mcp.tool()
def solve_assembly(assembly: Assembly = None, document: Doc = None) -> dict[str, Any]:
    """Re-solve an assembly's joints, e.g. after editing a part or a joint property."""
    return client.call("solve_assembly", assembly=assembly, document=document)


@mcp.tool()
def get_assembly(assembly: Assembly = None, document: Doc = None) -> dict[str, Any]:
    """Parts (position, rotation, grounded) and joints of an assembly."""
    return client.call("get_assembly", assembly=assembly, document=document)


# --- other add-ons (need the FreeCAD GUI) ----------------------------------------

@mcp.tool()
def list_addons() -> dict[str, Any]:
    """Which supporting add-ons (Fasteners, SheetMetal, Gears, ...) are installed."""
    return client.call("list_addons")


@mcp.tool()
def insert_fastener(
    type: Annotated[str, Field(
        description="Fasteners standard: ISO4762 socket cap, ISO7380-1 button head, "
                    "ISO10642 countersunk, ISO4017 hex screw, ISO4032 nut, ISO7089 "
                    "washer, ... (any FS<type> command of the Fasteners add-on)")] = "ISO4762",
    diameter: Annotated[str | None, Field(description="e.g. 'M4'; default matches the hole")] = None,
    length: Annotated[float | None, Field(description="Screw length in mm (standard sizes)")] = None,
    hole: Annotated[str | None, Field(
        description="Circular edge of a hole to seat it in, e.g. 'Pocket:Edge14' "
                    "(get_topology); the fastener is placed and sized for it")] = None,
    position: Annotated[list[float] | None, Field(description="[x, y, z] when no hole")] = None,
    invert: bool = False,
    document: Doc = None,
) -> dict[str, Any]:
    """Insert a standard screw, nut or washer (Fusion: Insert > McMaster-Carr)."""
    return client.call("insert_fastener", type=type, diameter=diameter, length=length,
                       hole=hole, position=position, invert=invert, document=document)


@mcp.tool()
def create_gear(kind: Literal["involute", "internal", "rack", "bevel", "worm", "timing",
                              "cycloid", "crown"] = "involute",
                teeth: int | None = None,
                module: Annotated[float | None, Field(description="Gear module in mm")] = None,
                height: Annotated[float | None, Field(description="Face width in mm")] = None,
                position: list[float] | None = None,
                in_body: Annotated[bool, Field(
                    description="Add to the active PartDesign body instead of creating "
                                "a separate part")] = False,
                document: Doc = None) -> dict[str, Any]:
    """Create a parametric gear (Gears add-on), as its own part by default."""
    return client.call("create_gear", kind=kind, teeth=teeth, module=module, height=height,
                       position=position, in_body=in_body, document=document)


@mcp.tool()
def sheet_metal_base(sketch: str, thickness: float | None = None,
                     radius: Annotated[float | None, Field(description="Bend radius")] = None,
                     document: Doc = None) -> dict[str, Any]:
    """Turn a closed sketch into a sheet metal base plate (SheetMetal add-on)."""
    return client.call("sheet_metal_base", sketch=sketch, thickness=thickness,
                       radius=radius, document=document)


@mcp.tool()
def sheet_metal_flange(edges: Annotated[list[str], Field(
                           description="Edges of the sheet to bend up, e.g. ['BaseBend:Edge4']")],
                       length: float | None = None,
                       angle: Annotated[float | None, Field(description="Degrees")] = None,
                       radius: float | None = None,
                       document: Doc = None) -> dict[str, Any]:
    """Add a bent flange (wall) along sheet metal edges (Fusion: Flange)."""
    return client.call("sheet_metal_flange", edges=edges, length=length, angle=angle,
                       radius=radius, document=document)


@mcp.tool()
def sheet_metal_unfold(face: Annotated[str | None, Field(
                           description="Face that stays fixed, e.g. 'Bend:Face3'")] = None,
                       base: Annotated[str | None, Field(
                           description="Or: the sheet metal feature; its largest flat "
                                       "face is used")] = None,
                       document: Doc = None) -> dict[str, Any]:
    """Create the flat pattern of a sheet metal part (Fusion: Create Flat Pattern).
    Export it with export(path='....step', objects=[flat_pattern])."""
    return client.call("sheet_metal_unfold", face=face, base=base, document=document)


@mcp.tool()
def list_commands(filter: Annotated[str, Field(
                      description="Text to search in command names and menu text")] = "",
                  limit: int = 100) -> dict[str, Any]:
    """Find FreeCAD GUI commands, including other add-ons' tools, for run_command."""
    return client.call("list_commands", filter=filter, limit=limit)


@mcp.tool()
def run_command(command: str,
                selection: Annotated[list[str] | None, Field(
                    description="Objects or sub-elements to select first, e.g. "
                                "['Pad', 'Pad:Face6']")] = None,
                accept_dialog: Annotated[bool, Field(
                    description="Press OK on the task panel the command opens")] = True,
                document: Doc = None) -> dict[str, Any]:
    """Run any FreeCAD GUI command (any workbench or add-on) as if clicked in the UI,
    after selecting the given objects. Returns the objects it created. Use set_property
    afterwards to adjust them. Prefer a dedicated tool when there is one."""
    return client.call("run_command", command=command, selection=selection,
                       accept_dialog=accept_dialog, document=document)


# --- view --------------------------------------------------------------------

View = Literal["isometric", "front", "back", "top", "bottom", "left", "right"]


@mcp.tool()
def set_view(view: View = "isometric", fit: bool = True) -> dict[str, Any]:
    """Orient the 3D view (GUI only)."""
    return client.call("set_view", view=view, fit=fit)


@mcp.tool()
def screenshot(view: View | None = None, width: int = 1024, height: int = 768,
               fit: bool = True) -> Image:
    """Capture the 3D view as a PNG to check the model visually (GUI only)."""
    result = client.call("screenshot", view=view, width=width, height=height, fit=fit)
    return Image(data=base64.b64decode(result["png_base64"]), format="png")


# --- files -------------------------------------------------------------------

@mcp.tool()
def export(path: Annotated[str, Field(
               description="Absolute output path; format from the extension: "
                           ".step .stp .iges .igs .stl .obj .brep .FCStd .dxf (2D: "
                           "the largest flat face of each object, e.g. a sheet metal "
                           "flat pattern, for laser cutting)")],
           objects: Annotated[list[str] | None, Field(
               description="Objects to export; defaults to all bodies")] = None,
           document: Doc = None) -> dict[str, Any]:
    """Export geometry to a file."""
    return client.call("export", path=path, objects=objects, document=document)


@mcp.tool()
def import_file(path: str, document: Doc = None) -> dict[str, Any]:
    """Import a STEP, IGES, BREP, STL or OBJ file into a document."""
    return client.call("import_file", path=path, document=document)


# --- escape hatch ------------------------------------------------------------

@mcp.tool()
def run_python(code: Annotated[str, Field(
        description="Python run inside FreeCAD. Available: App/FreeCAD, Gui/FreeCADGui "
                    "(None when headless), doc (active document). Assign to `result` "
                    "to return a value; print() output is returned too.")],
        document: Doc = None) -> dict[str, Any]:
    """Run Python inside FreeCAD for anything the other tools don't cover. Runs as one
    undo step."""
    return client.call("run_python", code=code, document=document)


# --- resources: the model's state, readable without a tool call ------------------

def _json(value):
    return json.dumps(value, indent=1)


@mcp.resource("freecad://documents", mime_type="application/json",
              description="Open documents and which one is active")
def documents_resource() -> str:
    return _json(client.call("list_documents"))


@mcp.resource("freecad://{document}/objects", mime_type="application/json",
              description="A document's objects: bodies, features, sketches, datums")
def objects_resource(document: str) -> str:
    return _json(client.call("list_objects", document=document))


@mcp.resource("freecad://{document}/timeline", mime_type="application/json",
              description="The active body's feature history")
def timeline_resource(document: str) -> str:
    return _json(client.call("get_timeline", document=document))


@mcp.resource("freecad://{document}/parameters", mime_type="application/json",
              description="User parameters and every expression in the document")
def parameters_resource(document: str) -> str:
    return _json(client.call("get_parameters", document=document))


# --- prompts: workflows the user can pick ------------------------------------

@mcp.prompt(title="Model a part", description="Build a parametric part from a description")
def model_part(description: str) -> str:
    return f"""Model this part in FreeCAD: {description}

Work like a careful CAD user:
1. Pick the main sizes and set them as parameters (set_parameters), so they can be
   changed later. Ask me if a size that matters is missing; assume the rest and say so.
2. Build it feature by feature: sketch on a plane or face, then pad / pocket / revolve /
   hole. Tie sketch dimensions and lengths to the parameters with expressions.
3. Add fillets and chamfers last (get_topology for the edge names, fresh each time).
4. After each feature, check the result has no "errors"; screenshot when it helps.
5. Finish with check_geometry, a screenshot from isometric, and a short summary of the
   features and the parameters I can change."""


@mcp.prompt(title="Prepare for 3D printing",
            description="Check a body and export it as STL for printing")
def prepare_for_print(body: str = "Body", material: str = "PLA") -> str:
    return f"""Get {body} ready to 3D print in {material}:
1. check_geometry on {body}: it must be one valid, closed solid. Fix or report problems.
2. If the document has several bodies or an assembly, run interference.
3. set_material {material}, then mass_properties: report mass, size (bounding box) and
   volume.
4. Look for things that print badly: walls thinner than 0.8 mm, unsupported overhangs
   past 45 degrees, tiny holes. Use measure where needed and screenshot to look. Suggest
   fixes, but ask before changing the model.
5. Export {body} as STL next to the document (or where I say) and tell me the path."""


@mcp.prompt(title="Review the model",
            description="Look over the open document and suggest improvements")
def review_model() -> str:
    return """Review the active FreeCAD document:
1. list_objects and get_timeline: what is modelled, in which order.
2. Any feature with errors? check_geometry on each body.
3. get_parameters: are the main sizes parameters, or typed-in numbers that should be?
   Are sketches fully constrained (get_object on each sketch)?
4. Screenshot from a couple of views.
Then summarise what the model is, what's fragile (e.g. edges picked by name that will
renumber, unconstrained sketches), and what you'd change. Don't change anything yet."""


def main():
    mcp.run()


if __name__ == "__main__":
    main()
