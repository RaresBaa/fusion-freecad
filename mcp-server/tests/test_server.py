"""Checks on the MCP tool definitions themselves (no FreeCAD needed)."""

import asyncio

from fusion_freecad_mcp.server import mcp


def test_tools_registered():
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in ["freecad_status", "create_sketch", "pad", "pocket", "fillet",
                 "get_topology", "screenshot", "export", "run_python"]:
        assert name in tools
    sketch_schema = tools["create_sketch"].input_schema
    assert "geometry" in sketch_schema["required"]
    assert "rectangle" in sketch_schema["properties"]["geometry"]["description"]
