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
                 "set_expression", "create_assembly", "insert_part", "create_joint",
                 "get_assembly", "move_feature"]:
        assert name in tools
    tool = tools["create_sketch"]
    sketch_schema = getattr(tool, "input_schema", None) or tool.inputSchema  # mcp 2.x / 1.x
    assert "geometry" in sketch_schema["required"]
    assert "rectangle" in sketch_schema["properties"]["geometry"]["description"]


def test_resources_and_prompts():
    resources = [str(r.uri) for r in asyncio.run(mcp.list_resources())]
    assert "freecad://documents" in resources
    templates = [getattr(t, "uri_template", None) or t.uriTemplate
                 for t in asyncio.run(mcp.list_resource_templates())]
    assert {"freecad://{document}/objects", "freecad://{document}/timeline",
            "freecad://{document}/parameters"} <= set(templates)
    prompts = {p.name for p in asyncio.run(mcp.list_prompts())}
    assert {"model_part", "prepare_for_print", "review_model"} <= prompts
    result = asyncio.run(mcp.get_prompt("prepare_for_print", {"body": "Bracket"}))
    text = result.messages[0].content.text
    assert "Bracket" in text and "PLA" in text and "check_geometry" in text
