"""Fusion-style timeline: a strip of feature icons docked at the bottom of FreeCAD.

- Click selects a feature, double-click edits it, right-click opens a menu. Drag a
  feature to reorder the history (its own sketch moves with it).
- The orange marker sits after the body's Tip. Drag it to roll the model back;
  new features are then inserted at the marker. Playback buttons step it.
- Rolled-back features are faded, suppressed ones struck through, failing ones red.
- A feature's own sketch shares its slot, shown as a small badge (*Fusion → Group
  sketches in timeline* turns that off).

The widget polls a cheap signature of the active body a few times per second while
visible and repaints only when it changed, which keeps it in sync with every way the
model can change (tree view, undo, Python, MCP) without fragile observers.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import history, prefs

CELL = 34          # width of one timeline slot
ICON = 24
BADGE = 13         # the sketch icon in a grouped slot
PAD = 10           # left/right padding inside the strip
STRIP_HEIGHT = 46
MARKER_COLOR = QtGui.QColor("#f28c28")
ERROR_COLOR = QtGui.QColor("#d9534f")
SELECT_COLOR = QtGui.QColor(70, 140, 230, 90)
DROP_COLOR = QtGui.QColor(70, 140, 230)
POLL_MS = 300


class TimelineStrip(QtWidgets.QWidget):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.items = []          # slots: [[(obj, entry dict), ...]], the feature last
        self.marker = -1         # slot index after which the marker sits
        self.selected = set()
        self.drag_marker = None  # marker index while dragging
        self.press = None        # (cell index, x) of a left press on a feature
        self.drag_item = None    # cell index being dragged to reorder
        self.drop_at = None      # boundary it would be dropped at
        self.setMouseTracking(True)
        self.setFixedHeight(STRIP_HEIGHT)

    # -- data -----------------------------------------------------------------

    def set_data(self, items, marker, selected):
        self.items = items
        self.marker = marker
        self.selected = selected
        self.setMinimumWidth(2 * PAD + max(1, len(items)) * CELL + 8)
        self.update()

    # -- geometry -------------------------------------------------------------

    def cell_rect(self, i):
        return QtCore.QRect(PAD + i * CELL, 6, CELL, STRIP_HEIGHT - 12)

    def marker_x(self, marker):
        return PAD + (marker + 1) * CELL

    def index_at(self, x):
        i = (x - PAD) // CELL
        return int(i) if 0 <= i < len(self.items) else None

    def boundary_at(self, x):
        """Nearest gap between cells, as a marker index (-1 .. len-1)."""
        b = round((x - PAD) / CELL) - 1
        return max(-1, min(len(self.items) - 1, int(b)))

    def near_marker(self, x):
        return abs(x - self.marker_x(self.marker)) <= 6

    # -- painting -------------------------------------------------------------

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.color(QtGui.QPalette.Base))

        # A thin rail behind the icons, like Fusion's.
        rail_y = STRIP_HEIGHT // 2
        p.setPen(QtGui.QPen(pal.color(QtGui.QPalette.Mid), 2))
        p.drawLine(PAD, rail_y, PAD + len(self.items) * CELL, rail_y)

        for i, members in enumerate(self.items):
            obj, entry = members[-1]
            r = self.cell_rect(i)
            box = r.adjusted(3, 0, -3, 0)
            if any(o.Name in self.selected for o, _ in members):
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(SELECT_COLOR)
                p.drawRoundedRect(box, 4, 4)
            if any(e["error"] for _, e in members):
                p.setPen(QtGui.QPen(ERROR_COLOR, 2))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRoundedRect(box, 4, 4)
            icon = _icon_for(obj)
            p.setOpacity(0.3 if entry["rolled_back"] or entry["suppressed"] else 1.0)
            ix = r.x() + (CELL - ICON) // 2
            iy = r.y() + (r.height() - ICON) // 2
            if icon is not None and not icon.isNull():
                icon.paint(p, ix, iy, ICON, ICON)
            else:
                p.setPen(pal.color(QtGui.QPalette.Text))
                p.drawText(QtCore.QRect(ix, iy, ICON, ICON), QtCore.Qt.AlignCenter,
                           entry["label"][:2])
            if len(members) > 1:
                badge = _icon_for(members[0][0])
                if badge is not None and not badge.isNull():
                    badge.paint(p, box.right() - BADGE, box.bottom() - BADGE, BADGE, BADGE)
            p.setOpacity(1.0)
            if entry["suppressed"]:
                p.setPen(QtGui.QPen(pal.color(QtGui.QPalette.Text), 2))
                p.drawLine(box.topLeft() + QtCore.QPoint(4, 4),
                           box.bottomRight() - QtCore.QPoint(4, 4))

        self._paint_marker(p, self.marker, 1.0)
        if self.drag_marker is not None and self.drag_marker != self.marker:
            self._paint_marker(p, self.drag_marker, 0.5)
        if self.drag_item is not None:
            p.setPen(QtGui.QPen(DROP_COLOR, 2, QtCore.Qt.DashLine))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawRoundedRect(self.cell_rect(self.drag_item).adjusted(3, 0, -3, 0), 4, 4)
            if self._drop_changes_order():
                x = self.marker_x(self.drop_at)
                p.setPen(QtGui.QPen(DROP_COLOR, 3))
                p.drawLine(x, 6, x, STRIP_HEIGHT - 6)
        p.end()

    def _drop_changes_order(self):
        return self.drop_at not in (self.drag_item, self.drag_item - 1)

    def _paint_marker(self, p, marker, opacity):
        x = self.marker_x(marker)
        p.setOpacity(opacity)
        p.setPen(QtGui.QPen(MARKER_COLOR, 3))
        p.drawLine(x, 4, x, STRIP_HEIGHT - 4)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(MARKER_COLOR)
        p.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x - 6, 1), QtCore.QPoint(x + 6, 1),
                                      QtCore.QPoint(x, 9)]))
        p.setOpacity(1.0)

    # -- mouse ----------------------------------------------------------------

    def mousePressEvent(self, event):
        x = _x(event)
        if event.button() == QtCore.Qt.LeftButton and self.near_marker(x):
            self.drag_marker = self.marker
            self.setCursor(QtCore.Qt.SizeHorCursor)
            return
        i = self.index_at(x)
        if event.button() == QtCore.Qt.LeftButton and i is not None:
            self.panel.select(self.items[i][-1][0], event.modifiers())
            self.press = (i, x)

    def mouseMoveEvent(self, event):
        x = _x(event)
        if self.drag_marker is not None:
            self.drag_marker = self.boundary_at(x)
            self.update()
            return
        if self.press is not None and event.buttons() & QtCore.Qt.LeftButton:
            i, start_x = self.press
            if (self.drag_item is None
                    and abs(x - start_x) >= QtWidgets.QApplication.startDragDistance()):
                self.drag_item = i
                self.setCursor(QtCore.Qt.ClosedHandCursor)
            if self.drag_item is not None:
                self.drop_at = self.boundary_at(x)
                self.update()
                return
        self.setCursor(QtCore.Qt.SizeHorCursor if self.near_marker(x)
                       else QtCore.Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.press = None
        if self.drag_item is not None:
            item, self.drag_item = self.drag_item, None
            target, self.drop_at = self.drop_at, None
            self.setCursor(QtCore.Qt.ArrowCursor)
            self.update()
            if target not in (item, item - 1):
                self.panel.move(self.items[item][-1][0], self.group_index(target))
            return
        if self.drag_marker is None:
            return
        target, self.drag_marker = self.drag_marker, None
        self.setCursor(QtCore.Qt.ArrowCursor)
        if target != self.marker:
            self.panel.roll_to_index(self.group_index(target))
        self.update()

    def group_index(self, boundary):
        """A boundary between slots as an index in body.Group (-1: before everything)."""
        return self.items[boundary][-1][1]["index"] if boundary >= 0 else -1

    def mouseDoubleClickEvent(self, event):
        i = self.index_at(_x(event))
        if i is not None:
            self.panel.edit(self.items[i][-1][0])

    def contextMenuEvent(self, event):
        i = self.index_at(event.pos().x())
        if i is not None:
            self.panel.context_menu([o for o, _ in self.items[i]], self.group_index(i),
                                    event.globalPos())

    def event(self, event):
        if event.type() == QtCore.QEvent.ToolTip:
            i = self.index_at(event.pos().x())
            if i is not None:
                obj, entry = self.items[i][-1]
                lines = ["<b>%s</b>" % entry["label"], entry["type"].split("::")[-1]]
                if len(self.items[i]) > 1:
                    lines.append("sketch: %s" % self.items[i][0][1]["label"])
                if entry["rolled_back"]:
                    lines.append("<i>rolled back</i>")
                if entry["suppressed"]:
                    lines.append("<i>suppressed</i>")
                if entry["error"]:
                    lines.append("<span style='color:#d9534f'>failed to recompute</span>")
                QtWidgets.QToolTip.showText(event.globalPos(), "<br>".join(lines), self)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().event(event)


def _x(event):
    pos = event.position() if hasattr(event, "position") else event.pos()
    return int(pos.x())


def _icon_for(obj):
    vo = getattr(obj, "ViewObject", None)
    try:
        return vo.Icon if vo is not None else None
    except Exception:
        return None


class TimelinePanel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.doc = None
        self.body = None
        self._signature = None

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        style = self.style()
        for icon, tip, slot in [
            (QtWidgets.QStyle.SP_MediaSkipBackward, "Roll to start", self.roll_start),
            (QtWidgets.QStyle.SP_MediaSeekBackward, "Step back", lambda: self.step(-1)),
            (QtWidgets.QStyle.SP_MediaSeekForward, "Step forward", lambda: self.step(1)),
            (QtWidgets.QStyle.SP_MediaSkipForward, "Roll to end", self.roll_end),
        ]:
            button = QtWidgets.QToolButton()
            button.setIcon(style.standardIcon(icon))
            button.setToolTip(tip)
            button.setAutoRaise(True)
            button.clicked.connect(slot)
            layout.addWidget(button)

        self.strip = TimelineStrip(self)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidget(self.strip)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(STRIP_HEIGHT + 16)
        layout.addWidget(self.scroll, 1)

        self.caption = QtWidgets.QLabel()
        self.caption.setMinimumWidth(80)
        layout.addWidget(self.caption)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(POLL_MS)

    # -- sync -----------------------------------------------------------------

    def refresh(self, force=False):
        if not self.isVisible() and not force:
            return
        try:
            doc = App.ActiveDocument
            body = history.find_body(doc) if doc else None
            signature = self._make_signature(doc, body)
        except ReferenceError:  # object deleted while we were looking
            return
        if signature == self._signature and not force:
            return
        self._signature = signature
        self.doc, self.body = doc, body
        if body is None:
            self.strip.set_data([], -1, set())
            self.caption.setText("No body" if doc else "")
            return
        group, entries = body.Group, history.entries(body)
        slots = history.cells(body, grouped=_grouped())
        items = [[(group[i], entries[i]) for i in slot] for slot in slots]
        # The marker is on a feature, which is always the last of its slot.
        marker = history.marker_index(body)
        marker_slot = max((s for s, slot in enumerate(slots) if slot[-1] <= marker), default=-1)
        selected = {o.Name for o in Gui.Selection.getSelection(doc.Name)}
        self.strip.set_data(items, marker_slot, selected)
        self.caption.setText(body.Label)

    @staticmethod
    def _make_signature(doc, body):
        if doc is None or body is None:
            return (doc.Name if doc else None, None)
        objs = tuple((o.Name, o.Label, tuple(o.State), bool(getattr(o, "Suppressed", False)))
                     for o in body.Group)
        selected = tuple(o.Name for o in Gui.Selection.getSelection(doc.Name))
        return (doc.Name, body.Name, body.Tip.Name if body.Tip else None, objs, selected,
                _grouped())

    # -- actions --------------------------------------------------------------

    def _change(self, label, fn):
        if self.doc is None or self.body is None:
            return
        doc = self.doc
        doc.openTransaction(label)
        try:
            fn()
            doc.recompute()
        except Exception as e:
            doc.abortTransaction()
            App.Console.PrintError("Timeline: %s\n" % e)
            Gui.getMainWindow().statusBar().showMessage(str(e), 6000)
            return
        doc.commitTransaction()
        self.refresh(force=True)

    def roll_to_index(self, index):
        self._change("Roll timeline", lambda: history.roll_to_index(self.body, index))

    def move(self, obj, boundary):
        self._change("Move feature", lambda: history.move(self.body, obj, boundary))

    def roll_start(self):
        self._change("Roll timeline", lambda: history.roll_to_start(self.body))

    def roll_end(self):
        self._change("Roll timeline", lambda: history.roll_to_end(self.body))

    def step(self, delta):
        self._change("Roll timeline", lambda: history.step(self.body, delta))

    def select(self, obj, modifiers):
        if not modifiers & QtCore.Qt.ControlModifier:
            Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj)
        self.refresh(force=True)

    def edit(self, obj):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj)
        gdoc = Gui.getDocument(obj.Document.Name)
        if gdoc is not None:
            gdoc.setEdit(obj, 0)

    def context_menu(self, members, index, global_pos):
        obj = members[-1]
        menu = QtWidgets.QMenu(self)
        menu.addAction("Edit feature", lambda: self.edit(obj))
        if len(members) > 1:
            menu.addAction("Edit sketch", lambda: self.edit(members[0]))
        menu.addAction("Roll back to here", lambda: self.roll_to_index(index))
        if "Suppressed" in obj.PropertiesList:
            suppressed = bool(obj.Suppressed)
            menu.addAction("Unsuppress" if suppressed else "Suppress",
                           lambda: self._change("Suppress feature",
                                                lambda: history.set_suppressed(obj, not suppressed)))
        menu.addSeparator()
        menu.addAction("Delete", lambda: self._delete(obj))
        menu.exec(global_pos)

    def _delete(self, obj):
        # Std_Delete asks about dependent objects, like deleting from the tree.
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj)
        Gui.runCommand("Std_Delete", 0)
        self.refresh(force=True)


def _grouped():
    return prefs().GetBool("GroupSketches", True)


DOCK_NAME = "FusionFreeCAD_Timeline"


def dock():
    """The timeline dock widget, created on first use."""
    mw = Gui.getMainWindow()
    existing = mw.findChild(QtWidgets.QDockWidget, DOCK_NAME)
    if existing is not None:
        return existing
    widget = QtWidgets.QDockWidget("Timeline", mw)
    widget.setObjectName(DOCK_NAME)
    widget.setWidget(TimelinePanel())
    widget.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea | QtCore.Qt.TopDockWidgetArea)
    mw.addDockWidget(QtCore.Qt.BottomDockWidgetArea, widget)
    return widget


def show():
    d = dock()
    d.show()
    d.widget().refresh(force=True)


def hide():
    mw = Gui.getMainWindow()
    existing = mw.findChild(QtWidgets.QDockWidget, DOCK_NAME)
    if existing is not None:
        existing.hide()


def refresh():
    mw = Gui.getMainWindow()
    existing = mw.findChild(QtWidgets.QDockWidget, DOCK_NAME)
    if existing is not None:
        existing.widget().refresh(force=True)


def toggle():
    d = dock()
    if d.isVisible():
        d.hide()
    else:
        show()
