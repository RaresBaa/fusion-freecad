"""Starts and stops the RPC server inside FreeCAD and pumps its queue on the main thread."""

import FreeCAD as App

from . import prefs
from .rpc import DEFAULT_PORT, RpcServer

_server = None
_timer = None


def port_preference():
    return prefs().GetInt("ServerPort", DEFAULT_PORT) or DEFAULT_PORT


def is_running():
    return _server is not None and _server.running


def start(port=None):
    """Start the bridge in the GUI. Calls are executed from a Qt timer."""
    global _server, _timer
    if is_running():
        return _server.address
    from PySide import QtCore

    from .handlers import HANDLERS

    server = RpcServer(HANDLERS, port=port or port_preference())
    try:
        server.start()
    except OSError as e:
        App.Console.PrintError(
            "Fusion FreeCAD: could not start the MCP bridge on port %d: %s\n"
            % (server.address[1], e))
        return None
    timer = QtCore.QTimer()
    timer.timeout.connect(server.process_pending)
    timer.start(25)
    _server, _timer = server, timer
    # Remove rpc.json on exit so clients report "not running" instead of a dead port.
    app = QtCore.QCoreApplication.instance()
    if app is not None and not getattr(start, "_quit_hooked", False):
        app.aboutToQuit.connect(stop)
        start._quit_hooked = True
    App.Console.PrintMessage(
        "Fusion FreeCAD: MCP bridge listening on %s:%d\n" % server.address)
    return server.address


def stop():
    global _server, _timer
    if _timer is not None:
        _timer.stop()
        _timer = None
    if _server is not None:
        _server.stop()
        _server = None
        App.Console.PrintMessage("Fusion FreeCAD: MCP bridge stopped\n")


def serve_headless(port=0, idle_timeout=None):
    """Run the bridge in freecadcmd until a client calls ``shutdown``.

    Used for tests and for driving FreeCAD without a GUI.
    """
    import time

    from .handlers import HANDLERS

    stopping = []

    def shutdown():
        stopping.append(True)
        return {"stopping": True}

    handlers = dict(HANDLERS, shutdown=shutdown)
    server = RpcServer(handlers, port=port)
    server.start()
    App.Console.PrintMessage("Fusion FreeCAD: headless bridge on %s:%d\n" % server.address)
    started = time.monotonic()
    try:
        while not stopping:
            server.process_pending(timeout=0.1)
            if idle_timeout and time.monotonic() - started > idle_timeout:
                break
    finally:
        server.stop()
