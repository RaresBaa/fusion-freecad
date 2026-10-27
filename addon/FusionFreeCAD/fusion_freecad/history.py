"""The feature history of a PartDesign body, seen as a Fusion-style timeline.

The timeline is the body's Group in order. The rollback marker sits right after the
body's Tip: features after it are "rolled back" (not part of the body's shape), and
new features are inserted at the marker. Only solid features can be the Tip, so
rolling to a sketch or datum puts the Tip on the nearest solid feature before it.

A feature's own profile sketch, right before it, can share its slot (``cells``), which
keeps long timelines short.

Groups (Fusion: timeline groups) name a run of the timeline and can be collapsed into
one slot. They are stored on the body (``TimelineGroups``, one JSON object per group
listing its members) and cover everything from their first to their last member, so a
feature inserted inside a group joins it and a deleted member just drops out.

No Qt here, so it works headless and backs both the timeline widget and the RPC tools.
"""

import json

import FreeCAD as App

GROUPS_PROPERTY = "TimelineGroups"


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


def cells(body, grouped=True):
    """The timeline's slots, as lists of body.Group indices. With ``grouped``, a
    feature's own sketch directly before it shares the feature's slot."""
    group = body.Group
    result = []
    for i, obj in enumerate(group):
        if grouped and result and result[-1] == [i - 1] and own_sketch(body, obj) is group[i - 1]:
            result[-1].append(i)
        else:
            result.append([i])
    return result


def entries(body):
    group = body.Group
    marker = marker_index(body)
    owners = {}
    for cell in cells(body):
        for i in cell[:-1]:
            owners[i] = group[cell[-1]].Name
    in_group = {}
    for g in groups(body):
        for i in range(g["start"], g["end"] + 1):
            in_group[i] = g["name"]
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
            "owner": owners.get(i),  # the feature whose sketch this is, if grouped
            "group": in_group.get(i),
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
    _regroup(body, moving, order)
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


# -- groups --------------------------------------------------------------------

def _stored(body):
    if GROUPS_PROPERTY not in body.PropertiesList:
        return []
    result = []
    for text in getattr(body, GROUPS_PROPERTY):
        try:
            g = json.loads(text)
        except ValueError:
            continue
        if isinstance(g, dict) and g.get("name") and g.get("members"):
            result.append(g)
    return result


def _store(body, stored):
    if GROUPS_PROPERTY not in body.PropertiesList:
        body.addProperty("App::PropertyStringList", GROUPS_PROPERTY, "Timeline",
                         "Named, collapsible runs of the timeline")
        body.setEditorMode(GROUPS_PROPERTY, 2)  # hidden: edited from the timeline
    setattr(body, GROUPS_PROPERTY, [json.dumps(g, sort_keys=True) for g in stored])


def _spans(body, stored, order=None):
    """(group, start, end) for each stored group with members left in ``order``."""
    order = body.Group if order is None else order
    position = {o.Name: i for i, o in enumerate(order)}
    result = []
    for g in stored:
        at = [position[n] for n in g["members"] if n in position]
        if at:
            result.append((g, min(at), max(at)))
    return result


def groups(body):
    """The body's timeline groups in order: name, start/end (body.Group indices,
    inclusive), members (names) and collapsed."""
    group = body.Group
    result = [{"name": g["name"], "start": start, "end": end,
               "members": [o.Name for o in group[start:end + 1]],
               "collapsed": bool(g.get("collapsed"))}
              for g, start, end in _spans(body, _stored(body))]
    return sorted(result, key=lambda g: g["start"])


def find_group(body, name):
    for g in groups(body):
        if g["name"] == name:
            return g
    raise ValueError("body %s has no timeline group %r" % (body.Label, name))


def make_group(body, first, last, name=None, collapsed=False):
    """Group group[first..last] (indices), widened to whole slots so a feature keeps
    its own sketch. Groups can't overlap. Returns the new group."""
    group = body.Group
    first, last = sorted((first, last))
    if first < 0 or last >= len(group):
        raise ValueError("group range %d..%d is outside the timeline" % (first, last))
    for cell in cells(body):
        if cell[0] <= first <= cell[-1]:
            first = cell[0]
        if cell[0] <= last <= cell[-1]:
            last = cell[-1]
    for g in groups(body):
        if g["start"] <= last and first <= g["end"]:
            raise ValueError("that range overlaps the group %r" % g["name"])
    names = {g["name"] for g in groups(body)}
    if not name:
        n = 1
        while "Group%d" % n in names:
            n += 1
        name = "Group%d" % n
    elif name in names:
        raise ValueError("there already is a group named %r" % name)
    stored = [g for g, _, _ in _spans(body, _stored(body))]
    stored.append({"name": name, "members": [o.Name for o in group[first:last + 1]],
                   "collapsed": bool(collapsed)})
    _store(body, _normalised(body, stored))
    return find_group(body, name)


def _normalised(body, stored, order=None):
    """Members rewritten to each group's whole current run."""
    order = body.Group if order is None else order
    return [dict(g, members=[o.Name for o in order[start:end + 1]])
            for g, start, end in _spans(body, stored, order)]


def _edit_group(body, name, change):
    stored = _stored(body)
    for g in stored:
        if g["name"] == name:
            change(g, stored)
            _store(body, _normalised(body, [x for x in stored if x.get("members")]))
            return
    raise ValueError("body %s has no timeline group %r" % (body.Label, name))


def ungroup(body, name):
    _edit_group(body, name, lambda g, stored: g.update(members=[]))


def rename_group(body, name, new_name):
    if not new_name:
        raise ValueError("a group needs a name")
    if new_name != name and any(g["name"] == new_name for g in _stored(body)):
        raise ValueError("there already is a group named %r" % new_name)
    _edit_group(body, name, lambda g, stored: g.update(name=new_name))


def set_collapsed(body, name, collapsed):
    _edit_group(body, name, lambda g, stored: g.update(collapsed=bool(collapsed)))


def _regroup(body, moving, order):
    """After a move to ``order``: the moved objects belong to the group they landed
    inside (between two of its members), and to no other."""
    stored = _stored(body)
    if not stored:
        return
    names = {m.Name for m in moving}
    old = _spans(body, stored)
    for g in stored:
        g["members"] = [n for n in g["members"] if n not in names]
    position = {o.Name: i for i, o in enumerate(order)}
    at = [position[n] for n in names]
    for g, start, end in old:
        rest = [position[n] for n in g["members"] if n in position]
        if rest and min(rest) < min(at) and max(at) < max(rest):
            g["members"] += sorted(names, key=position.get)
    _store(body, _normalised(body, [g for g in stored if g["members"]], order))
