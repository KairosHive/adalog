from PyQt6.QtWidgets import QVBoxLayout, QTextEdit
from PyQt6.QtCore import pyqtSignal, Qt
from adalog.base_modality import BaseModality
from datetime import datetime
import os
import pandas as pd


class SpaceTextEdit(QTextEdit):
    wordEnded = pyqtSignal()
    firstCharOfWord = pyqtSignal()

    def keyPressEvent(self, e):
        text = e.text()
        cursor = self.textCursor()
        pos_before = cursor.position()
        doc = self.toPlainText()

        # First character of a word
        if text and not text.isspace():
            prev_char = doc[pos_before - 1] if pos_before > 0 else None
            if pos_before == 0 or (prev_char and prev_char.isspace()):
                self.firstCharOfWord.emit()

        super().keyPressEvent(e)

        # Any whitespace ends the word
        if text and text.isspace():
            self.wordEnded.emit()


class Text(BaseModality):
    def __init__(self):
        super().__init__()
        self.recording = False
        self.logged_word_index = 0
        self.session_dir = None
        self.pending_word_start_ts = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.editor = SpaceTextEdit()
        self.editor.firstCharOfWord.connect(self.on_new_word_started)
        self.editor.wordEnded.connect(self.on_word_ended)
        layout.addWidget(self.editor)
        self.setLayout(layout)

    def start_recording(self, session_dir):
        self.recording = True
        self.session_dir = session_dir
        self.logged_word_index = 0
        self.pending_word_start_ts = None
        self.editor.clear()

    def stop_recording(self):
        # flush any pending word
        if not self.recording:
            return
        self.recording = False

        # if a word was started but not closed by a space, save it now
        if self.pending_word_start_ts is not None:
            words = self.editor.toPlainText().split()
            if len(words) > self.logged_word_index:
                self._save_word(self.pending_word_start_ts, words[self.logged_word_index])
            self.pending_word_start_ts = None

    def on_new_word_started(self):
        """Called at first character of a new word."""
        if self.recording:
            # stamp the time right when the first character is typed
            self.pending_word_start_ts = datetime.utcnow().isoformat()

    def on_word_ended(self):
        """Called when any whitespace character ends the current word."""
        if not self.recording or self.pending_word_start_ts is None:
            return

        words = self.editor.toPlainText().split()
        if len(words) > self.logged_word_index:
            word = words[self.logged_word_index]
            ts = self.pending_word_start_ts
            self._save_word(ts, word)
            self.logged_word_index += 1

        self.pending_word_start_ts = None

    def _save_word(self, timestamp, word):
        """Append a single timestamped word row to pheno.csv."""
        csv_path = os.path.join(self.session_dir, "text.csv")
        df = pd.DataFrame([[timestamp, word]], columns=["timestamp", "content"])
        df.to_csv(csv_path, mode="a", header=not os.path.exists(csv_path), index=False)
