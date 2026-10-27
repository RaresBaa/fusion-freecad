"""Fusion's marking menu: a radial menu on right-click in the 3D view.

Right-click and release opens a ring of eight commands around the cursor; click one
(or move towards it and click anywhere in its direction). Right-drag towards a
command and release runs it straight away, without waiting for the ring (a "mark").
"More..." under the ring opens FreeCAD's usual context menu.

The ring depends on what's going on, like Fusion's:
- while a sketch is being edited: sketch tools and Finish Sketch;
- in another task dialog (a feature being created or edited): OK and Cancel;
- otherwise: the part tools.
The top slot repeats the last command run from the ring.

Only active in Fusion mode, and only when the view shows its normal cursor: tools
that change it (sketcher tools, box selection, measuring) use the right button
themselves, so they get it unchanged. An event filter sits on each 3D view's
viewport; FreeCAD's own context menu is reached by replaying the click past it.
"""

import math

import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import prefs

DEAD_ZONE = 18     # px from the centre where nothing is picked
MARK_DISTANCE = 30  # px of right-drag that turns a click into a mark
RADIUS_X, RADIUS_Y = 125, 88

# Slots clockwise from the top: N, NE, E, SE, S, SW, W, NW. None leaves one empty;
# slot 0 is replaced by "Repeat <last command>" when there is one.
PART_RING = [None, "Std_Undo", "FusionFreeCAD_PressPull", "PartDesign_Fillet",
             "Std_Delete", "PartDesign_Hole", "PartDesign_NewSketch", "PartDesign_Pad"]
SKETCH_RING = [None, "Std_Undo", "Sketcher_CreateCircle", "Sketcher_Dimension",
               "Sketcher_LeaveSketch", "Sketcher_Trimming", "Sketcher_CreatePolyline",
               "Sketcher_CreateRectangle"]
# Fusion's Construction toggle sits in its sketch overflow; ours goes in "More...".

OK, CANCEL = "__ok__", "__cancel__"
DIALOG_RING = [None, None, OK, None, None, None, CANCEL, None]

_last = None        # last command run from the ring
_open = None        # the popup ring; Python must hold it or it's deleted at once
_viewports = {}     # id(viewport) -> viewport with our filter installed
_filter = None
_mdi = None


def enabled():
    return prefs().GetBool("MarkingMenu", True)


def set_enabled(value):
    prefs().SetBool("MarkingMenu", bool(value))
    if value:
        apply()
    else:
        restore()


