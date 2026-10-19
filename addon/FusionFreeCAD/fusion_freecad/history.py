"""The feature history of a PartDesign body, seen as a Fusion-style timeline.

The timeline is the body's Group in order. The rollback marker sits right after the
body's Tip: features after it are "rolled back" (not part of the body's shape), and
new features are inserted at the marker. Only solid features can be the Tip, so
rolling to a sketch or datum puts the Tip on the nearest solid feature before it.

No Qt here, so it works headless and backs both the timeline widget and the RPC tools.
"""

import FreeCAD as App


def is_feature(obj):
    """A solid PartDesign feature (Pad, Pocket, Fillet...), i.e. something that can be Tip."""
    return obj.isDerivedFrom("PartDesign::Feature")


def kind(obj):
    if obj.isDerivedFrom("Sketcher::SketchObject"):
        return "sketch"
    if is_feature(obj):
        return "feature"
    if obj.TypeId.startswith("PartDesign::") and obj.TypeId != "PartDesign::Body":
        return "datum"
    return "other"


def bodies(doc):
    return [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]


def body_of(obj):
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def find_body(doc):
    """The body the user is working on: the active one, else one holding the selection,
    else the only (or first) body in the document."""
    if doc is None:
        return None
    if App.GuiUp:
        import FreeCADGui as Gui
        gdoc = Gui.getDocument(doc.Name)
        view = gdoc.ActiveView if gdoc else None
        if view is not None and hasattr(view, "getActiveObject"):
            body = view.getActiveObject("pdbody")
            if body is not None:
                return body
        for sel in Gui.Selection.getSelection(doc.Name):
            body = sel if sel.TypeId == "PartDesign::Body" else body_of(sel)
            if body is not None:
                return body
    found = bodies(doc)
    return found[0] if found else None


def marker_index(body):
    """Index in body.Group after which the marker sits; -1 means before everything."""
    group = body.Group
    tip = body.Tip
    if tip is None or tip not in group:
        return -1
    return group.index(tip)


def entries(body):
    group = body.Group
    marker = marker_index(body)
    result = []
    for i, obj in enumerate(group):
        result.append({
            "index": i,
            "name": obj.Name,
            "label": obj.Label,
            "type": obj.TypeId,
            "kind": kind(obj),
            "tip": obj is body.Tip,
            "rolled_back": i > marker,
            "suppressed": bool(getattr(obj, "Suppressed", False)),
            "error": "Invalid" in obj.State or "Error" in obj.State,
        })
    return result


def roll_to_index(body, index):
    """Put the marker after group[index] (index -1: before everything)."""
    group = body.Group
    index = max(-1, min(index, len(group) - 1))
    tip = None
    for obj in reversed(group[:index + 1]):
        if is_feature(obj):
            tip = obj
            break
    _set_tip(body, tip)
    return tip


def roll_to(body, obj):
    return roll_to_index(body, body.Group.index(obj))


def roll_to_end(body):
    return roll_to_index(body, len(body.Group) - 1)


def roll_to_start(body):
    return roll_to_index(body, -1)


def step(body, delta):
    """Move the marker by ``delta`` solid features (negative = back in time)."""
    group = body.Group
    feature_positions = [i for i, o in enumerate(group) if is_feature(o)]
    current = marker_index(body)
    if delta < 0:
        earlier = [i for i in feature_positions if i < current]
        target = earlier[delta] if len(earlier) >= -delta else -1
    else:
        later = [i for i in feature_positions if i > current]
        target = later[min(delta, len(later)) - 1] if later else current
    return roll_to_index(body, target)


def own_sketch(body, obj):
    """The profile sketch that only ``obj`` uses, which moves along with it."""
    profile = getattr(obj, "Profile", None)
    sketch = profile[0] if isinstance(profile, tuple) else profile
    if sketch is None or not sketch.isDerivedFrom("Sketcher::SketchObject"):
        return None
    group = body.Group
    users = [o for o in sketch.InList if o in group]
    return sketch if sketch in group and users == [obj] else None


def move(body, obj, boundary, with_sketch=True):
    """Move ``obj`` (with its own sketch) to just after group[boundary] (-1: first).

    Refuses moves that would put something before what it is built on. PartDesign
    relinks the chain of BaseFeatures itself. The rollback marker stays on the same
    feature, or at the end if it was at the end. Returns False if nothing moved.
    """
    group = body.Group
    if obj not in group:
        raise ValueError("%s is not in body %s" % (obj.Name, body.Name))
    sketch = own_sketch(body, obj) if with_sketch else None
    moving = [o for o in group if o is obj or o is sketch]
    anchor = group[boundary] if boundary >= 0 else None
    if anchor in moving:
        return False
    rest = [o for o in group if o not in moving]
    at = rest.index(anchor) + 1 if anchor is not None else 0
    order = rest[:at] + moving + rest[at:]
    if order == group:
        return False
    _check_order(order, moving)

    tip = body.Tip
    at_end = not any(is_feature(o) for o in group[marker_index(body) + 1:])
    for m in moving:
        body.removeObject(m)
    previous = anchor
    for m in moving:
        if previous is None:
            body.insertObject(m, body.Group[0], False)
        else:
            body.insertObject(m, previous, True)
        previous = m
    if at_end:
        roll_to_end(body)
    else:
        _set_tip(body, tip)
    return True


def _check_order(order, moving):
    position = {o: i for i, o in enumerate(order)}
    for m in moving:
        base = getattr(m, "BaseFeature", None)  # relinked by PartDesign
        for used in m.OutList:
            if used in position and used is not base and position[used] > position[m]:
                raise ValueError("%s is built on %s, so it can't go before it"
                                 % (m.Label, used.Label))
        for user in m.InList:
            if (user in position and getattr(user, "BaseFeature", None) is not m
                    and position[user] < position[m]):
                raise ValueError("%s uses %s, so %s can't go after it"
                                 % (user.Label, m.Label, m.Label))


def set_suppressed(obj, suppressed):
    if "Suppressed" not in obj.PropertiesList:
        raise ValueError("%s can't be suppressed" % obj.Name)
    obj.Suppressed = bool(suppressed)


def _set_tip(body, tip):
    old = body.Tip
    if old is tip:
        return
    body.Tip = tip
    # Like PartDesign's own "Set tip": show the new tip's solid, hide the old one.
    if App.GuiUp:
        if old is not None:
            old.Visibility = False
        if tip is not None:
            tip.Visibility = True
