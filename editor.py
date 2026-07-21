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
  - "Compiler vers .wad..." runs it and writes a WAD file, then runs
    the configured nodebuilder on it in place (if one is configured --
    see "Paramètres" below), since a freshly-written WAD always needs
    one before it's playable (see README.md).

Either one, on a WsError, prints "file:line: error: message" (the same
format the CLI uses) to the output pane and jumps the editor to the
offending line.

"Paramètres" > "Configurer..." sets the path to an external nodebuilder
(e.g. BSP, ZenNode), to a Doom source port, to a level editor (e.g.
Yadex), and to an IWAD, persisted across runs via QSettings. Once
configured, "Lancer dans le moteur" / "Ouvrir dans l'éditeur de niveau"
launch them on the most recently compiled (and node-built) WAD, passing
the IWAD along (`-iwad` for the engine, Yadex's own `-g doom2 -i2` for
the level editor) if one is set, and (for the level editor) `-map
<level>` so Yadex opens straight into the level instead of sitting at
its own "yadex:" startup prompt.
"""

import io
import os
import subprocess
import sys
import traceback

from PySide6.QtCore import Qt, QRect, QSettings, QSize, QRegularExpression
from PySide6.QtGui import (
    QColor, QFont, QKeySequence, QPainter, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor, QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QStatusBar, QTextEdit, QToolBar, QVBoxLayout,
    QWidget,
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


class SettingsDialog(QDialog):
    """Four file paths (nodebuilder, source port, level editor, IWAD), each
    with a "Parcourir..." button -- deliberately just paths, no extra
    flags/arguments fields, to stay a small settings dialog rather than
    growing into a launcher config editor. Values are only written back to
    QSettings on Ok, not live as the user types, so Cancel truly discards
    edits."""

    def __init__(self, nodebuilder_path, engine_path, level_editor_path, iwad_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paramètres")

        self.nodebuilder_edit = QLineEdit(nodebuilder_path)
        self.engine_edit = QLineEdit(engine_path)
        self.level_editor_edit = QLineEdit(level_editor_path)
        self.iwad_edit = QLineEdit(iwad_path)

        form = QFormLayout()
        form.addRow("Nodebuilder (ex. bsp) :", self._row(self.nodebuilder_edit, "un nodebuilder"))
        form.addRow("Moteur Doom (port source) :", self._row(self.engine_edit, "un moteur Doom"))
        form.addRow("Éditeur de niveau (ex. Yadex) :", self._row(self.level_editor_edit, "un éditeur de niveau"))
        form.addRow("IWAD (ex. doom2.wad) :", self._row(self.iwad_edit, "un IWAD"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _row(self, line_edit, dialog_title_suffix):
        browse = QPushButton("Parcourir...")
        browse.clicked.connect(lambda: self._browse(line_edit, dialog_title_suffix))
        row = QHBoxLayout()
        row.addWidget(line_edit)
        row.addWidget(browse)
        container = QWidget()
        container.setLayout(row)
        return container

    def _browse(self, line_edit, dialog_title_suffix):
        path, _ = QFileDialog.getOpenFileName(self, f"Choisir {dialog_title_suffix}", line_edit.text())
        if path:
            line_edit.setText(path)


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
        self.last_map_name = None
        self.settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "wadscript", "editor")
        self.nodebuilder_path = self.settings.value("nodebuilder_path", "", str)
        self.engine_path = self.settings.value("engine_path", "", str)
        self.level_editor_path = self.settings.value("level_editor_path", "", str)
        self.iwad_path = self.settings.value("iwad_path", "", str)
        self.recent_files = self._load_recent_files()

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
        # Rebuilt from scratch (see _refresh_recent_menu) every time
        # recent_files changes -- self._recent_actions holds a live Python
        # reference to whatever's currently in it, same GC gotcha as above.
        self.recent_menu = file_menu.addMenu("Fichiers &récents")
        self._recent_actions = []
        self._refresh_recent_menu()
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
        self.play_action = run_menu.addAction("&Lancer dans le moteur")
        self.play_action.setShortcut(QKeySequence("Ctrl+R"))
        self.play_action.triggered.connect(self.play_in_engine)
        self.open_in_editor_action = run_menu.addAction("&Ouvrir dans l'éditeur de niveau")
        self.open_in_editor_action.setShortcut(QKeySequence("Ctrl+E"))
        self.open_in_editor_action.triggered.connect(self.open_in_level_editor)

        settings_menu = self.menuBar().addMenu("&Paramètres")
        self.configure_action = settings_menu.addAction("&Configurer...")
        self.configure_action.triggered.connect(self.open_settings)

        self.toolbar = QToolBar("Principale")
        self.toolbar.addAction(self.new_action)
        self.toolbar.addAction(self.open_action)
        self.toolbar.addAction(self.save_action)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.check_action)
        self.toolbar.addAction(self.build_action)
        self.toolbar.addAction(self.play_action)
        self.toolbar.addAction(self.open_in_editor_action)
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

    # -- recent files (Fichier > Fichiers récents) --

    MAX_RECENT_FILES = 10

    def _load_recent_files(self):
        # QSettings can hand back a bare str instead of a one-element list
        # (an ini-format quirk when exactly one value was ever stored), so
        # this always normalizes to a list.
        value = self.settings.value("recent_files", [])
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        return list(value)

    def _save_recent_files(self):
        self.settings.setValue("recent_files", self.recent_files)

    def _add_recent_file(self, path):
        path = os.path.abspath(path)
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        del self.recent_files[self.MAX_RECENT_FILES:]
        self._save_recent_files()
        self._refresh_recent_menu()

    def _remove_recent_file(self, path):
        if path in self.recent_files:
            self.recent_files.remove(path)
            self._save_recent_files()
            self._refresh_recent_menu()

    def _clear_recent_files(self):
        self.recent_files = []
        self._save_recent_files()
        self._refresh_recent_menu()

    def _open_recent(self, path):
        if not self._confirm_discard():
            return
        try:
            self._load_file(path)
        except OSError as e:
            QMessageBox.warning(self, "Fichier introuvable", f"Impossible d'ouvrir {path!r} : {e}")
            self._remove_recent_file(path)

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        self._recent_actions = []  # keep a live reference -- see _build_actions
        if not self.recent_files:
            empty_action = self.recent_menu.addAction("(aucun)")
            empty_action.setEnabled(False)
            self._recent_actions.append(empty_action)
            return
        for i, path in enumerate(self.recent_files):
            label = f"&{i + 1} {os.path.basename(path)}" if i < 9 else os.path.basename(path)
            action = self.recent_menu.addAction(label)
            action.setStatusTip(path)
            action.triggered.connect(lambda checked=False, p=path: self._open_recent(p))
            self._recent_actions.append(action)
        self.recent_menu.addSeparator()
        clear_action = self.recent_menu.addAction("Vider la liste")
        clear_action.triggered.connect(self._clear_recent_files)
        self._recent_actions.append(clear_action)

    def _load_file(self, path):
        with open(path, "r", encoding="utf-8") as f:
            self.editor.setPlainText(f.read())
        self.editor.document().setModified(False)
        self.current_path = os.path.abspath(path)
        self.editor.clear_error_line()
        self.output.clear()
        self._update_title()
        self._add_recent_file(self.current_path)

    def save_file(self):
        if self.current_path is None:
            return self.save_file_as()
        with open(self.current_path, "w", encoding="utf-8") as f:
            f.write(self.editor.toPlainText())
        self.editor.document().setModified(False)
        self._update_title()
        self._add_recent_file(self.current_path)
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
        self.last_map_name = level.map_name
        try:
            write_wad(path, level)
        except OSError as e:
            self.output.appendPlainText(f"erreur : impossible d'écrire {path!r} : {e}")
            return
        self.output.appendPlainText(
            f"écrit {path} : {len(level.vertices)} vertices, {len(level.linedefs)} linedefs, "
            f"{len(level.sidedefs)} sidedefs, {len(level.sectors)} sectors, {len(level.things)} things")
        if self.nodebuilder_path:
            self._run_nodebuilder(path)
        else:
            self.output.appendPlainText(
                "rappel : ce WAD a besoin d'un nodebuilder externe (bsp, ZenNode) avant de "
                "pouvoir être chargé dans un port source ou dans Yadex pour jouer -- configurez-en "
                "un dans Paramètres > Configurer... pour que ce soit fait automatiquement.")

    def _run_nodebuilder(self, wad_path):
        """Runs the configured nodebuilder on wad_path in place, the same
        'bsp <wad> -o <wad>' convention documented in README.md."""
        self.output.appendPlainText(f"lancement du nodebuilder : {self.nodebuilder_path} {wad_path} -o {wad_path}")
        try:
            result = subprocess.run(
                [self.nodebuilder_path, wad_path, "-o", wad_path],
                capture_output=True, text=True, timeout=60)
        except OSError as e:
            self.output.appendPlainText(f"erreur : impossible de lancer le nodebuilder : {e}")
            return
        except subprocess.TimeoutExpired:
            self.output.appendPlainText("erreur : le nodebuilder n'a pas terminé après 60s, abandon")
            return
        if result.stdout:
            self.output.appendPlainText(result.stdout.rstrip())
        if result.stderr:
            self.output.appendPlainText(result.stderr.rstrip())
        if result.returncode != 0:
            self.output.appendPlainText(f"le nodebuilder a rendu le code {result.returncode}")
        else:
            self.output.appendPlainText("nodebuilder : OK, WAD prêt à être chargé.")

    def play_in_engine(self):
        if not self.engine_path:
            QMessageBox.warning(
                self, "Moteur non configuré",
                "Configurez le chemin d'un moteur Doom dans Paramètres > Configurer... avant "
                "de pouvoir lancer un test.")
            return
        if not self.last_wad_path or not os.path.exists(self.last_wad_path):
            QMessageBox.warning(
                self, "Aucun WAD compilé",
                "Compilez le script (Exécuter > Compiler vers .wad...) avant de le lancer dans "
                "le moteur.")
            return
        args = [self.engine_path]
        if self.iwad_path:
            args += ["-iwad", self.iwad_path]
        args += ["-file", self.last_wad_path]
        try:
            subprocess.Popen(args)
        except OSError as e:
            self.output.appendPlainText(f"erreur : impossible de lancer le moteur : {e}")
            return
        self.output.appendPlainText(f"lancé : {' '.join(args)}")

    def open_in_level_editor(self):
        if not self.level_editor_path:
            QMessageBox.warning(
                self, "Éditeur de niveau non configuré",
                "Configurez le chemin d'un éditeur de niveau (ex. Yadex) dans "
                "Paramètres > Configurer... avant de pouvoir l'ouvrir.")
            return
        if not self.last_wad_path or not os.path.exists(self.last_wad_path):
            QMessageBox.warning(
                self, "Aucun WAD compilé",
                "Compilez le script (Exécuter > Compiler vers .wad...) avant de l'ouvrir dans "
                "l'éditeur de niveau.")
            return
        args = [self.level_editor_path]
        # -g/-i2 are Yadex's own flags for "game" and "Doom II/Final Doom
        # iwad" -- this project only ever targets Doom II (see README.md),
        # and this action is documented as launching Yadex specifically.
        if self.iwad_path:
            args += ["-g", "doom2", "-i2", self.iwad_path]
        # -map auto-loads the level instead of leaving the user to type
        # "e <level_name>" themselves at Yadex's own startup prompt.
        if self.last_map_name:
            args += ["-map", self.last_map_name]
        args.append(self.last_wad_path)
        try:
            subprocess.Popen(args)
        except OSError as e:
            self.output.appendPlainText(f"erreur : impossible de lancer l'éditeur de niveau : {e}")
            return
        self.output.appendPlainText(f"lancé : {' '.join(args)}")

    def open_settings(self):
        dialog = SettingsDialog(self.nodebuilder_path, self.engine_path, self.level_editor_path, self.iwad_path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.nodebuilder_path = dialog.nodebuilder_edit.text().strip()
        self.engine_path = dialog.engine_edit.text().strip()
        self.level_editor_path = dialog.level_editor_edit.text().strip()
        self.iwad_path = dialog.iwad_edit.text().strip()
        self.settings.setValue("nodebuilder_path", self.nodebuilder_path)
        self.settings.setValue("engine_path", self.engine_path)
        self.settings.setValue("level_editor_path", self.level_editor_path)
        self.settings.setValue("iwad_path", self.iwad_path)


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