def sector(dx, dy):
    """The slot (0 = up, clockwise) in direction (dx, dy), screen y down; None in the
    dead zone."""
    if math.hypot(dx, dy) < DEAD_ZONE:
        return None
    angle = math.degrees(math.atan2(dx, -dy)) % 360
    return int((angle + 22.5) // 45) % 8


def ring():
    """The command names for the ring as it should be now."""
    from .session import _sketch_in_edit

    if _sketch_in_edit():  # it has a task panel too, but no OK/Cancel to press
        slots = list(SKETCH_RING)
    elif Gui.Control.activeDialog():
        return list(DIALOG_RING)
    else:
        slots = list(PART_RING)
    if _last:
        slots[0] = _last
    return slots


# Commands

class _Item:
    def __init__(self, name, repeat=False):
        self.name = name
        self.text, self.icon, self.enabled = name, QtGui.QIcon(), False
        if name == OK:
            self.text = "OK"
            self.enabled = _task_button(QtWidgets.QDialogButtonBox.Ok) is not None
            self.icon = QtGui.QIcon.fromTheme("dialog-ok", QtGui.QIcon(":/icons/edit_OK.svg"))
            return
        if name == CANCEL:
            self.text = "Cancel"
            self.enabled = _task_button(QtWidgets.QDialogButtonBox.Cancel) is not None
            self.icon = QtGui.QIcon(":/icons/edit-cleartext.svg")
            return
        if name not in Gui.listCommands():
            return
        cmd = Gui.Command.get(name)
        actions = cmd.getAction()
        action = actions[0] if actions else None
        if action is not None:
            self.text = action.text().replace("&", "")
            self.icon = action.icon()
            self.enabled = action.isEnabled()
        else:
            self.text = cmd.getInfo().get("menuText", name).replace("&", "")
            self.enabled = cmd.isActive()
        if self.text.endswith("..."):
            self.text = self.text[:-3]
        if repeat:
            self.text = "Repeat " + self.text

    def run(self):
        global _last
        if self.name == OK:
            _click(QtWidgets.QDialogButtonBox.Ok)
        elif self.name == CANCEL:
            _click(QtWidgets.QDialogButtonBox.Cancel)
        else:
            if self.name not in ("Std_Undo", "Std_Delete", "Sketcher_LeaveSketch"):
                _last = self.name
            Gui.runCommand(self.name, 0)


def _task_button(role):
    """The visible OK/Cancel button of the task panel's dialog, if any."""
    mw = Gui.getMainWindow()
    for box in mw.findChildren(QtWidgets.QDialogButtonBox):
        if not box.isVisible():
            continue
        button = box.button(role)
        if button is not None and button.isVisible() and button.isEnabled():
            return button
    return None


def _click(role):
    button = _task_button(role)
    if button is not None:
        button.click()


def _items():
    slots = ring()
    repeat = 0 if slots[0] and slots[0] == _last else None
    return [_Item(n, repeat=(i == repeat)) if n else None for i, n in enumerate(slots)]


# The ring

class Ring(QtWidgets.QWidget):
    """Eight commands round a centre. ``live`` while the right button is still held
    (a mark in progress): shown without taking the mouse. Otherwise a popup, which
    closes on a click outside, Esc or right-click."""

    def __init__(self, centre, items, live):
        flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.NoDropShadowWindowHint
        flags |= QtCore.Qt.ToolTip if live else QtCore.Qt.Popup
        super().__init__(None, flags)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        if live:
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.items = items
        self.live = live
        self.hover = None
        self.more_rect = QtCore.QRectF()
        self.rects = []
        size = QtCore.QSize(2 * RADIUS_X + 300, 2 * RADIUS_Y + 120)
        self.resize(size)
        self.centre = QtCore.QPointF(size.width() / 2, size.height() / 2 - 10)
        self.move(centre - self.centre.toPoint())
        self._lay_out()

    def _lay_out(self):
        fm = QtGui.QFontMetrics(self.font())
        h = max(fm.height(), 16) + 10
        for i, item in enumerate(self.items):
            if item is None:
                self.rects.append(None)
                continue
            w = fm.horizontalAdvance(item.text) + 16 + 22
            a = math.radians(i * 45)
            x = self.centre.x() + RADIUS_X * math.sin(a)
            y = self.centre.y() - RADIUS_Y * math.cos(a)
            if i in (1, 2, 3):      # right side: grow outwards from the point
                left = x - 16
            elif i in (5, 6, 7):
                left = x - w + 16
            else:
                left = x - w / 2
            self.rects.append(QtCore.QRectF(left, y - h / 2, w, h))
        if not self.live:
            w = fm.horizontalAdvance("More...") + 20
            self.more_rect = QtCore.QRectF(self.centre.x() - w / 2,
                                           self.centre.y() + RADIUS_Y + h, w, h)

    def pick(self, pos):
        """Slot index, "more" or None for a point in widget coordinates."""
        if self.more_rect.contains(pos):
            return "more"
        for i, rect in enumerate(self.rects):
            if rect is not None and rect.contains(pos):
                return i
        i = sector(pos.x() - self.centre.x(), pos.y() - self.centre.y())
        return i if i is not None and self.items[i] is not None else None

    def set_hover(self, hover):
        if hover != self.hover:
            self.hover = hover
            self.update()

    # Painting

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pal = self.palette()
        base, text = pal.color(QtGui.QPalette.Window), pal.color(QtGui.QPalette.WindowText)
        accent = pal.color(QtGui.QPalette.Highlight)
        border = QtGui.QColor(text)
        border.setAlpha(90)

        # Centre: a ring with a wedge pointing at the hovered slot.
        c, r = self.centre, DEAD_ZONE
        p.setPen(QtGui.QPen(border, 1.5))
        p.setBrush(base)
        p.drawEllipse(c, r, r)
        if isinstance(self.hover, int):
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(accent)
            start = 90 - self.hover * 45 - 22.5
            p.drawPie(QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r),
                      int(start * 16), 45 * 16)

        for i, (item, rect) in enumerate(zip(self.items, self.rects)):
            if item is not None:
                self._paint_item(p, item.text, item.icon, rect, item.enabled,
                                 self.hover == i, base, text, accent, border)
        if not self.more_rect.isNull():
            self._paint_item(p, "More...", None, self.more_rect, True,
                             self.hover == "more", base, text, accent, border)

    def _paint_item(self, p, label, icon, rect, enabled, hover, base, text, accent, border):
        p.setPen(QtGui.QPen(accent if hover else border, 1))
        p.setBrush(base)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if hover and enabled:
            fill = QtGui.QColor(accent)
            fill.setAlpha(90)
            p.setBrush(fill)
            p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        x = rect.left() + 10
        if icon is not None:
            if not icon.isNull():
                mode = QtGui.QIcon.Normal if enabled else QtGui.QIcon.Disabled
                pix = icon.pixmap(16, 16, mode)
                p.drawPixmap(QtCore.QPointF(x, rect.center().y() - 8), pix)
            x += 22
        colour = QtGui.QColor(text)
        if not enabled:
            colour.setAlpha(110)
        p.setPen(colour)
        p.drawText(QtCore.QRectF(x, rect.top(), rect.right() - x - 6, rect.height()),
                   QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, label)

    # Popup mode

    def mouseMoveEvent(self, event):
        self.set_hover(self.pick(event.position() if hasattr(event, "position")
                                 else QtCore.QPointF(event.pos())))

    def mouseReleaseEvent(self, event):
        pos = event.position() if hasattr(event, "position") else QtCore.QPointF(event.pos())
        if event.button() == QtCore.Qt.RightButton:
            self.close()
            return
        if event.button() != QtCore.Qt.LeftButton:
            return
        if not self.rect().contains(pos.toPoint()):
            self.close()
            return
        picked = self.pick(pos)
        if picked is None:
            if math.hypot(pos.x() - self.centre.x(), pos.y() - self.centre.y()) < DEAD_ZONE:
                self.close()  # the centre cancels, like Fusion's
            return
        self.close()
        _choose(self, picked)

    def mousePressEvent(self, event):
        pos = event.pos()
        if not self.rect().contains(pos):
            self.close()  # Qt also closes a popup here; the click doesn't go through

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()

    def closeEvent(self, event):
        global _open
        if _open is self:
            _open = None
        super().closeEvent(event)


