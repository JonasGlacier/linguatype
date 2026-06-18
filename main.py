"""LinguaType entry point.

Ensures only one instance runs (via a named mutex on Windows), sets up
logging, creates the Tk root, and starts the event loop.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

import customtkinter as ctk
import tkinter as tk


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


_MUTEX_NAME = "Global\\LinguaType_SingleInstance_Mutex"
_mutex_handle = None


def _acquire_single_instance() -> bool:
    global _mutex_handle
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    last_error = ctypes.windll.kernel32.GetLastError()
    if last_error == 183:
        return False
    return True


def main() -> None:
    _setup_logging()
    log = logging.getLogger(__name__)

    if not _acquire_single_instance():
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "LinguaType is already running.\nFind it in the system tray.",
                "LinguaType",
                0x40,
            )
        except Exception:
            pass
        sys.exit(0)

    log.info("Starting LinguaType %s", _get_version())

    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("green")

    root = tk.Tk()
    root.withdraw()

    from linguatype.app import App
    _app = App(root)  # noqa: F841 — kept alive for the duration

    log.info("LinguaType started — listening in the system tray.")
    root.mainloop()


def _get_version() -> str:
    try:
        from linguatype import __version__
        return __version__
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
