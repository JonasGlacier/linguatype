"""Settings dialog — four-tab QDialog.

Tab 1 – Engine    : choose engine, enter API keys
Tab 2 – Hotkeys   : manage (label, target lang, shortcut) pairs
Tab 3 – General   : max-chars threshold, autostart toggle
Tab 4 – History   : read-only list of recent translations
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QIcon, QKeySequence, QPalette, QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QRadioButton,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSpinBox,
    QCheckBox,
    QComboBox,
    QAbstractItemView,
    QKeySequenceEdit,
    QStackedWidget,
    QScrollArea,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
)

from linguatype.config import Config, HotkeyEntry, ApiKeys, save_config, set_autostart, clear_history


# ---------------------------------------------------------------------------
# Language list shown in the hotkeys tab drop-down
# ---------------------------------------------------------------------------

_LANGUAGES: list[tuple[str, str]] = [
    ("en",    "English"),
    ("en-GB", "English (UK)"),
    ("zh-CN", "Chinese (Simplified)"),
    ("zh-TW", "Chinese (Traditional)"),
    ("ja",    "Japanese"),
    ("ko",    "Korean"),
    ("de",    "German"),
    ("fr",    "French"),
    ("es",    "Spanish"),
    ("pt",    "Portuguese"),
    ("pt-BR", "Portuguese (Brazil)"),
    ("it",    "Italian"),
    ("ru",    "Russian"),
    ("ar",    "Arabic"),
    ("nl",    "Dutch"),
    ("pl",    "Polish"),
    ("tr",    "Turkish"),
    ("vi",    "Vietnamese"),
    ("th",    "Thai"),
]

_LANG_CODE_TO_NAME = {code: name for code, name in _LANGUAGES}
_LANG_NAME_TO_CODE = {name: code for code, name in _LANGUAGES}


# ---------------------------------------------------------------------------
# Hotkey capture widget
# ---------------------------------------------------------------------------

class HotkeyEdit(QKeySequenceEdit):
    """Thin wrapper that shows the shortcut in `keyboard`-lib notation."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setMaximumSequenceLength(1)
        self.setStyleSheet("""
            QKeySequenceEdit {
                background-color: #ffffff;
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 4px;
            }
            QKeySequenceEdit:focus {
                border-color: #79A92A;
            }
        """)

    def keySequenceToStr(self) -> str:  # noqa: N802
        ks = self.keySequence()
        if ks.isEmpty():
            return ""
        # PySide6 gives e.g. "Ctrl+Shift+1" which is already compatible
        return ks.toString(QKeySequence.SequenceFormat.NativeText).lower()


# ---------------------------------------------------------------------------
# Engine tab
# ---------------------------------------------------------------------------

