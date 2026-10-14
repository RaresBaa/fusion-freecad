# Run with freecadcmd to start the bridge without a GUI (used by the integration tests):
#   FUSION_FREECAD_ADDON=<repo>/addon/FusionFreeCAD freecadcmd headless_bridge.py
# Settings come from environment variables because freecadcmd doesn't pass script args.

import os
import sys

sys.path.insert(0, os.environ["FUSION_FREECAD_ADDON"])

from fusion_freecad import bridge  # noqa: E402

bridge.serve_headless(port=int(os.environ.get("FUSION_FREECAD_PORT", "0")),
                      idle_timeout=float(os.environ.get("FUSION_FREECAD_IDLE_TIMEOUT", "300")))
