"""Settings dialog — four-tab QDialog.

Tab 1 – Engine    : choose engine, enter API keys
Tab 2 – Hotkeys   : manage (label, target lang, shortcut) pairs
Tab 3 – General   : max-chars threshold, autostart toggle
Tab 4 – History   : read-only list of recent translations
"""

from __future__ import annotations

from datetime import datetime

import requests

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QIcon, QKeySequence, QPalette, QColor
from PySide6.QtWidgets import (
    QApplication,
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

_ENGINE_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "gemini": "gemini-1.5-flash",
    "grok": "grok-2",
    "openrouter": "google/gemini-2.5-flash",
}


def _extract_error_message(resp: requests.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        return resp.text.strip() or f"HTTP {resp.status_code}"

    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            if isinstance(err.get("message"), str):
                return err["message"]
        if isinstance(err, str):
            return err
        if isinstance(payload.get("message"), str):
            return payload["message"]
    return f"HTTP {resp.status_code}"


def _fetch_models(engine: str, api_key: str) -> list[str]:
    timeout = 15
    headers = {"Content-Type": "application/json"}

    if engine == "openai":
        headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.get("https://api.openai.com/v1/models", headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error_message(resp))
        data = resp.json().get("data", [])
        models = sorted(
            item.get("id", "")
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        )
        return [m for m in models if m]

    if engine == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        resp = requests.get("https://api.anthropic.com/v1/models", headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error_message(resp))
        data = resp.json().get("data", [])
        return [
            item.get("id", "")
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        ]

    if engine == "gemini":
        resp = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key},
            timeout=timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error_message(resp))
        models = []
        for item in resp.json().get("models", []):
            if not isinstance(item, dict):
                continue
            methods = item.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            raw_name = item.get("name", "")
            if isinstance(raw_name, str) and raw_name.startswith("models/"):
                models.append(raw_name.split("/", 1)[1])
        return sorted(set(models))

    if engine == "grok":
        headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.get("https://api.x.ai/v1/models", headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error_message(resp))
        data = resp.json().get("data", [])
        return sorted(
            item.get("id", "")
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        )

    if engine == "openrouter":
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/LinguaType/LinguaType",
            "X-Title": "LinguaType",
        }
        resp = requests.get("https://openrouter.ai/api/v1/models", headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error_message(resp))
        data = resp.json().get("data", [])
        return sorted(
            item.get("id", "")
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        )

    raise RuntimeError(f"Model fetching not supported for engine: {engine}")