class _EngineTab(QWidget):
    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Engine selection
        group = QGroupBox("Translation Engine")
        g_layout = QVBoxLayout(group)
        g_layout.setSpacing(6)

        self._rb_google = QRadioButton("Google Translate  (free, no key required)")
        self._rb_deepl  = QRadioButton("DeepL")
        self._rb_openai = QRadioButton("OpenAI (ChatGPT)")
        self._rb_anthropic = QRadioButton("Anthropic (Claude)")
        self._rb_gemini = QRadioButton("Google Gemini")
        self._rb_grok = QRadioButton("xAI (Grok)")
        self._rb_openrouter = QRadioButton("OpenRouter")

        for rb in (self._rb_google, self._rb_deepl, self._rb_openai,
                   self._rb_anthropic, self._rb_gemini, self._rb_grok,
                   self._rb_openrouter):
            g_layout.addWidget(rb)

        layout.addWidget(group)

        # Stacked config panel
        self._config_group = QGroupBox("Engine Settings")
        config_layout = QVBoxLayout(self._config_group)

        self._stacked = QStackedWidget()
        config_layout.addWidget(self._stacked)
        layout.addWidget(self._config_group)

        # Page 0: Google Translate
        pg_google = QWidget()
        pg_google_layout = QVBoxLayout(pg_google)
        lbl_google = QLabel(
            "Google Translate is free and does not require an API key.\n"
            "Please note that heavy usage may be rate-limited by Google."
        )
        lbl_google.setWordWrap(True)
        pg_google_layout.addWidget(lbl_google)
        pg_google_layout.addStretch()
        self._stacked.addWidget(pg_google)

        # Page 1: DeepL
        pg_deepl = QWidget()
        pg_deepl_layout = QFormLayout(pg_deepl)
        pg_deepl_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._deepl_key = QLineEdit()
        self._deepl_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._deepl_key.setPlaceholderText("Paste your DeepL API key here")

        deepl_row = QHBoxLayout()
        deepl_row.addWidget(self._deepl_key)
        deepl_link = QLabel('<a href="https://www.deepl.com/pro-api">Get free key</a>')
        deepl_link.setOpenExternalLinks(True)
        deepl_row.addWidget(deepl_link)
        pg_deepl_layout.addRow("DeepL API key:", deepl_row)
        self._stacked.addWidget(pg_deepl)

        # Page 2: OpenAI
        pg_openai = QWidget()
        pg_openai_layout = QFormLayout(pg_openai)
        pg_openai_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._openai_key = QLineEdit()
        self._openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._openai_key.setPlaceholderText("Paste your OpenAI API key here")

        self._openai_model = QLineEdit()
        self._openai_model.setPlaceholderText("gpt-4o-mini")

        openai_row = QHBoxLayout()
        openai_row.addWidget(self._openai_key)
        openai_link = QLabel('<a href="https://platform.openai.com/api-keys">Get key</a>')
        openai_link.setOpenExternalLinks(True)
        openai_row.addWidget(openai_link)

        pg_openai_layout.addRow("OpenAI API key:", openai_row)
        pg_openai_layout.addRow("OpenAI model:", self._openai_model)
        self._stacked.addWidget(pg_openai)

        # Page 3: Anthropic
        pg_anthropic = QWidget()
        pg_anthropic_layout = QFormLayout(pg_anthropic)
        pg_anthropic_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._anthropic_key = QLineEdit()
        self._anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._anthropic_key.setPlaceholderText("Paste your Anthropic API key here")

        self._anthropic_model = QLineEdit()
        self._anthropic_model.setPlaceholderText("claude-3-5-sonnet-latest")

        anthropic_row = QHBoxLayout()
        anthropic_row.addWidget(self._anthropic_key)
        anthropic_link = QLabel('<a href="https://console.anthropic.com/">Get key</a>')
        anthropic_link.setOpenExternalLinks(True)
        anthropic_row.addWidget(anthropic_link)

        pg_anthropic_layout.addRow("Anthropic API key:", anthropic_row)
        pg_anthropic_layout.addRow("Anthropic model:", self._anthropic_model)
        self._stacked.addWidget(pg_anthropic)

        # Page 4: Gemini
        pg_gemini = QWidget()
        pg_gemini_layout = QFormLayout(pg_gemini)
        pg_gemini_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._gemini_key = QLineEdit()
        self._gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._gemini_key.setPlaceholderText("Paste your Google Gemini API key here")

        self._gemini_model = QLineEdit()
        self._gemini_model.setPlaceholderText("gemini-1.5-flash")

        gemini_row = QHBoxLayout()
        gemini_row.addWidget(self._gemini_key)
        gemini_link = QLabel('<a href="https://aistudio.google.com/">Get key</a>')
        gemini_link.setOpenExternalLinks(True)
        gemini_row.addWidget(gemini_link)

        pg_gemini_layout.addRow("Gemini API key:", gemini_row)
        pg_gemini_layout.addRow("Gemini model:", self._gemini_model)
        self._stacked.addWidget(pg_gemini)

        # Page 5: Grok
        pg_grok = QWidget()
        pg_grok_layout = QFormLayout(pg_grok)
        pg_grok_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._grok_key = QLineEdit()
        self._grok_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._grok_key.setPlaceholderText("Paste your xAI Grok API key here")

        self._grok_model = QLineEdit()
        self._grok_model.setPlaceholderText("grok-2")

        grok_row = QHBoxLayout()
        grok_row.addWidget(self._grok_key)
        grok_link = QLabel('<a href="https://console.x.ai/">Get key</a>')
        grok_link.setOpenExternalLinks(True)
        grok_row.addWidget(grok_link)

        pg_grok_layout.addRow("Grok API key:", grok_row)
        pg_grok_layout.addRow("Grok model:", self._grok_model)
        self._stacked.addWidget(pg_grok)

        # Page 6: OpenRouter
        pg_openrouter = QWidget()
        pg_openrouter_layout = QFormLayout(pg_openrouter)
        pg_openrouter_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._openrouter_key = QLineEdit()
        self._openrouter_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._openrouter_key.setPlaceholderText("Paste your OpenRouter API key here")

        self._openrouter_model = QLineEdit()
        self._openrouter_model.setPlaceholderText("google/gemini-2.5-flash")

        openrouter_row = QHBoxLayout()
        openrouter_row.addWidget(self._openrouter_key)
        openrouter_link = QLabel('<a href="https://openrouter.ai/keys">Get key</a>')
        openrouter_link.setOpenExternalLinks(True)
        openrouter_row.addWidget(openrouter_link)

        pg_openrouter_layout.addRow("OpenRouter API key:", openrouter_row)
        pg_openrouter_layout.addRow("OpenRouter model:", self._openrouter_model)
        self._stacked.addWidget(pg_openrouter)

        # Connect radio buttons
        self._rb_google.toggled.connect(lambda checked: self._stacked.setCurrentIndex(0) if checked else None)
        self._rb_deepl.toggled.connect(lambda checked: self._stacked.setCurrentIndex(1) if checked else None)
        self._rb_openai.toggled.connect(lambda checked: self._stacked.setCurrentIndex(2) if checked else None)
        self._rb_anthropic.toggled.connect(lambda checked: self._stacked.setCurrentIndex(3) if checked else None)
        self._rb_gemini.toggled.connect(lambda checked: self._stacked.setCurrentIndex(4) if checked else None)
        self._rb_grok.toggled.connect(lambda checked: self._stacked.setCurrentIndex(5) if checked else None)
        self._rb_openrouter.toggled.connect(lambda checked: self._stacked.setCurrentIndex(6) if checked else None)

        layout.addStretch()
        self._load()

    def _load(self) -> None:
        engine = self._cfg.engine
        self._rb_google.setChecked(engine == "google")
        self._rb_deepl.setChecked(engine == "deepl")
        self._rb_openai.setChecked(engine == "openai")
        self._rb_anthropic.setChecked(engine == "anthropic")
        self._rb_gemini.setChecked(engine == "gemini")
        self._rb_grok.setChecked(engine == "grok")
        self._rb_openrouter.setChecked(engine == "openrouter")

        engine_to_idx = {
            "google": 0,
            "deepl": 1,
            "openai": 2,
            "anthropic": 3,
            "gemini": 4,
            "grok": 5,
            "openrouter": 6,
        }
        self._stacked.setCurrentIndex(engine_to_idx.get(engine, 0))

        self._deepl_key.setText(self._cfg.api_keys.deepl)
        self._openai_key.setText(self._cfg.api_keys.openai)
        self._openai_model.setText(self._cfg.api_keys.openai_model or "gpt-4o-mini")
        self._anthropic_key.setText(self._cfg.api_keys.anthropic)
        self._anthropic_model.setText(self._cfg.api_keys.anthropic_model or "claude-3-5-sonnet-latest")
        self._gemini_key.setText(self._cfg.api_keys.gemini)
        self._gemini_model.setText(self._cfg.api_keys.gemini_model or "gemini-1.5-flash")
        self._grok_key.setText(self._cfg.api_keys.grok)
        self._grok_model.setText(self._cfg.api_keys.grok_model or "grok-2")
        self._openrouter_key.setText(self._cfg.api_keys.openrouter)
        self._openrouter_model.setText(self._cfg.api_keys.openrouter_model or "google/gemini-2.5-flash")

    def save_to(self, cfg: Config) -> None:
        if self._rb_deepl.isChecked():
            cfg.engine = "deepl"
        elif self._rb_openai.isChecked():
            cfg.engine = "openai"
        elif self._rb_anthropic.isChecked():
            cfg.engine = "anthropic"
        elif self._rb_gemini.isChecked():
            cfg.engine = "gemini"
        elif self._rb_grok.isChecked():
            cfg.engine = "grok"
        elif self._rb_openrouter.isChecked():
            cfg.engine = "openrouter"
        else:
            cfg.engine = "google"

        cfg.api_keys.deepl = self._deepl_key.text().strip()
        cfg.api_keys.openai = self._openai_key.text().strip()
        cfg.api_keys.openai_model = self._openai_model.text().strip() or "gpt-4o-mini"
        cfg.api_keys.anthropic = self._anthropic_key.text().strip()
        cfg.api_keys.anthropic_model = self._anthropic_model.text().strip() or "claude-3-5-sonnet-latest"
        cfg.api_keys.gemini = self._gemini_key.text().strip()
        cfg.api_keys.gemini_model = self._gemini_model.text().strip() or "gemini-1.5-flash"
        cfg.api_keys.grok = self._grok_key.text().strip()
        cfg.api_keys.grok_model = self._grok_model.text().strip() or "grok-2"
        cfg.api_keys.openrouter = self._openrouter_key.text().strip()
        cfg.api_keys.openrouter_model = self._openrouter_model.text().strip() or "google/gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Hotkeys tab
