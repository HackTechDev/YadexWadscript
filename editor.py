#!/usr/bin/env python3
"""editor.py - a small Qt GUI editor for wadscript (.wsl) scripts.

Usage:
    python3 editor.py [script.wsl]

Optional companion to wadscript.py's CLI. Unlike the rest of this repo
(stdlib only), this needs PySide6 (`pip install PySide6`).

Syntax highlighting, line numbers, and two actions that reuse the exact
same tokenize/parse/resolve pipeline as wadscript.py:
  - "Vérifier" runs it and prints the resolved vertex/linedef/sidedef/
    sector/thing tables (same as --dump-geometry), without writing
    anything.
  - "Compiler vers .wad..." runs it and writes a WAD file.

Either one, on a WsError, prints "file:line: error: message" (the same
format the CLI uses) to the output pane and jumps the editor to the
offending line.
"""

import io
import os
import sys
import traceback

from PySide6.QtCore import Qt, QRect, QSize, QRegularExpression
from PySide6.QtGui import (
    QColor, QFont, QKeySequence, QPainter, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor, QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMainWindow, QMessageBox, QPlainTextEdit,
    QSplitter, QStatusBar, QTextEdit, QToolBar, QWidget,
)

from errors import WsError
from lexer import tokenize
from parser import parse
from geometry import resolve
from wadwriter import write_wad

KEYWORDS = [
    "map", "defaults", "texture_preset", "const", "include",
    "sector", "edge", "thing", "repeat", "rotate", "around",
    "points", "holes", "offset", "relative_to",
    "special", "tag", "flags", "raw", "at", "angle", "random",
    "floor", "ceiling", "light", "floor_flat", "ceiling_flat",
    "wall_texture", "middle_texture",
    "upper", "lower", "middle", "x_offset", "y_offset", "preset", "texture",
]
DIRECTIONS = ["east", "north", "west", "south"]


class WadscriptHighlighter(QSyntaxHighlighter):
    """Keyword/direction/number/string/comment highlighting -- no attempt
    to validate the script, just coloring, so it never blocks typing even
    on a currently-invalid script."""

    def __init__(self, document):
        super().__init__(document)
        self._rules = []

        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569cd6"))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        for word in KEYWORDS:
            self._rules.append((QRegularExpression(rf"\b{word}\b"), keyword_format))

        direction_format = QTextCharFormat()
        direction_format.setForeground(QColor("#4ec9b0"))
        for word in DIRECTIONS:
            self._rules.append((QRegularExpression(rf"\b{word}\b"), direction_format))

        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#b5cea8"))
        self._rules.append((QRegularExpression(r"-?\b\d+\b"), number_format))

        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#ce9178"))
        self._rules.append((QRegularExpression(r'"[^"\n]*"'), string_format))

        self._comment_format = QTextCharFormat()
        self._comment_format.setForeground(QColor("#6a9955"))
        self._comment_format.setFontItalic(True)
        self._comment_re = QRegularExpression(r"#.*$")

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
        # Comments last so a '#' anywhere on the line wins over any
        # keyword/number/string match to its right.
        it = self._comment_re.globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), self._comment_format)


