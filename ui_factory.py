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
    if ui_mode == "console":
        try:
            return ConsoleMFD(sbc, config_view, config_root, config_path, reload_callback=reload_callback)
        except Exception:
            return None
    if ui_mode == "pygame":
        try:
            from ui_pygame import PygameMFD
        except Exception:
            return None
        try:
            return PygameMFD(sbc)
        except Exception:
            return None
    if ui_mode == "auto":
        try:
            from ui_pygame import PygameMFD
            return PygameMFD(sbc)
        except Exception:
            try:
                return ConsoleMFD(sbc, config_view, config_root, config_path, reload_callback=reload_callback)
            except Exception:
                return None
    return None