# ---------------------------------------------------------------------------

_COL_LABEL    = 0
_COL_LANG     = 1
_COL_SHORTCUT = 2


class _HotkeysTab(QWidget):
    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 8)
        layout.setSpacing(8)

        info = QLabel(
            "Each row maps a keyboard shortcut to a target language.\n"
            "Click the Shortcut field and press your key combination."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #555555; font-weight: 500;")
        layout.addWidget(info)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Label", "Target Language", "Shortcut"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                    | QAbstractItemView.EditTrigger.SelectedClicked)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(36)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("+ Add")
        self._del_btn = QPushButton("− Remove")
        self._add_btn.clicked.connect(self._add_row)
        self._del_btn.clicked.connect(self._del_row)
        
        self._del_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffebee;
                color: #c62828;
                border: 1px solid #ffcdd2;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #ffcdd2;
            }
            QPushButton:pressed {
                background-color: #ef9a9a;
            }
        """)
        
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._load()

    def _load(self) -> None:
        self._table.setRowCount(0)
        for entry in self._cfg.hotkeys:
            self._append_entry(entry)

    def _append_entry(self, entry: HotkeyEntry) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        self._table.setItem(row, _COL_LABEL, QTableWidgetItem(entry.label))

        lang_combo = QComboBox()
        for code, name in _LANGUAGES:
            lang_combo.addItem(name, code)
        idx = lang_combo.findData(entry.lang)
        if idx >= 0:
            lang_combo.setCurrentIndex(idx)
        self._table.setCellWidget(row, _COL_LANG, lang_combo)

        shortcut_edit = HotkeyEdit()
        shortcut_edit.setKeySequence(QKeySequence(entry.shortcut))
        self._table.setCellWidget(row, _COL_SHORTCUT, shortcut_edit)

    def _add_row(self) -> None:
        self._append_entry(HotkeyEntry("en", "ctrl+shift+3", "→ New"))

    def _del_row(self) -> None:
        rows = set(idx.row() for idx in self._table.selectedIndexes())
        for row in sorted(rows, reverse=True):
            self._table.removeRow(row)

    def save_to(self, cfg: Config) -> None:
        entries: list[HotkeyEntry] = []
        for row in range(self._table.rowCount()):
            label_item = self._table.item(row, _COL_LABEL)
            label = label_item.text().strip() if label_item else ""

            lang_widget = self._table.cellWidget(row, _COL_LANG)
            lang = lang_widget.currentData() if lang_widget else "en"

            shortcut_widget = self._table.cellWidget(row, _COL_SHORTCUT)
            shortcut = ""
            if isinstance(shortcut_widget, HotkeyEdit):
                shortcut = shortcut_widget.keySequenceToStr()

            if shortcut:
                entries.append(HotkeyEntry(lang=lang, shortcut=shortcut, label=label))

        cfg.hotkeys = entries


# ---------------------------------------------------------------------------
# General tab
# ---------------------------------------------------------------------------

class _GeneralTab(QWidget):
    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        form_group = QGroupBox("Behaviour")
        form = QFormLayout(form_group)

        self._max_chars = QSpinBox()
        self._max_chars.setRange(50, 10000)
        self._max_chars.setSingleStep(50)
        self._max_chars.setValue(cfg.max_chars_confirm)
        self._max_chars.setSuffix(" chars")
        form.addRow("Ask confirmation when text exceeds:", self._max_chars)

        layout.addWidget(form_group)

        startup_group = QGroupBox("System")
        startup_layout = QVBoxLayout(startup_group)
        self._autostart = QCheckBox("Start LinguaType automatically when Windows starts")
        self._autostart.setChecked(cfg.autostart)
        startup_layout.addWidget(self._autostart)
        layout.addWidget(startup_group)

        layout.addStretch()

    def save_to(self, cfg: Config) -> None:
        cfg.max_chars_confirm = self._max_chars.value()
        cfg.autostart = self._autostart.isChecked()


# ---------------------------------------------------------------------------
# History tab
# ---------------------------------------------------------------------------

def _format_timestamp(ts: str) -> str:
    """Format an ISO timestamp for display in history cards."""
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).strftime("%b %d, %Y  %H:%M")
    except ValueError:
        return ts


class HistoryCard(QWidget):
    """A visually appealing card for displaying a single translation history entry."""

    def __init__(self, item: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        
        # Borderless, styled card
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        
        # Header: Language Badge + optional metadata (or arrow)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        
        lang_code = item.get("lang", "").upper()
        lang_name = _LANG_CODE_TO_NAME.get(item.get("lang", ""), lang_code)
        
        lang_badge = QLabel(f"  {lang_name} ({lang_code})  ")
        lang_badge.setStyleSheet(
            "background-color: #79A92A; color: white; border-radius: 4px; "
            "font-weight: bold; font-size: 11px; padding: 2px 0px;"
        )
        header_layout.addWidget(lang_badge)
        header_layout.addStretch()

        timestamp = _format_timestamp(item.get("timestamp", ""))
        if timestamp:
            time_lbl = QLabel(timestamp)
            time_lbl.setStyleSheet("color: #888888; font-size: 11px;")
            header_layout.addWidget(time_lbl)

        layout.addLayout(header_layout)
        
        # Content: Source -> Result with elegant divider
        body_layout = QHBoxLayout()
        body_layout.setSpacing(12)
        
        src_box = QWidget()
        src_box_layout = QVBoxLayout(src_box)
        src_box_layout.setContentsMargins(0, 0, 0, 0)
        src_lbl_hdr = QLabel("SOURCE")
        src_lbl_hdr.setStyleSheet("color: #7a7a7a; font-size: 9px; font-weight: bold;")
        src_text = QLabel(item.get("source", ""))
        src_text.setWordWrap(True)
        src_text.setStyleSheet("color: #333333; font-size: 12px;")
        src_box_layout.addWidget(src_lbl_hdr)
        src_box_layout.addWidget(src_text)
        
        arrow_lbl = QLabel("→")
        arrow_lbl.setStyleSheet("font-size: 20px; color: #a0a0a0; font-weight: 300;")
        arrow_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        res_box = QWidget()
        res_box_layout = QVBoxLayout(res_box)
        res_box_layout.setContentsMargins(0, 0, 0, 0)
        res_lbl_hdr = QLabel("TRANSLATION")
        res_lbl_hdr.setStyleSheet("color: #79A92A; font-size: 9px; font-weight: bold;")
        res_text = QLabel(item.get("result", ""))
        res_text.setWordWrap(True)
        res_text.setStyleSheet("color: #111111; font-size: 12px; font-weight: 500;")
        res_box_layout.addWidget(res_lbl_hdr)
        res_box_layout.addWidget(res_text)
        
        body_layout.addWidget(src_box, 4)
        body_layout.addWidget(arrow_lbl, 1)
        body_layout.addWidget(res_box, 4)
        
        layout.addLayout(body_layout)
        
        # Border & background styling
        self.setStyleSheet(
            "HistoryCard { "
            "  background-color: #fcfcfc; "
            "  border: 1px solid #e5e5e5; "
            "  border-radius: 8px; "
            "} "
            "HistoryCard:hover { "
            "  background-color: #f5faf0; "
            "  border: 1px solid #cde5ab; "
            "}"
        )


class _HistoryTab(QWidget):
    history_cleared = Signal()

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        info = QLabel("Recent translations, newest first (read-only).")
        info.setStyleSheet("color: #555555; font-size: 13px;")
        header_row.addWidget(info)
        header_row.addStretch()

        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.clicked.connect(self._clear_all)
        self._clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffebee;
                color: #c62828;
                border: 1px solid #ffcdd2;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #ffcdd2;
            }
            QPushButton:pressed {
                background-color: #ef9a9a;
            }
            QPushButton:disabled {
                background-color: #f5f5f5;
                color: #bdbdbd;
                border: 1px solid #e0e0e0;
            }
        """)
        header_row.addWidget(self._clear_btn)
        layout.addLayout(header_row)

        self._list = QListWidget()
        self._list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setStyleSheet(
            "QListWidget {"
            "  border: none;"
            "  background-color: transparent;"
            "  outline: none;"
            "}"
            "QListWidget::item {"
            "  padding: 4px 0px;"
            "}"
        )
        # Smooth scrolling
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        layout.addWidget(self._list)

        self.reload(cfg)

    def _clear_all(self) -> None:
        if not self._cfg.translation_history:
            return

        answer = QMessageBox.question(
            self,
            "LinguaType — Clear History",
            "Delete all translation history?\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        clear_history(self._cfg)
        save_config(self._cfg)
        self.reload(self._cfg)
        self.history_cleared.emit()

    def reload(self, cfg: Config) -> None:
        self._cfg = cfg
        self._list.clear()
        self._clear_btn.setEnabled(bool(cfg.translation_history))
        if not cfg.translation_history:
            item = QListWidgetItem("No translations yet.")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            return

        for entry in reversed(cfg.translation_history[-50:]):
            widget = HistoryCard(entry)
            
            list_item = QListWidgetItem(self._list)
            # Set size hint of list item based on card size hint plus vertical padding
            list_item.setSizeHint(widget.sizeHint())
            list_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            
            self._list.addItem(list_item)
            self._list.setItemWidget(list_item, widget)



# ---------------------------------------------------------------------------
# Main Settings dialog
# ---------------------------------------------------------------------------

class SettingsWindow(QDialog):
    """Four-tab settings dialog.

    Emits ``settings_saved`` after the user clicks OK and the config is written.
    """

    settings_saved = Signal(object)   # emits the updated Config

    _TAB_ENGINE = 0
    _TAB_HOTKEYS = 1
    _TAB_GENERAL = 2
    _TAB_HISTORY = 3

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

        self.setWindowTitle("LinguaType - Settings")
        self.setMinimumSize(520, 400)
        self.resize(560, 460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        # Apply palette to change link color from blue to theme color #79A92A
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Link, QColor("#79A92A"))
        self.setPalette(palette)

        # Style tab widget, buttons, form fields, and scrollbars with theme color #79A92A
        self.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #e0e0e0;
                background-color: #ffffff;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #f5f5f5;
                border: 1px solid #e0e0e0;
                border-bottom: none;
                padding: 8px 16px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:hover {
                background-color: #eaeaea;
            }
            QTabBar::tab:selected {
                background-color: #ffffff;
                border-color: #e0e0e0;
                border-bottom: 2px solid #79A92A;
                color: #79A92A;
                font-weight: bold;
            }
            QLineEdit, QSpinBox, QComboBox {
                border: 1px solid #cccccc;
                border-radius: 4px;
                padding: 4px;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #79A92A;
                background-color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._engine_tab   = _EngineTab(cfg)
        self._hotkeys_tab  = _HotkeysTab(cfg)
        self._general_tab  = _GeneralTab(cfg)
        self._history_tab  = _HistoryTab(cfg)
        self._history_tab.history_cleared.connect(self._on_history_cleared)

        self._tabs.addTab(self._engine_tab,  "Engine")
        self._tabs.addTab(self._hotkeys_tab, "Hotkeys")
        self._tabs.addTab(self._general_tab, "General")
        self._tabs.addTab(self._history_tab, "History")
        layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def show_history_tab(self) -> None:
        """Switch to the History tab and refresh its contents."""
        self._history_tab.reload(self._cfg)
        self._tabs.setCurrentIndex(self._TAB_HISTORY)

    def refresh_history(self) -> None:
        """Refresh history list from the current config."""
        self._history_tab.reload(self._cfg)

    def update_config(self, cfg: Config) -> None:
        """Sync in-memory config (e.g. after a new translation)."""
        self._cfg = cfg
        self.refresh_history()

    def _on_history_cleared(self) -> None:
        """Keep parent config in sync after history is cleared from the tab."""
        self.refresh_history()

    def _save(self) -> None:
        self._engine_tab.save_to(self._cfg)
        self._hotkeys_tab.save_to(self._cfg)
        self._general_tab.save_to(self._cfg)

        save_config(self._cfg)
        set_autostart(self._cfg.autostart)

        self.settings_saved.emit(self._cfg)
        self.accept()
