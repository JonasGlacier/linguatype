"""LinguaType entry point.

Ensures only one instance runs (via a named mutex on Windows), sets up
logging, creates the QApplication, and starts the event loop.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    log_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "LinguaType"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "linguatype.log"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Single-instance guard
# ---------------------------------------------------------------------------

_MUTEX_NAME = "Global\\LinguaType_SingleInstance_Mutex"
_mutex_handle = None   # keep reference so GC doesn't close it


def _acquire_single_instance() -> bool:
    """Return True if this is the first instance, False if another is already running."""
    global _mutex_handle
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    last_error = ctypes.windll.kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183
    if last_error == ERROR_ALREADY_EXISTS:
        return False
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _setup_logging()
    log = logging.getLogger(__name__)

    if not _acquire_single_instance():
        # Another instance is already running — bring its window to front
        # by showing a message box (the other instance will not respond here,
        # but at least we don't start a second one).
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "LinguaType is already running.\nFind it in the system tray.",
                "LinguaType",
                0x40,  # MB_ICONINFORMATION
            )
        except Exception:
            pass
        sys.exit(0)

    log.info("Starting LinguaType %s", _get_version())

    # High-DPI support
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from PySide6.QtCore import Qt

    app = QApplication(sys.argv)
    app.setApplicationName("LinguaType")
    app.setApplicationVersion(_get_version())
    app.setQuitOnLastWindowClosed(False)   # keep running when dialogs close

    # Set application icon
    icon_path = Path(__file__).parent / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    from linguatype.app import App
    linguatype_app = App()   # noqa: F841 — kept alive for the duration

    log.info("LinguaType started — listening in the system tray.")
    sys.exit(app.exec())


def _get_version() -> str:
    try:
        from linguatype import __version__
        return __version__
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