class _LineNumberArea(QWidget):
    """Thin gutter widget to the left of a CodeEditor -- painting is
    delegated back to the editor, which is the one that knows about
    block geometry (standard Qt "Code Editor" example pattern)."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setPointSize(11)
        self.setFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; border: none;")

        self._error_selection = None
        self._line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._refresh_selections)
        self._update_line_number_area_width(0)
        self._refresh_selections()

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_area_width(self, _new_block_count):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def paint_line_numbers(self, event):
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#252526"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        height = self.fontMetrics().height()
        width = self._line_number_area.width() - 6
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#858585"))
                painter.drawText(0, top, width, height, Qt.AlignmentFlag.AlignRight, str(block_number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def _refresh_selections(self):
        selections = []
        current_line = QTextEdit.ExtraSelection()
        current_line.format.setBackground(QColor("#2a2d2e"))
        current_line.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        current_line.cursor = self.textCursor()
        current_line.cursor.clearSelection()
        selections.append(current_line)
        if self._error_selection is not None:
            selections.append(self._error_selection)
        self.setExtraSelections(selections)

    def show_error_line(self, line_no):
        """line_no is 1-indexed, matching WsError.line."""
        block = self.document().findBlockByNumber(line_no - 1)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.setTextCursor(cursor)
        self.centerCursor()
        error_line = QTextEdit.ExtraSelection()
        error_line.format.setBackground(QColor("#5a1d1d"))
        error_line.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        error_line.cursor = cursor
        error_line.cursor.clearSelection()
        self._error_selection = error_line
        self._refresh_selections()

    def clear_error_line(self):
        self._error_selection = None
        self._refresh_selections()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_path = None
        self.last_wad_path = None

        self.editor = CodeEditor()
        self.editor.textChanged.connect(self._update_title)
        WadscriptHighlighter(self.editor.document())

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self.output.setFont(mono)
        self.output.setStyleSheet("background-color: #181818; color: #cccccc; border: none;")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.output)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._build_actions()
        self.setStatusBar(QStatusBar())
        self.editor.cursorPositionChanged.connect(self._update_status)
        self._update_status()
        self._update_title()
        self.resize(1000, 750)

    def _build_actions(self):
        # Kept as self.*_action attributes (not locals) so PySide6 keeps a
        # live Python reference around -- a QAction handed only to
        # QMenu.addAction()/QToolBar.addAction() without one gets garbage
        # collected out from under the menu once this method returns,
        # despite still being listed in menu.actions() (verified: calling
        # .trigger() on it then raises "Internal C++ object already
        # deleted").
        file_menu = self.menuBar().addMenu("&Fichier")
        self.new_action = file_menu.addAction("&Nouveau")
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_file)
        self.open_action = file_menu.addAction("&Ouvrir...")
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_file)
        self.save_action = file_menu.addAction("&Enregistrer")
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_file)
        self.save_as_action = file_menu.addAction("Enregistrer &sous...")
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(self.save_file_as)
        file_menu.addSeparator()
        self.quit_action = file_menu.addAction("&Quitter")
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)

        run_menu = self.menuBar().addMenu("&Exécuter")
        self.check_action = run_menu.addAction("&Vérifier (dump-geometry)")
        self.check_action.setShortcut(QKeySequence("Ctrl+Return"))
        self.check_action.triggered.connect(self.check_script)
        self.build_action = run_menu.addAction("&Compiler vers .wad...")
        self.build_action.setShortcut(QKeySequence("Ctrl+B"))
        self.build_action.triggered.connect(self.build_wad)

        self.toolbar = QToolBar("Principale")
        self.toolbar.addAction(self.new_action)
        self.toolbar.addAction(self.open_action)
        self.toolbar.addAction(self.save_action)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.check_action)
        self.toolbar.addAction(self.build_action)
        self.addToolBar(self.toolbar)

    # -- window title / status bar --

    def _update_title(self):
        name = os.path.basename(self.current_path) if self.current_path else "sans titre"
        mark = "*" if self.editor.document().isModified() else ""
        self.setWindowTitle(f"{mark}{name} — éditeur wadscript")

    def _update_status(self):
        cursor = self.editor.textCursor()
        self.statusBar().showMessage(f"Ligne {cursor.blockNumber() + 1}, colonne {cursor.columnNumber() + 1}")

    # -- file handling --

    def _confirm_discard(self):
        if not self.editor.document().isModified():
            return True
        resp = QMessageBox.question(
            self, "Modifications non enregistrées",
            "Ce script a été modifié. Voulez-vous l'enregistrer avant de continuer ?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if resp == QMessageBox.StandardButton.Save:
            return self.save_file()
        return resp == QMessageBox.StandardButton.Discard

    def new_file(self):
        if not self._confirm_discard():
            return
        self.editor.clear()
        self.editor.document().setModified(False)
        self.current_path = None
        self.editor.clear_error_line()
        self.output.clear()
        self._update_title()

    def open_file(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un script", "", "wadscript (*.wsl);;Tous les fichiers (*)")
        if not path:
            return
        self._load_file(path)

    def _load_file(self, path):
        with open(path, "r", encoding="utf-8") as f:
            self.editor.setPlainText(f.read())
        self.editor.document().setModified(False)
        self.current_path = os.path.abspath(path)
        self.editor.clear_error_line()
        self.output.clear()
        self._update_title()

    def save_file(self):
        if self.current_path is None:
            return self.save_file_as()
        with open(self.current_path, "w", encoding="utf-8") as f:
            f.write(self.editor.toPlainText())
        self.editor.document().setModified(False)
        self._update_title()
        return True

    def save_file_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer sous", self.current_path or "untitled.wsl",
            "wadscript (*.wsl);;Tous les fichiers (*)")
        if not path:
            return False
        if "." not in os.path.basename(path):
            path += ".wsl"
        self.current_path = path
        return self.save_file()

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    # -- compile pipeline (shared by "Vérifier" and "Compiler") --

    def _compile(self):
        """Runs tokenize -> parse -> resolve on the editor's current text,
        the same pipeline wadscript.py's CLI uses. Returns a LevelData on
        success. On a WsError, logs "file:line: error: message" (matching
        the CLI's own format) and jumps the editor to the offending line,
        then re-raises so the caller knows to stop (e.g. not write a .wad
        from a script that didn't actually compile)."""
        self.editor.clear_error_line()
        source = self.editor.toPlainText()
        display_name = self.current_path or "<sans titre>"
        base_dir = os.path.dirname(self.current_path) if self.current_path else "."
        try:
            tokens = tokenize(source)
            script = parse(tokens, base_dir=base_dir)
            return resolve(script)
        except WsError as e:
            self.output.appendPlainText(e.format(display_name))
            if e.line is not None:
                self.editor.show_error_line(e.line)
            raise

    def check_script(self):
        self.output.clear()
        if self.current_path is None:
            self.output.appendPlainText(
                "note : script non enregistré -- un 'include' relatif serait résolu par "
                "rapport au répertoire courant plutôt qu'au fichier (voir README.md).\n")
        try:
            level = self._compile()
        except WsError:
            return
        except Exception:
            self.output.appendPlainText("erreur interne inattendue :\n" + traceback.format_exc())
            return
        buf = io.StringIO()
        level.dump(buf)
        self.output.appendPlainText(buf.getvalue())
        self.output.appendPlainText(
            f"OK : {len(level.vertices)} vertices, {len(level.linedefs)} linedefs, "
            f"{len(level.sidedefs)} sidedefs, {len(level.sectors)} sectors, {len(level.things)} things")

    def build_wad(self):
        self.output.clear()
        if self.current_path is None:
            QMessageBox.warning(
                self, "Enregistrement requis",
                "Enregistrez le script (.wsl) avant de compiler -- 'include' a besoin d'un "
                "chemin de fichier réel pour résoudre les chemins relatifs.")
            return
        try:
            level = self._compile()
        except WsError:
            return
        except Exception:
            self.output.appendPlainText("erreur interne inattendue :\n" + traceback.format_exc())
            return
        default_path = self.last_wad_path or os.path.splitext(self.current_path)[0] + ".wad"
        path, _ = QFileDialog.getSaveFileName(self, "Compiler vers", default_path, "WAD (*.wad);;Tous les fichiers (*)")
        if not path:
            return
        self.last_wad_path = path
        try:
            write_wad(path, level)
        except OSError as e:
            self.output.appendPlainText(f"erreur : impossible d'écrire {path!r} : {e}")
            return
        self.output.appendPlainText(
            f"écrit {path} : {len(level.vertices)} vertices, {len(level.linedefs)} linedefs, "
            f"{len(level.sidedefs)} sidedefs, {len(level.sectors)} sectors, {len(level.things)} things")
        self.output.appendPlainText(
            "rappel : passez ce WAD dans un nodebuilder externe (bsp, ZenNode) avant de le "
            "charger dans un port source ou dans Yadex pour jouer -- voir README.md.")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        try:
            window._load_file(sys.argv[1])
        except OSError as e:
            QMessageBox.critical(window, "Erreur", f"Impossible d'ouvrir {sys.argv[1]!r} : {e}")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
