"""Change Parameters: Fusion's table of user parameters.

Every edit applies at once (the model recomputes); the whole dialog is one undo
transaction, so Cancel puts everything back.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import parameters as P

NAME, EXPRESSION, VALUE, KIND, COMMENT, USED_BY = range(6)
KINDS = ["length", "angle", "number"]


class ParametersDialog(QtWidgets.QDialog):
    def __init__(self, doc):
        super().__init__(Gui.getMainWindow())
        self.doc = doc
        self.setWindowTitle("Change Parameters")
        self.resize(760, 360)
        layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Expression", "Value", "Kind", "Comment", "Used by"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        header.setSectionResizeMode(USED_BY, QtWidgets.QHeaderView.Stretch)
        for column, width in ((NAME, 130), (EXPRESSION, 160), (VALUE, 100), (KIND, 110),
                              (COMMENT, 140)):
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._on_item)
        layout.addWidget(self.table)

        self.error = QtWidgets.QLabel()
        self.error.setStyleSheet("color: #d9534f")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add")
        add.setToolTip("Add a user parameter")
        add.clicked.connect(self._add)
        self.delete = QtWidgets.QPushButton("Delete")
        self.delete.clicked.connect(self._delete)
        row.addWidget(add)
        row.addWidget(self.delete)
        row.addStretch()
        hint = QtWidgets.QLabel("Use them anywhere as Parameters.<name>, e.g. in a "
                                "sketch dimension.")
        hint.setEnabled(False)
        row.addWidget(hint)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok
                                             | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

        self.saved = P.snapshot(self._vs())
        self.doc.openTransaction("Change parameters")
        self._fill()

    # -- table ------------------------------------------------------------------

    def _vs(self, create=False):
        return P.varset(self.doc, create)

    def _fill(self, select=None):
        vs = self._vs()
        names = P.names(vs) if vs else []
        self.table.blockSignals(True)
        self.table.setRowCount(len(names))
        for r, name in enumerate(names):
            users = P.users(self.doc, name)
            cells = {NAME: name, EXPRESSION: P.as_text(vs, name),
                     VALUE: P.value_text(vs, name),
                     COMMENT: vs.getDocumentationOfProperty(name) or "",
                     USED_BY: ", ".join("%s.%s" % (o.Label, p) for o, p in users)}
            for column, text in cells.items():
                item = QtWidgets.QTableWidgetItem(text)
                item.setData(QtCore.Qt.UserRole, name)
                if column in (VALUE, USED_BY):
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                    item.setForeground(self.palette().brush(
                        QtGui.QPalette.Disabled, QtGui.QPalette.Text))
                if column == USED_BY:
                    item.setToolTip(text.replace(", ", "\n"))
                self.table.setItem(r, column, item)
            kind = QtWidgets.QComboBox()
            kind.addItems(KINDS)
            kind.setCurrentText(P.kind(vs, name) or "number")
            kind.currentTextChanged.connect(
                lambda text, name=name: self._apply(name, P.set_kind, vs, name, text))
            self.table.setCellWidget(r, KIND, kind)
            if name == select:
                self.table.setCurrentCell(r, NAME)
        self.table.blockSignals(False)
        self.delete.setEnabled(bool(names))

    def _apply(self, select, change, *args):
        """Run one change, recompute and show the result (``select`` is the row to
        keep current), or the error."""
        try:
            change(*args)
            self.doc.recompute()
            self.error.clear()
        except Exception as e:
            self.error.setText(str(e))
        # Rebuilding inside itemChanged would delete the item Qt is still using.
        QtCore.QTimer.singleShot(0, lambda: self._fill(select))

    def _on_item(self, item):
        name = item.data(QtCore.Qt.UserRole)
        text = item.text()
        vs = self._vs()
        column = item.column()
        if column == NAME and text != name:
            self._apply(text.strip(), P.rename, vs, name, text.strip())
        elif column == EXPRESSION:
            self._apply(name, P.set_one, vs, name, P.from_text(text) or "0")
        elif column == COMMENT:
            self._apply(name, vs.setDocumentationOfProperty, name, text)

    def _add(self):
        vs = self._vs(create=True)
        taken = set(vs.PropertiesList)
        n = 1
        while "param%d" % n in taken:
            n += 1
        name = "param%d" % n
        self._apply(name, P.set_one, vs, name, "10 mm")
        QtCore.QTimer.singleShot(0, lambda: self._edit_name(name))

    def _edit_name(self, name):
        for r in range(self.table.rowCount()):
            if self.table.item(r, NAME).data(QtCore.Qt.UserRole) == name:
                self.table.editItem(self.table.item(r, NAME))

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        names = [self.table.item(r, NAME).data(QtCore.Qt.UserRole) for r in rows]
        if not names:
            return
        used = [n for n in names if P.users(self.doc, n)]
        if used and QtWidgets.QMessageBox.question(
                self, "Delete parameters",
                "%s still used by the model; their expressions will fail. Delete anyway?"
                % ", ".join(used)) != QtWidgets.QMessageBox.Yes:
            return
        vs = self._vs()
        self._apply(None, lambda: [vs.removeProperty(n) for n in names])

    # -- dialog ---------------------------------------------------------------

    def accept(self):
        self.table.setFocus()  # finish an edit in progress
        self.doc.commitTransaction()
        super().accept()

    def reject(self):
        self.doc.abortTransaction()
        P.restore(self._vs(), self.saved)
        self.doc.recompute()
        super().reject()


class ChangeParametersCommand:
    def GetResources(self):
        from . import icon

        return {"Pixmap": icon("parameters.svg"),
                "MenuText": "Change Parameters",
                "ToolTip": "Named values the model's dimensions can use, in one table"}

    def Activated(self):
        ParametersDialog(App.ActiveDocument).exec()

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()
