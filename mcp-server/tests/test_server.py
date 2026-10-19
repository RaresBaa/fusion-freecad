"""Checks on the MCP tool definitions themselves (no FreeCAD needed)."""

import asyncio

from fusion_freecad_mcp.server import mcp


def test_tools_registered():
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in ["freecad_status", "create_sketch", "pad", "pocket", "fillet",
                 "get_topology", "screenshot", "export", "run_python", "hole", "shell",
                 "mirror", "linear_pattern", "polar_pattern", "loft", "sweep",
                 "measure", "set_dimension", "delete_sketch_geometry",
                 "move_sketch_geometry", "set_parameters", "get_parameters",
                 "set_expression"]:
        assert name in tools
    tool = tools["create_sketch"]
    sketch_schema = getattr(tool, "input_schema", None) or tool.inputSchema  # mcp 2.x / 1.x
    assert "geometry" in sketch_schema["required"]
    assert "rectangle" in sketch_schema["properties"]["geometry"]["description"]
