import sys

from ui_console import ConsoleMFD

"""UI backend selector with graceful fallback behavior."""


def init_ui(ui_mode, sbc, config_view, config_root, config_path, reload_callback=None):
    """
    Create a UI backend instance based on requested mode.

    Modes:
    - `console`: curses UI
    - `pygame`: pygame UI
    - `auto`: try pygame, fallback to console
    """
    if ui_mode in ("pygame", "auto"):
        try:
            from ui_pygame import PygameMFD
            return PygameMFD(sbc, config_view, config_root, config_path, reload_callback)
        except Exception as exc:
            mode = "trying console" if ui_mode == "auto" else "running without an MFD"
            print(f"Pygame MFD unavailable ({exc}); {mode}.", file=sys.stderr)
    if ui_mode in ("console", "auto"):
        try:
            return ConsoleMFD(sbc, config_view, config_root, config_path, reload_callback=reload_callback)
        except Exception as exc:
            print(f"Console MFD unavailable ({exc}).", file=sys.stderr)
    return None
