# Architecture

```
Claude Code ──MCP (stdio)──▶ fusion-freecad-mcp ──JSON lines over TCP──▶ bridge in FreeCAD
                             (mcp-server/, any Python)   127.0.0.1 + token   (addon/, FreeCAD's Python)
```

There are two processes because FreeCAD ships its own Python (3.11 in FreeCAD 1.1) and
we don't want to install the MCP SDK and its dependencies into it. The bridge inside
FreeCAD uses only the standard library; everything MCP-specific lives in `mcp-server/`.

## The bridge (`addon/FusionFreeCAD/fusion_freecad/`)

| File | Role |
|---|---|
| `rpc.py` | TCP server, auth, request queue. No FreeCAD imports, so it is easy to reason about |
| `handlers.py` | The operations (sketch, pad, fillet, export, ...). This is where CAD logic goes |
| `bridge.py` | Starts/stops the server in the GUI, or runs it headless for tests |
| `commands.py` | FreeCAD GUI commands (start/stop bridge, auto-start toggle) |
| `workbench.py` | Toolbar layout of the Fusion workbench |
| `../InitGui.py` | Registers the workbench and runs auto-start at FreeCAD launch |

### Threading

FreeCAD's document and GUI APIs must only be used from the main thread. The TCP
server runs on background threads that only parse requests, check the token and put
calls on a queue. In the GUI a `QTimer` drains the queue every 25 ms on the main
thread; headless, `bridge.serve_headless()` drains it in a loop. The network thread
waits up to 300 s for the result (a modal dialog left open in FreeCAD blocks calls).

### Protocol

One JSON object per line:

```json
{"id": 1, "token": "<from rpc.json>", "method": "pad", "params": {"sketch": "Sketch", "length": 5}}
{"id": 1, "result": {"feature": "Pad", "body": "Body", "shape": {"volume": 4000.0}}}
{"id": 1, "error": {"type": "HandlerError", "message": "no object 'Skech' in document 'Unnamed'"}}
```

On start the bridge writes `~/.fusion-freecad/rpc.json` (`host`, `port`, `token`,
`pid`, `protocol`), and deletes it when it stops or FreeCAD quits. The MCP server
re-reads it on every call, so FreeCAD can be restarted without restarting the agent.
`FUSION_FREECAD_RPC_FILE` overrides the location (tests use this to run in isolation).

### Undo and errors

Every modelling handler is wrapped by `_mutating()` in `handlers.py`: it opens a
document transaction, runs, recomputes and commits. If the handler raises, the
transaction is aborted, so a failed call leaves nothing half-built. Features that
fail to recompute don't raise; they are listed under `"errors"` in the result so the
agent can see them and decide to undo or fix them.

`HandlerError` marks expected, user-facing errors (bad arguments, missing objects);
the MCP client shows just the message. Other exceptions include a traceback.

## The MCP server (`mcp-server/src/fusion_freecad_mcp/`)

`server.py` defines the tools with the `mcp` SDK (2.x, `MCPServer`). Each tool is a
thin wrapper that calls the handler of the same name, adding typed parameters and
descriptions for the agent. `client.py` is the bridge client.

To add an operation: write the handler in `handlers.py`, add it to `HANDLERS`, add a
tool in `server.py`, and add a test in `mcp-server/tests/test_bridge.py`.
