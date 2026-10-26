"""User parameters (Fusion: Change Parameters): one App::VarSet named "Parameters".
Expressions anywhere can then use Parameters.<name>.

Shared by the MCP handlers and the Change Parameters dialog.
"""

import FreeCAD as App

from .rpc import HandlerError

GROUP = "Parameters"
TYPES = {"length": "App::PropertyDistance", "angle": "App::PropertyAngle",
         "number": "App::PropertyFloat"}
UNITS = {"App::PropertyDistance": "mm", "App::PropertyAngle": "deg"}


class ParameterError(HandlerError):
    pass


def varset(doc, create=False):
    obj = doc.getObject("Parameters")
    if obj is None or obj.TypeId != "App::VarSet":
        if not create:
            return None
        obj = doc.addObject("App::VarSet", "Parameters")
    return obj


def names(vs):
    return [p for p in vs.PropertiesList if vs.getGroupOfProperty(p) == GROUP]


def kind(vs, name):
    return {t: k for k, t in TYPES.items()}.get(vs.getTypeIdOfProperty(name))


def check_name(name):
    if not name.isidentifier():
        raise ParameterError("parameter name %r must be a valid identifier" % name)
    try:
        App.Units.Quantity(name)
    except Exception:
        return
    # Expressions would read it as a unit: h is hours, m metres, ...
    raise ParameterError("%r is a unit name; pick another parameter name" % name)


def rename(vs, old, new):
    """Expressions that use the parameter follow the new name."""
    if old not in names(vs):
        raise ParameterError("no parameter %r" % old)
    check_name(new)
    if new in vs.PropertiesList:
        raise ParameterError("%r is already taken" % new)
    vs.renameProperty(old, new)


def _kind_of(quantity):
    unit = quantity.Unit
    if unit == App.Units.Unit("mm"):
        return "length"
    if unit == App.Units.Unit("deg"):
        return "angle"
    if unit == App.Units.Unit():
        return "number"
    raise ParameterError("parameters can be lengths, angles or plain numbers, got %s"
                         % quantity.UserString)


def set_one(vs, name, spec):
    """``spec``: a number, a quantity string ('30 deg'), an expression ('=width / 2'),
    or a dict with ``value`` and optionally ``kind`` and ``comment``."""
    if not isinstance(spec, dict):
        spec = {"value": spec}
    value, wanted = spec.get("value"), spec.get("kind")
    check_name(name)
    expression = value[1:] if isinstance(value, str) and value.startswith("=") else None
    if expression is not None:
        try:
            quantity = vs.evalExpression(expression)
        except Exception as e:
            raise ParameterError("bad expression for %s: %s" % (name, e))
    elif isinstance(value, str):
        try:
            quantity = App.Units.Quantity(value)
        except Exception:
            raise ParameterError("can't read %r for %s; use 10, '30 deg' or '=width / 2'"
                                 % (value, name))
    else:
        unit = {"length": "mm", "angle": "deg"}.get(wanted or "length")
        quantity = App.Units.Quantity(float(value), App.Units.Unit(unit) if unit
                                      else App.Units.Unit())
    if not isinstance(quantity, App.Units.Quantity):
        quantity = App.Units.Quantity(float(quantity))
    if wanted is None and name in names(vs) and quantity.Unit == App.Units.Unit():
        wanted = kind(vs, name)  # '20' typed into a length stays a length
    if wanted is None:
        wanted = _kind_of(quantity)
    if wanted not in TYPES:
        raise ParameterError("kind must be length, angle or number")
    if name in vs.PropertiesList and vs.getGroupOfProperty(name) != GROUP:
        raise ParameterError("%r is a reserved name" % name)
    comment = spec.get("comment")
    if name in vs.PropertiesList and vs.getTypeIdOfProperty(name) != TYPES[wanted]:
        if comment is None:
            comment = vs.getDocumentationOfProperty(name)
        vs.removeProperty(name)
    if name not in vs.PropertiesList:
        vs.addProperty(TYPES[wanted], name, GROUP, comment or "")
    elif "comment" in spec:
        vs.setDocumentationOfProperty(name, spec["comment"] or "")
    if expression is not None:
        vs.setExpression(name, expression)
    else:
        vs.setExpression(name, None)
        setattr(vs, name, quantity.Value if wanted == "number" else quantity)


def from_text(text):
    """What someone typed in the dialog: a value ('40', '30 deg') or an expression
    ('width / 2', with or without a leading '=')."""
    text = text.strip()
    if not text or text.startswith("="):
        return text
    try:
        App.Units.Quantity(text)
        return text
    except Exception:
        return "=" + text


def as_text(vs, name):
    """The other way round: the expression if there is one, else the value."""
    expression = dict(vs.ExpressionEngine).get(name)
    if expression is not None:
        return expression
    return value_text(vs, name)


def value_text(vs, name):
    value = getattr(vs, name)
    if hasattr(value, "UserString"):
        return value.UserString
    return "%g" % value


def set_kind(vs, name, kind):
    """Make a parameter a length, angle or number, keeping its expression or number."""
    expression = dict(vs.ExpressionEngine).get(name)
    if expression is not None:
        set_one(vs, name, {"value": "=" + expression, "kind": kind})
    else:
        value = getattr(vs, name)
        set_one(vs, name, {"value": getattr(value, "Value", value), "kind": kind})


def snapshot(vs):
    """Everything about the parameters, for ``restore``."""
    if vs is None:
        return {}
    expressions = dict(vs.ExpressionEngine)
    out = {}
    for name in names(vs):
        value = getattr(vs, name)
        out[name] = {"kind": kind(vs, name),
                     "value": ("=" + expressions[name]) if name in expressions
                     else getattr(value, "Value", value),
                     "comment": vs.getDocumentationOfProperty(name) or ""}
    return out


def restore(vs, saved):
    """Put the parameters back as ``snapshot`` saw them. Aborting a transaction doesn't
    always do it: changing a kind removes and re-adds a property of the same name, and
    undo loses it."""
    if vs is None:
        return
    for name in names(vs):
        if name not in saved:
            vs.removeProperty(name)
    if snapshot(vs) != saved:
        set_many(vs, {n: dict(spec) for n, spec in saved.items()})


def set_many(vs, parameters):
    # Plain values first so expressions can refer to parameters set in the same call.
    items = sorted(parameters.items(), key=lambda kv: str(
        kv[1].get("value") if isinstance(kv[1], dict) else kv[1]).startswith("="))
    for name, spec in items:
        set_one(vs, name, spec)


def listing(vs):
    vs.Document.recompute()  # evaluate expressions set in this call
    expressions = dict(vs.ExpressionEngine)
    out = []
    for p in names(vs):
        value = getattr(vs, p)
        out.append({"name": p, "value": round(getattr(value, "Value", value), 6),
                    "unit": UNITS.get(vs.getTypeIdOfProperty(p)),
                    "expression": expressions.get(p),
                    "comment": vs.getDocumentationOfProperty(p) or None})
    return out


def users(doc, name):
    """Objects whose expressions use Parameters.<name>, as (object, property) pairs."""
    import re

    pattern = re.compile(r"(?<![\w.])(?:Parameters|<<Parameters>>)\.%s\b" % re.escape(name))
    return [(o, prop.lstrip(".")) for o in doc.Objects
            for prop, expr in o.ExpressionEngine if pattern.search(expr)]
