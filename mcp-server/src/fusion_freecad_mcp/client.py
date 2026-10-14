"""Client for the JSON-lines RPC bridge running inside FreeCAD.

The bridge publishes its port and a random token in ``~/.fusion-freecad/rpc.json``
(override with ``FUSION_FREECAD_RPC_FILE``). The file is re-read on every call, so
restarting FreeCAD doesn't require restarting the MCP server.
"""

import itertools
import json
import os
import socket
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp.exceptions import ToolError

CONNECT_TIMEOUT = 5.0
CALL_TIMEOUT = 330.0  # a bit longer than the bridge's own 300 s limit


class BridgeError(ToolError):
    """FreeCAD reported an error, or the bridge couldn't be reached.

    A ToolError so the MCP SDK shows the message to the agent; other exceptions
    are reported only as "Error executing tool <name>".
    """


def rpc_file():
    override = os.environ.get("FUSION_FREECAD_RPC_FILE")
    if override:
        return Path(override)
    return Path.home() / ".fusion-freecad" / "rpc.json"


class FreeCADClient:
    def __init__(self, path=None):
        self._path = Path(path) if path else None
        self._ids = itertools.count(1)

    def _connection_info(self):
        path = self._path or rpc_file()
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise BridgeError(
                "FreeCAD bridge is not running. In FreeCAD, switch to the 'Fusion' "
                "workbench and press 'Start MCP bridge' (or enable auto-start in the "
                "Fusion menu).") from None
        except ValueError as e:
            raise BridgeError("unreadable bridge info in %s: %s" % (path, e)) from None

    def call(self, method, **params):
        info = self._connection_info()
        params = {k: v for k, v in params.items() if v is not None}
        request = {"id": next(self._ids), "token": info["token"],
                   "method": method, "params": params}
        try:
            with socket.create_connection((info["host"], info["port"]),
                                          timeout=CONNECT_TIMEOUT) as sock:
                sock.settimeout(CALL_TIMEOUT)
                sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
                response = _read_line(sock)
        except ConnectionRefusedError:
            raise BridgeError(
                "FreeCAD bridge isn't answering on port %s. Is FreeCAD still running? "
                "Restart the bridge from the Fusion workbench." % info["port"]) from None
        except socket.timeout:
            raise BridgeError("timed out waiting for FreeCAD") from None

        message = json.loads(response)
        if "error" in message:
            err = message["error"]
            text = "%s: %s" % (err.get("type", "Error"), err.get("message", ""))
            if err.get("traceback") and err.get("type") not in ("HandlerError",):
                text += "\n" + err["traceback"]
            raise BridgeError(text)
        return message["result"]


def _read_line(sock):
    chunks = []
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        if chunk.endswith(b"\n"):
            break
    data = b"".join(chunks)
    if not data:
        raise BridgeError("FreeCAD closed the connection without answering")
    return data.decode("utf-8")
