"""Fusion 360 single-key shortcuts, active only in Fusion mode (see session.py).

FreeCAD shortcuts are global and saved in user settings, so they are applied when
Fusion mode starts and the previous ones restored when it ends. The originals are
kept in preferences, not memory, so that if FreeCAD quits in Fusion mode the next
startup can still restore them.

FreeCAD's sketcher already uses most single letters for constraints (C coincident,
L horizontal distance, P parallel, E equal, H horizontal, ...). Those only work while
a sketch is open and our part-level commands (E, F, H) only work outside one, so the
two sets coexist. Fusion's sketch keys that clash (L, C, P) are only bound when
"OverrideSketcherKeys" is enabled, which moves FreeCAD's constraints off those keys.
S opens SearchBar's search box at the mouse (Fusion's S toolbox). FreeCAD uses S as
the first key of two-key shortcuts (S, B select back; S, G link select; ...), which
would make a bare S ambiguous, so those are unbound in Fusion mode and restored after.
T is never bound: FreeCAD's tree view commands use it the same way.
"""

import json

import FreeCADGui as Gui

from . import prefs

# key -> command. Fusion's name in comments where it differs.
PART_KEYS = {
    "E": "PartDesign_Pad",               # Extrude
    "F": "PartDesign_Fillet",
    "H": "PartDesign_Hole",
    "Q": "FusionFreeCAD_PressPull",      # Press Pull
}

SEARCH_KEYS = {
    "S": "FusionFreeCAD_SearchAtCursor",  # S toolbox (needs the SearchBar add-on)
}

SKETCH_KEYS = {  # keys FreeCAD's sketcher doesn't use
    "R": "Sketcher_CreateRectangle",     # 2-point rectangle
    "D": "Sketcher_Dimension",           # Sketch dimension
    "X": "Sketcher_ToggleConstruction",  # Normal / construction
    "O": "Sketcher_Offset",
}

SKETCH_OVERRIDE_KEYS = {  # keys taken from FreeCAD's sketcher constraints
    "L": "Sketcher_CreatePolyline",      # Line (chains segments, like Fusion's)
    "C": "Sketcher_CreateCircle",        # Center diameter circle
    "P": "Sketcher_Projection",          # Project / include
}


def enabled():
    return prefs().GetBool("FusionShortcuts", True)


def set_enabled(value):
    prefs().SetBool("FusionShortcuts", bool(value))
    if value:
        apply()
    else:
        restore()


def override_sketcher_keys():
    return prefs().GetBool("OverrideSketcherKeys", False)


def set_override_sketcher_keys(value):
    # Restore first so keys bound under the old setting are released.
    restore()
    prefs().SetBool("OverrideSketcherKeys", bool(value))
    apply()


def _load_saved():
    raw = prefs().GetString("SavedShortcuts", "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _store_saved(saved):
    prefs().SetString("SavedShortcuts", json.dumps(saved))


def active():
    return _load_saved() is not None


def _bind(mapping, saved, take_over=False):
    """Bind keys, recording each changed command's previous shortcut in ``saved``.

    With take_over, commands already using one of the keys, or a two-key sequence
    starting with it ("S, B"), are unbound first. take_over="sequences" only unbinds
    the sequences (they'd make the bare key wait for a second one) and leaves other
    commands on the bare key alone (the sketcher's S); FreeCAD picks the active one.
    """
    known = set(Gui.listCommands())
    if take_over:
        for name in known:
            if name in saved:
                continue
            current = Gui.Command.get(name).getShortcut()
            if take_over == "sequences" and "," not in current:
                continue
            first = current.split(",")[0].strip()
            if first in mapping and mapping[first] != name:
                saved[name] = current
                Gui.Command.get(name).setShortcut("")
    for key, name in mapping.items():
        if name not in known:
            continue
        cmd = Gui.Command.get(name)
        if cmd.getShortcut() == key:
            continue
        saved.setdefault(name, cmd.getShortcut())
        cmd.setShortcut(key)


def apply():
    """Bind the part-level keys. Sketch keys follow in apply_sketch()."""
    if not enabled():
        return
    saved = _load_saved()
    if saved is None:
        saved = {}
    _bind(PART_KEYS, saved)
    if "SearchBar" in Gui.listCommands():
        _bind(SEARCH_KEYS, saved, take_over="sequences")
    _store_saved(saved)


_sketch_bound = False


def apply_sketch():
    """Bind the sketch keys. Call while a sketch is being edited (actions exist then)."""
    global _sketch_bound
    if _sketch_bound or not enabled():
        return
    saved = _load_saved()
    if saved is None:
        saved = {}
    _bind(SKETCH_KEYS, saved)
    if override_sketcher_keys():
        _bind(SKETCH_OVERRIDE_KEYS, saved, take_over=True)
    _store_saved(saved)
    _sketch_bound = True


def restore():
    global _sketch_bound
    _sketch_bound = False
    saved = _load_saved()
    if saved is None:
        return
    import FreeCAD

    known = set(Gui.listCommands())
    stored = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Shortcut")
    for name, shortcut in saved.items():
        if name in known:
            Gui.Command.get(name).setShortcut(shortcut)
        # Commands of workbenches not loaded yet (e.g. Sketcher at startup) can't be
        # reached through the API; fix the stored setting they will load from.
        elif shortcut:
            stored.SetString(name, shortcut)
        else:
            stored.RemString(name)
    prefs().RemString("SavedShortcuts")
