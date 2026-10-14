import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fusion_freecad_mcp.client import BridgeError, FreeCADClient

REPO = Path(__file__).resolve().parents[2]
ADDON = REPO / "addon" / "FusionFreeCAD"


def find_freecadcmd():
    candidates = [os.environ.get("FREECADCMD"), shutil.which("freecadcmd"),
                  shutil.which("FreeCADCmd")]
    if sys.platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidates += sorted((str(p) for p in program_files.glob("FreeCAD*/bin/freecadcmd.exe")),
                             reverse=True)
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


@pytest.fixture(scope="session")
def freecad(tmp_path_factory):
    """A headless FreeCAD running the bridge, plus a client connected to it."""
    exe = find_freecadcmd()
    if not exe:
        pytest.skip("freecadcmd not found (set FREECADCMD)")
    rpc_file = tmp_path_factory.mktemp("bridge") / "rpc.json"
    env = dict(os.environ, FUSION_FREECAD_ADDON=str(ADDON),
               FUSION_FREECAD_RPC_FILE=str(rpc_file), FUSION_FREECAD_PORT="0")
    log = open(rpc_file.parent / "freecad.log", "w")
    proc = subprocess.Popen([exe, str(Path(__file__).parent / "headless_bridge.py")],
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    client = FreeCADClient(rpc_file)
    deadline = time.monotonic() + 60
    while True:
        if rpc_file.exists():
            try:
                client.call("ping")
                break
            except BridgeError:
                pass
        if proc.poll() is not None or time.monotonic() > deadline:
            proc.kill()
            log.close()
            pytest.fail("headless FreeCAD bridge didn't start:\n"
                        + (rpc_file.parent / "freecad.log").read_text(errors="replace"))
        time.sleep(0.2)
    yield client
    try:
        client.call("shutdown")
        proc.wait(timeout=30)
    except Exception:
        proc.kill()
    log.close()
