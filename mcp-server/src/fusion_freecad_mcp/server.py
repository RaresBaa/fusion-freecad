"""MCP server exposing FreeCAD modelling tools.

Each tool forwards to the RPC bridge inside a running FreeCAD (see client.py);
the real work happens in addon/FusionFreeCAD/fusion_freecad/handlers.py.
"""

import base64
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Image, MCPServer
from pydantic import Field

from .client import FreeCADClient

INSTRUCTIONS = """\
Drive a live FreeCAD session for parametric part modelling (PartDesign).

Units are millimetres and degrees. Typical flow:
  new_document -> create_sketch (on XY/XZ/YZ or on a face like "Pad:Face6")
  -> pad / pocket / revolve -> get_topology to find edge names -> fillet / chamfer
  -> screenshot to check the result -> export (STEP/STL).

Sketch geometry indices start at 0 in the order shapes are added; a rectangle or
polygon adds one line per side. Face and edge names (Face1, Edge7) come from
get_topology and can change after earlier features are edited, so look them up again
rather than reusing old names. Each modelling tool is one undo step in FreeCAD.
If a tool result contains "errors", a feature failed to recompute: inspect it, then
undo or fix it. Use run_python only when no dedicated tool fits.
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
    plane: Annotated[Literal["XY", "XZ", "YZ"], Field(
        description="Body origin plane to sketch on (ignored when face is given)")] = "XY",
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


@mcp.tool()
def pad(sketch: str, length: float = 10.0, reversed: bool = False, midplane: bool = False,
        up_to_face: Annotated[str | None, Field(
            description="Extrude up to this face instead of a length, e.g. 'Pad:Face3'")] = None,
        label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Extrude a sketch to add material (Fusion: Extrude / Join)."""
    return client.call("pad", sketch=sketch, length=length, reversed=reversed,
                       midplane=midplane, up_to_face=up_to_face, label=label,
                       document=document)


@mcp.tool()
def pocket(sketch: str, length: float = 10.0, through_all: bool = False,
           reversed: bool = False, midplane: bool = False, label: str | None = None,
           document: Doc = None) -> dict[str, Any]:
    """Extrude a sketch to cut material (Fusion: Extrude / Cut). By default cuts into the
    solid, opposite the sketch normal; use reversed if it cuts into empty space."""
    return client.call("pocket", sketch=sketch, length=length, through_all=through_all,
                       reversed=reversed, midplane=midplane, label=label, document=document)


@mcp.tool()
def revolve(sketch: str, angle: float = 360.0,
            axis: Annotated[Literal["V", "H", "X", "Y", "Z"], Field(
                description="V/H = sketch vertical/horizontal axis; X/Y/Z = body axes")] = "V",
            groove: Annotated[bool, Field(description="Cut instead of adding material")] = False,
            label: str | None = None, document: Doc = None) -> dict[str, Any]:
    """Revolve a sketch around an axis (Fusion: Revolve)."""
    return client.call("revolve", sketch=sketch, angle=angle, axis=axis, groove=groove,
                       label=label, document=document)


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
def set_property(name: str, property: str, value: Any, document: Doc = None) -> dict[str, Any]:
    """Change a property of an object, e.g. a Pad's Length, then recompute. Use
    get_object to see available properties."""
    return client.call("set_property", name=name, property=property, value=value,
                       document=document)


@mcp.tool()
def delete_object(name: str, document: Doc = None) -> dict[str, Any]:
    """Delete an object (removing it from its body first)."""
    return client.call("delete_object", name=name, document=document)


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
                           ".step .stp .iges .igs .stl .obj .brep .FCStd")],
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


def main():
    mcp.run()


if __name__ == "__main__":
    main()