def _verify_api_key(engine: str, api_key: str) -> tuple[bool, str]:
    if not api_key.strip():
        return False, "API key is empty."
    try:
        if engine == "openrouter":
            headers = {
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/LinguaType/LinguaType",
                "X-Title": "LinguaType",
            }
            resp = requests.get("https://openrouter.ai/api/v1/key", headers=headers, timeout=12)
            if resp.status_code >= 400:
                return False, _extract_error_message(resp)
            return True, "API key is valid."

        models = _fetch_models(engine, api_key)
        if not models:
            return False, "API key worked, but no models were returned."
        return True, "API key is valid."
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Unexpected error: {exc}"


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
        self._verified_keys: dict[str, str] = {}
        self._engine_controls: dict[str, dict[str, QWidget]] = {}
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

        self._openai_model = QComboBox()
        self._openai_model.addItem(_ENGINE_DEFAULT_MODELS["openai"])

        openai_row = QHBoxLayout()
        openai_row.addWidget(self._openai_key)
        openai_link = QLabel('<a href="https://platform.openai.com/api-keys">Get key</a>')
        openai_link.setOpenExternalLinks(True)
        openai_row.addWidget(openai_link)
        self._openai_verify_btn = QPushButton("Verify")
        self._openai_fetch_btn = QPushButton("Fetch")
        self._openai_status = QLabel("")
        self._openai_status.setVisible(False)
        openai_row.addWidget(self._openai_verify_btn)
        openai_row.addWidget(self._openai_fetch_btn)
        openai_row.addWidget(self._openai_status)

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

        self._anthropic_model = QComboBox()
        self._anthropic_model.addItem(_ENGINE_DEFAULT_MODELS["anthropic"])

        anthropic_row = QHBoxLayout()
        anthropic_row.addWidget(self._anthropic_key)
        anthropic_link = QLabel('<a href="https://console.anthropic.com/">Get key</a>')
        anthropic_link.setOpenExternalLinks(True)
        anthropic_row.addWidget(anthropic_link)
        self._anthropic_verify_btn = QPushButton("Verify")
        self._anthropic_fetch_btn = QPushButton("Fetch")
        self._anthropic_status = QLabel("")
        self._anthropic_status.setVisible(False)
        anthropic_row.addWidget(self._anthropic_verify_btn)
        anthropic_row.addWidget(self._anthropic_fetch_btn)
        anthropic_row.addWidget(self._anthropic_status)

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

        self._gemini_model = QComboBox()
        self._gemini_model.addItem(_ENGINE_DEFAULT_MODELS["gemini"])

        gemini_row = QHBoxLayout()
        gemini_row.addWidget(self._gemini_key)
        gemini_link = QLabel('<a href="https://aistudio.google.com/">Get key</a>')
        gemini_link.setOpenExternalLinks(True)
        gemini_row.addWidget(gemini_link)
        self._gemini_verify_btn = QPushButton("Verify")
        self._gemini_fetch_btn = QPushButton("Fetch")
        self._gemini_status = QLabel("")
        self._gemini_status.setVisible(False)
        gemini_row.addWidget(self._gemini_verify_btn)
        gemini_row.addWidget(self._gemini_fetch_btn)
        gemini_row.addWidget(self._gemini_status)

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

        self._grok_model = QComboBox()
        self._grok_model.addItem(_ENGINE_DEFAULT_MODELS["grok"])

        grok_row = QHBoxLayout()
        grok_row.addWidget(self._grok_key)
        grok_link = QLabel('<a href="https://console.x.ai/">Get key</a>')
        grok_link.setOpenExternalLinks(True)
        grok_row.addWidget(grok_link)
        self._grok_verify_btn = QPushButton("Verify")
        self._grok_fetch_btn = QPushButton("Fetch")
        self._grok_status = QLabel("")
        self._grok_status.setVisible(False)
        grok_row.addWidget(self._grok_verify_btn)
        grok_row.addWidget(self._grok_fetch_btn)
        grok_row.addWidget(self._grok_status)

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

        self._openrouter_model = QComboBox()
        self._openrouter_model.addItem(_ENGINE_DEFAULT_MODELS["openrouter"])

        openrouter_row = QHBoxLayout()
        openrouter_row.addWidget(self._openrouter_key)
        openrouter_link = QLabel('<a href="https://openrouter.ai/keys">Get key</a>')
        openrouter_link.setOpenExternalLinks(True)
        openrouter_row.addWidget(openrouter_link)
        self._openrouter_verify_btn = QPushButton("Verify")
        self._openrouter_fetch_btn = QPushButton("Fetch")
        self._openrouter_status = QLabel("")
        self._openrouter_status.setVisible(False)
        openrouter_row.addWidget(self._openrouter_verify_btn)
        openrouter_row.addWidget(self._openrouter_fetch_btn)
        openrouter_row.addWidget(self._openrouter_status)

        pg_openrouter_layout.addRow("OpenRouter API key:", openrouter_row)
        pg_openrouter_layout.addRow("OpenRouter model:", self._openrouter_model)
        self._stacked.addWidget(pg_openrouter)

        self._engine_controls = {
            "openai": {
                "key": self._openai_key,
                "model": self._openai_model,
                "verify": self._openai_verify_btn,
                "fetch": self._openai_fetch_btn,
                "status": self._openai_status,
            },
            "anthropic": {
                "key": self._anthropic_key,
                "model": self._anthropic_model,
                "verify": self._anthropic_verify_btn,
                "fetch": self._anthropic_fetch_btn,
                "status": self._anthropic_status,
            },
            "gemini": {
                "key": self._gemini_key,
                "model": self._gemini_model,
                "verify": self._gemini_verify_btn,
                "fetch": self._gemini_fetch_btn,
                "status": self._gemini_status,
            },
            "grok": {
                "key": self._grok_key,
                "model": self._grok_model,
                "verify": self._grok_verify_btn,
                "fetch": self._grok_fetch_btn,
                "status": self._grok_status,
            },
            "openrouter": {
                "key": self._openrouter_key,
                "model": self._openrouter_model,
                "verify": self._openrouter_verify_btn,
                "fetch": self._openrouter_fetch_btn,
                "status": self._openrouter_status,
            },
        }

        for engine_name, controls in self._engine_controls.items():
            key_edit = controls["key"]
            verify_btn = controls["verify"]
            fetch_btn = controls["fetch"]
            key_edit.textChanged.connect(lambda _text, e=engine_name: self._on_key_changed(e))
            verify_btn.clicked.connect(lambda _checked=False, e=engine_name: self._on_verify_clicked(e))
            fetch_btn.clicked.connect(lambda _checked=False, e=engine_name: self._on_fetch_clicked(e))

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
        self._set_model_value("openai", self._cfg.api_keys.openai_model or _ENGINE_DEFAULT_MODELS["openai"])
        self._anthropic_key.setText(self._cfg.api_keys.anthropic)
        self._set_model_value("anthropic", self._cfg.api_keys.anthropic_model or _ENGINE_DEFAULT_MODELS["anthropic"])
        self._gemini_key.setText(self._cfg.api_keys.gemini)
        self._set_model_value("gemini", self._cfg.api_keys.gemini_model or _ENGINE_DEFAULT_MODELS["gemini"])
        self._grok_key.setText(self._cfg.api_keys.grok)
        self._set_model_value("grok", self._cfg.api_keys.grok_model or _ENGINE_DEFAULT_MODELS["grok"])
        self._openrouter_key.setText(self._cfg.api_keys.openrouter)
        self._set_model_value("openrouter", self._cfg.api_keys.openrouter_model or _ENGINE_DEFAULT_MODELS["openrouter"])

    def _set_model_value(self, engine: str, model_name: str) -> None:
        combo = self._engine_controls[engine]["model"]
        idx = combo.findText(model_name)
        if idx < 0:
            combo.addItem(model_name)
            idx = combo.findText(model_name)
        combo.setCurrentIndex(idx)

    def _on_key_changed(self, engine: str) -> None:
        self._verified_keys.pop(engine, None)
        self._set_status(engine, text="Not verified", ok=False, visible=False)

    def _set_status(self, engine: str, text: str, ok: bool, visible: bool = True) -> None:
        status = self._engine_controls[engine]["status"]
        status.setText(text)
        status.setVisible(visible)
        if not visible:
            return
        color = "#2e7d32" if ok else "#c62828"
        status.setStyleSheet(f"color: {color}; font-weight: 600;")

    def _with_controls_enabled(self, engine: str, enabled: bool) -> None:
        self._engine_controls[engine]["verify"].setEnabled(enabled)
        self._engine_controls[engine]["fetch"].setEnabled(enabled)

    def _on_verify_clicked(self, engine: str) -> None:
        key = self._engine_controls[engine]["key"].text().strip()
        if not key:
            self._set_status(engine, "API key is empty", ok=False)
            return

        self._with_controls_enabled(engine, False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok, message = _verify_api_key(engine, key)
        finally:
            QApplication.restoreOverrideCursor()
            self._with_controls_enabled(engine, True)

        if ok:
            self._verified_keys[engine] = key
            self._set_status(engine, "Verified", ok=True)
        else:
            self._verified_keys.pop(engine, None)
            self._set_status(engine, message, ok=False)

    def _on_fetch_clicked(self, engine: str) -> None:
        key = self._engine_controls[engine]["key"].text().strip()
        if not key:
            self._set_status(engine, "Enter API key before fetching models", ok=False)
            return

        self._with_controls_enabled(engine, False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            models = _fetch_models(engine, key)
        except requests.RequestException as exc:
            self._set_status(engine, f"Network error: {exc}", ok=False)
            return
        except RuntimeError as exc:
            self._set_status(engine, str(exc), ok=False)
            return
        except Exception as exc:
            self._set_status(engine, f"Unexpected error: {exc}", ok=False)
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._with_controls_enabled(engine, True)

        models = [m for m in models if m]
        if not models:
            self._set_status(engine, "No models returned", ok=False)
            return

        combo = self._engine_controls[engine]["model"]
        current = combo.currentText().strip()
        combo.clear()
        combo.addItems(models)
        if current:
            self._set_model_value(engine, current)
        self._set_status(engine, f"Fetched {len(models)} models", ok=True)

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
        cfg.api_keys.openai_model = self._openai_model.currentText().strip() or _ENGINE_DEFAULT_MODELS["openai"]
        cfg.api_keys.anthropic = self._anthropic_key.text().strip()
        cfg.api_keys.anthropic_model = self._anthropic_model.currentText().strip() or _ENGINE_DEFAULT_MODELS["anthropic"]
        cfg.api_keys.gemini = self._gemini_key.text().strip()
        cfg.api_keys.gemini_model = self._gemini_model.currentText().strip() or _ENGINE_DEFAULT_MODELS["gemini"]
        cfg.api_keys.grok = self._grok_key.text().strip()
        cfg.api_keys.grok_model = self._grok_model.currentText().strip() or _ENGINE_DEFAULT_MODELS["grok"]
        cfg.api_keys.openrouter = self._openrouter_key.text().strip()
        cfg.api_keys.openrouter_model = self._openrouter_model.currentText().strip() or _ENGINE_DEFAULT_MODELS["openrouter"]


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
        lang_combo.currentIndexChanged.connect(
            lambda _idx, combo=lang_combo: self._sync_label_with_language(combo)
        )
        self._table.setCellWidget(row, _COL_LANG, lang_combo)

        shortcut_edit = HotkeyEdit()
        shortcut_edit.setKeySequence(QKeySequence(entry.shortcut))
        self._table.setCellWidget(row, _COL_SHORTCUT, shortcut_edit)

    def _sync_label_with_language(self, combo: QComboBox) -> None:
        row = self._find_row_for_widget(combo, _COL_LANG)
        if row < 0:
            return
        # ISO 639-1 abbreviation (best-effort). For languages like zh-CN, this
        # yields 'zh'. For multi-part tags like en-GB it yields 'en'.
        lang_code = combo.currentData()
        if isinstance(lang_code, str) and lang_code:
            iso_639_1 = lang_code.split("-", 1)[0]
        else:
            iso_639_1 = (combo.currentText().strip() or "lang")[:2]
        label_item = self._table.item(row, _COL_LABEL)
        if label_item is None:
            label_item = QTableWidgetItem()
            self._table.setItem(row, _COL_LABEL, label_item)
        label_item.setText(f"→ {iso_639_1}")

    def _find_row_for_widget(self, widget: QWidget, column: int) -> int:
        for row in range(self._table.rowCount()):
            if self._table.cellWidget(row, column) is widget:
                return row
        return -1

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
        self.setObjectName("historyCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
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
            "QWidget#historyCard { "
            "  background-color: #fcfcfc; "
            "  border: 1px solid #e5e5e5; "
            "  border-radius: 8px; "
            "} "
            "QWidget#historyCard:hover { "
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
