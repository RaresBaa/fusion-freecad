"""Fusion FreeCAD: a Fusion 360-style workflow and an MCP bridge for FreeCAD."""

import os

__version__ = "0.1.0"

ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(ADDON_DIR, "Resources", "icons")
PREFS_PATH = "User parameter:BaseApp/Preferences/Mod/FusionFreeCAD"


def icon(name):
    return os.path.join(ICON_DIR, name)


def prefs():
    import FreeCAD
    return FreeCAD.ParamGet(PREFS_PATH)