def _choose(ring_widget, picked):
    if picked == "more":
        QtCore.QTimer.singleShot(0, lambda vp=ring_widget.viewport, pos=ring_widget.origin:
                                 _context_menu(vp, pos))
        return
    item = ring_widget.items[picked]
    if item is not None and item.enabled:
        # After the ring has gone and this event is done, as from a menu.
        QtCore.QTimer.singleShot(0, item.run)


def _context_menu(viewport, pos):
    """FreeCAD's own right-click menu: replay the click past our filter."""
    if viewport is None:
        return
    _filter.passthrough = True
    try:
        for kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
            event = QtGui.QMouseEvent(kind, QtCore.QPointF(pos),
                                      QtCore.QPointF(viewport.mapToGlobal(pos)),
                                      QtCore.Qt.RightButton,
                                      QtCore.Qt.RightButton
                                      if kind == QtCore.QEvent.MouseButtonPress
                                      else QtCore.Qt.NoButton,
                                      QtCore.Qt.NoModifier)
            QtWidgets.QApplication.sendEvent(viewport, event)
    finally:
        _filter.passthrough = False


# The event filter

def _plain_cursor(widget):
    return widget.cursor().shape() == QtCore.Qt.ArrowCursor


class _Filter(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.passthrough = False
        self.press = None       # (viewport, local pos, global pos) while right is held
        self.live = None        # Ring shown during a mark

    def eventFilter(self, obj, event):
        try:
            return self._filter(obj, event)
        except Exception as e:  # never break the 3D view
            import FreeCAD
            FreeCAD.Console.PrintWarning("Fusion marking menu: %s\n" % e)
            self.press = None
            self._drop_live()
            return False

    def _filter(self, obj, event):
        kind = event.type()
        if self.passthrough or kind not in (QtCore.QEvent.MouseButtonPress,
                                            QtCore.QEvent.MouseMove,
                                            QtCore.QEvent.MouseButtonRelease,
                                            QtCore.QEvent.ContextMenu):
            return False
        if kind == QtCore.QEvent.ContextMenu:
            # Qt's own context-menu event (e.g. the menu key); FreeCAD opens its menu
            # from the mouse events, so a right-click we took must not open it here.
            return self.press is not None
        if kind == QtCore.QEvent.MouseButtonPress:
            if (event.button() != QtCore.Qt.RightButton
                    or event.modifiers() != QtCore.Qt.NoModifier
                    or event.buttons() != QtCore.Qt.RightButton
                    or not _plain_cursor(obj)):
                return False
            self.press = (obj, event.pos(), event.globalPos())
            return True
        if self.press is None or obj is not self.press[0]:
            return False
        _, local, origin = self.press
        delta = event.globalPos() - origin
        if kind == QtCore.QEvent.MouseMove:
            if self.live is None and math.hypot(delta.x(), delta.y()) >= MARK_DISTANCE:
                self.live = Ring(origin, _items(), live=True)
                self.live.show()
            if self.live is not None:
                self.live.set_hover(sector(delta.x(), delta.y()))
            return True
        if event.button() != QtCore.Qt.RightButton:
            return True
        self.press = None
        if self.live is not None:   # a mark: run what it points at
            picked = sector(delta.x(), delta.y())
            items = self.live.items
            self._drop_live()
            item = items[picked] if picked is not None else None
            if item is not None and item.enabled:
                QtCore.QTimer.singleShot(0, item.run)
            return True
        global _open
        popup = _open = Ring(origin, _items(), live=False)
        popup.viewport, popup.origin = obj, local
        popup.show()
        popup.set_hover(popup.pick(QtCore.QPointF(popup.mapFromGlobal(QtGui.QCursor.pos()))))
        return True

    def _drop_live(self):
        if self.live is not None:
            self.live.close()
            self.live = None


def _viewport(view):
    """The widget that gets a 3D view's mouse events."""
    widget = view if isinstance(view, QtWidgets.QWidget) else None
    if widget is None:
        return None
    for gv in widget.findChildren(QtWidgets.QGraphicsView):
        return gv.viewport()
    return None


def _hook_views(*_):
    if _filter is None:
        return
    for sub in _mdi.subWindowList() if _mdi is not None else []:
        inner = sub.widget()
        if inner is None or inner.metaObject().className() != "Gui::View3DInventor":
            continue
        vp = _viewport(inner)
        if vp is not None and id(vp) not in _viewports:
            vp.installEventFilter(_filter)
            _viewports[id(vp)] = vp
            vp.destroyed.connect(lambda *_, key=id(vp): _viewports.pop(key, None))


def apply():
    """Called when Fusion mode starts."""
    global _filter, _mdi
    if not enabled() or _filter is not None:
        return
    _filter = _Filter()
    _mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    if _mdi is not None:
        _mdi.subWindowActivated.connect(_hook_views)
    _hook_views()


def restore():
    """Called when Fusion mode ends."""
    global _filter, _mdi
    if _filter is None:
        return
    for vp in list(_viewports.values()):
        try:
            vp.removeEventFilter(_filter)
        except RuntimeError:
            pass  # already deleted
    _viewports.clear()
    if _mdi is not None:
        try:
            _mdi.subWindowActivated.disconnect(_hook_views)
        except (RuntimeError, TypeError):
            pass
    _filter._drop_live()
    _filter, _mdi = None, None
