"""Local JSON-lines RPC server that lets external tools (the MCP server) drive FreeCAD.

Protocol: one JSON object per line over TCP, bound to 127.0.0.1 only.

    request:  {"id": 1, "token": "...", "method": "pad", "params": {...}}
    response: {"id": 1, "result": {...}}
           or {"id": 1, "error": {"type": "...", "message": "...", "traceback": "..."}}

FreeCAD's document and GUI APIs are not thread-safe, so the network thread never
touches them. It queues each call, and the owner of the server drains the queue on
the main thread by calling ``process_pending()`` (from a Qt timer in the GUI, or a
blocking loop when running headless).
"""

import hmac
import json
import os
import queue
import secrets
import socketserver
import threading
import traceback
from pathlib import Path

PROTOCOL_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9875


def default_rpc_file():
    """Where the server publishes its port and token for clients to find."""
    override = os.environ.get("FUSION_FREECAD_RPC_FILE")
    if override:
        return Path(override)
    return Path.home() / ".fusion-freecad" / "rpc.json"


class HandlerError(Exception):
    """An expected, user-facing error (bad arguments, missing object, ...)."""


class _Call:
    __slots__ = ("method", "params", "done", "cancelled", "result", "error")

    def __init__(self, method, params):
        self.method = method
        self.params = params
        self.done = threading.Event()
        self.cancelled = False
        self.result = None
        self.error = None


class _TCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self):
        rpc = self.server.rpc
        for raw in self.rfile:
            line = raw.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("request must be a JSON object")
            except ValueError as e:
                response = _error_response(None, "ParseError", str(e))
            else:
                response = rpc.handle_request(request)
            data = json.dumps(response, default=_json_fallback)
            self.wfile.write(data.encode("utf-8") + b"\n")
            self.wfile.flush()


def _json_fallback(value):
    return repr(value)


def _error_response(request_id, error_type, message, tb=None):
    error = {"type": error_type, "message": message}
    if tb:
        error["traceback"] = tb
    return {"id": request_id, "error": error}


class RpcServer:
    def __init__(self, handlers, host=DEFAULT_HOST, port=DEFAULT_PORT,
                 rpc_file=None, call_timeout=300.0):
        self._handlers = handlers
        self._host = host
        self._port = port
        self._rpc_file = Path(rpc_file) if rpc_file else default_rpc_file()
        self._call_timeout = call_timeout
        self._queue = queue.Queue()
        self._token = None
        self._server = None
        self._thread = None

    @property
    def running(self):
        return self._server is not None

    @property
    def address(self):
        return (self._host, self._port)

    def start(self):
        if self._server:
            return
        server = _TCPServer((self._host, self._port), _RequestHandler)
        server.rpc = self
        # Port 0 means "pick a free one"; report what we actually got.
        self._port = server.server_address[1]
        self._token = secrets.token_urlsafe(32)
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, name="FusionFreeCAD-RPC", daemon=True)
        self._thread.start()
        self._write_rpc_file()

    def stop(self):
        server, self._server = self._server, None
        if not server:
            return
        server.shutdown()
        server.server_close()
        self._remove_rpc_file()
        # Release anyone still waiting on a queued call.
        while True:
            try:
                call = self._queue.get_nowait()
            except queue.Empty:
                break
            call.error = {"type": "ServerStopped", "message": "FreeCAD bridge stopped"}
            call.done.set()

    def process_pending(self, timeout=0.0):
        """Run queued calls. Must be called on FreeCAD's main thread."""
        block = timeout > 0
        while True:
            try:
                call = self._queue.get(block=block, timeout=timeout if block else None)
            except queue.Empty:
                return
            block = False
            if call.cancelled:
                continue
            self._execute(call)

    def handle_request(self, request):
        """Called on a network thread."""
        request_id = request.get("id")
        token = request.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(token, self._token or ""):
            return _error_response(request_id, "AuthError", "invalid or missing token")
        method = request.get("method")
        if method not in self._handlers:
            return _error_response(request_id, "UnknownMethod", "unknown method: %r" % (method,))
        params = request.get("params") or {}
        if not isinstance(params, dict):
            return _error_response(request_id, "InvalidParams", "params must be an object")

        call = _Call(method, params)
        self._queue.put(call)
        if not call.done.wait(self._call_timeout):
            call.cancelled = True
            return _error_response(
                request_id, "Timeout",
                "FreeCAD did not answer within %ds (busy, or a modal dialog is open?)"
                % self._call_timeout)
        if call.error:
            return {"id": request_id, "error": call.error}
        return {"id": request_id, "result": call.result}

    def _execute(self, call):
        try:
            call.result = self._handlers[call.method](**call.params)
        except HandlerError as e:
            call.error = {"type": "HandlerError", "message": str(e)}
        except TypeError as e:
            # Most often a wrong or missing parameter name.
            call.error = {"type": "InvalidParams", "message": str(e),
                          "traceback": traceback.format_exc()}
        except Exception as e:
            call.error = {"type": type(e).__name__, "message": str(e),
                          "traceback": traceback.format_exc()}
        finally:
            call.done.set()

    def _write_rpc_file(self):
        self._rpc_file.parent.mkdir(parents=True, exist_ok=True)
        info = {
            "host": self._host,
            "port": self._port,
            "token": self._token,
            "pid": os.getpid(),
            "protocol": PROTOCOL_VERSION,
        }
        tmp = self._rpc_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(info), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self._rpc_file)

    def _remove_rpc_file(self):
        # Only remove it if it still describes us; another FreeCAD may have taken over.
        try:
            info = json.loads(self._rpc_file.read_text(encoding="utf-8"))
            if info.get("token") == self._token:
                self._rpc_file.unlink()
        except (OSError, ValueError):
            pass
