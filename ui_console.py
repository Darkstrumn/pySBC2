import curses
import time
import json
from ui_common import build_dashboard

"""
Curses-based MFD UI.

Provides:
- status dashboard rendering for parsed controller state
- boot diagnostics/status view
- settings panel with simple command console for config updates
"""


class ConsoleMFD:
    """Terminal UI frontend used when pygame UI is unavailable or not selected."""

    def __init__(self, sbc, config_view, config_root, config_path, reload_callback=None):
        self.sbc = sbc
        self.config_view = config_view
        self.config_root = config_root
        self.config_path = config_path
        self.reload_callback = reload_callback
        self.tab = "status"
        self.boot_mode = False
        self.boot_stage = ""
        self.boot_message = ""
        self._boot_spinner = 0
        self._last_scroll = time.monotonic()
        self._scroll_index = 0
        self.status_message = ""
        self.layer = 0
        self.command_mode = False
        self.command_buf = ""
        self.command_result = ""
        self.last_touch = None
        self.screen = curses.initscr()
        curses.noecho()
        curses.cbreak()
        self.screen.nodelay(True)
        self.screen.keypad(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except Exception:
            pass
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_WHITE, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            self.color_accent = curses.color_pair(1)
            self.color_text = curses.color_pair(2)
            self.color_dim = curses.color_pair(3)
        else:
            self.color_accent = 0
            self.color_text = 0
            self.color_dim = 0

    def teardown(self):
        """Restore terminal state on exit."""
        try:
            self.screen.keypad(False)
            curses.nocbreak()
            curses.echo()
            curses.endwin()
        except Exception:
            pass

    def _safe_add(self, y, x, text, attr=0):
        """Best-effort safe text draw that avoids curses bounds exceptions."""
        try:
            self.screen.addstr(y, x, text[: max(0, self.width - x - 1)], attr)
        except curses.error:
            pass

    def _handle_input(self):
        """Handle keyboard/mouse input for tab switching and command mode."""
        try:
            key = self.screen.getch()
        except Exception:
            return
        if key == -1:
            return
        if self.command_mode:
            if key in (10, 13):
                self._run_command(self.command_buf)
                self.command_buf = ""
                self.command_mode = False
            elif key in (27,):
                self.command_buf = ""
                self.command_mode = False
            elif key in (8, 127, curses.KEY_BACKSPACE):
                self.command_buf = self.command_buf[:-1]
            elif 32 <= key <= 126:
                self.command_buf += chr(key)
            return
        if key == ord(":") and self.tab == "settings":
            self.command_mode = True
            self.command_buf = ""
            self.command_result = ""
            return
        if key in (ord("s"), ord("S")):
            self.tab = "settings"
        elif key in (ord("d"), ord("D")):
            self.tab = "status"
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, _ = curses.getmouse()
            except Exception:
                return
            if my == 0:
                if 2 <= mx <= 10:
                    self.tab = "status"
                elif 12 <= mx <= 21:
                    self.tab = "settings"

    def handle_touch(self, x, y):
        """Map touchscreen taps to tab selection zones."""
        self.last_touch = (x, y)
        if y == 0:
            if 2 <= x <= 10:
                self.tab = "status"
            elif 12 <= x <= 21:
                self.tab = "settings"

    def _draw_tabs(self):
        """Render status/settings tab strip."""
        self._safe_add(0, 2, "[STATUS]", self.color_accent if self.tab == "status" else self.color_dim)
        self._safe_add(0, 12, "[SETTINGS]", self.color_accent if self.tab == "settings" else self.color_dim)
        self._safe_add(1, 2, "-" * min(self.width - 4, 60), self.color_accent)

    def set_boot_mode(self, enabled, stage="", message=""):
        """Switch into/out of boot diagnostics view."""
        self.boot_mode = enabled
        self.boot_stage = stage
        self.boot_message = message
        if enabled:
            self.status_message = ""

    def update_boot(self, stage=None, message=None):
        """Update boot stage/status text."""
        if stage is not None:
            self.boot_stage = stage
        if message is not None:
            self.boot_message = message
            self.status_message = ""

    def set_status(self, message):
        """Set transient status line shown in dashboard."""
        self.status_message = message

    def set_layer(self, layer):
        """Expose active macro layer in UI."""
        self.layer = layer

    def render(self, state):
        """Render one UI frame for current parsed state."""
        self._handle_input()
        self.height, self.width = self.screen.getmaxyx()
        self.screen.erase()

        self._draw_tabs()

        if self.tab == "settings":
            self._render_settings()
            self.screen.refresh()
            return
        if self.boot_mode:
            self._render_boot()
            self.screen.refresh()
            return

        data = build_dashboard(state, self.sbc)
        if self.last_touch is not None:
            tx, ty = self.last_touch
            data["lines"].append(f"Touch: X:{tx:>3}  Y:{ty:>3}")
        data["pressed"].extend(self.sbc.get_held_controls(data["pressed"]))
        self._safe_add(3, 2, data["title"], self.color_accent)
        y = 4
        for line in data["lines"]:
            self._safe_add(y, 2, line, self.color_text)
            y += 1
        self._safe_add(9, 2, f"Layer: {self.layer}", self.color_dim)
        self._render_pressed_panel(data["pressed"])

        if self.status_message:
            self._safe_add(self.height - 2, 2, self.status_message, self.color_dim)
        self._safe_add(self.height - 1, 2, "Hold Eject+CockpitHatch+Ignition+Start to quit", self.color_dim)
        self.screen.refresh()

    def _render_pressed_panel(self, pressed):
        """Render right-side list of currently active/held controls."""
        left_width = max(40, int(self.width * 0.62))
        panel_x = left_width + 1
        panel_w = max(20, self.width - panel_x - 2)
        panel_h = max(6, self.height - 6)
        top = 3

        self._safe_add(top, panel_x, "+" + "-" * (panel_w - 2) + "+", self.color_accent)
        for row in range(1, panel_h - 1):
            self._safe_add(top + row, panel_x, "|" + " " * (panel_w - 2) + "|", self.color_dim)
        self._safe_add(top + panel_h - 1, panel_x, "+" + "-" * (panel_w - 2) + "+", self.color_accent)
        self._safe_add(top + 1, panel_x + 2, "Pressed Buttons", self.color_accent)

        list_y = top + 3
        list_h = max(1, panel_h - 4)
        if not pressed:
            self._safe_add(list_y, panel_x + 2, "(none)", self.color_dim)
            self._scroll_index = 0
            return

        now = time.monotonic()
        if len(pressed) > list_h:
            if now - self._last_scroll >= 0.8:
                self._scroll_index = (self._scroll_index + 1) % len(pressed)
                self._last_scroll = now
            for i in range(list_h):
                idx = (self._scroll_index + i) % len(pressed)
                name = pressed[idx]
                self._safe_add(list_y + i, panel_x + 2, name.ljust(panel_w - 4), self.color_text)
        else:
            self._scroll_index = 0
            for i, name in enumerate(pressed):
                self._safe_add(list_y + i, panel_x + 2, name.ljust(panel_w - 4), self.color_text)


    def _render_boot(self):
        """Render boot diagnostics overlay used during startup sequence."""
        spinner = ["-", "\\", "|", "/"][self._boot_spinner % 4]
        self._boot_spinner += 1
        self._safe_add(3, 2, "STEEL BATTALION CONTROLLER BIOS", self.color_accent)
        self._safe_add(4, 2, "Power On Self Test", self.color_text)
        self._safe_add(6, 2, f"[{spinner}] Stage: {self.boot_stage}", self.color_text)
        self._safe_add(7, 2, f"Status: {self.boot_message}", self.color_text)
        self._safe_add(9, 2, "Diagnostics:", self.color_accent)
        toggle_labels = [
            ("ToggleFilterControl", "Filter Control"),
            ("ToggleOxygenSupply", "Oxygen Supply"),
            ("ToggleFuelFlowRate", "Fuel Flow"),
            ("ToggleBufferMaterial", "Buffer Material"),
            ("ToggleVTLocation", "VT Location"),
        ]
        diag = getattr(self.sbc, "diag_status", {})
        diag_lines = [
            f"USB HID controller .... {diag.get('usb', 'PENDING')}",
            f"LED interface .......... {diag.get('led', 'PENDING')}",
            f"Control channels ....... {diag.get('control', 'PENDING')}",
            f"Calibration cache ...... {diag.get('calibration', 'PENDING')}",
            f"Input matrix ........... {diag.get('input', 'PENDING')}",
            "Toggle States:",
        ]
        for key, label in toggle_labels:
            idx = self.sbc.button_name_to_index.get(key)
            is_on = self.sbc.get_button_state(idx) if idx is not None else False
            status = "OK" if is_on else "Waiting"
            diag_lines.append(f" - {label:<15} {status}")
        y = 10
        for line in diag_lines:
            self._safe_add(y, 4, line, self.color_text)
            y += 1
        self._safe_add(self.height - 2, 2, "Press required controls to continue...", self.color_dim)
        self._safe_add(self.height - 1, 2, "Touch placeholder: Settings tab available", self.color_dim)

    def _render_settings(self):
        """Render settings summary and command-line prompt."""
        self._safe_add(3, 2, "MFD SETTINGS", self.color_accent)
        rows = [
            f"Active Profile: {self.config_view.get('active_profile', 'default')}",
            f"LED Mode: {self.config_view.get('led_mode', 'toggle')}",
            f"Macro Output: {self.config_view.get('macro_output', 'log')}",
            f"Gear Reverse Flash: {self.config_view.get('gear_reverse_flash', True)}",
            f"Poll Interval: {self.config_view.get('poll_interval_ms', 4)} ms",
            f"Flash Period: {self.config_view.get('flash_period_s', 0.3)} s",
        ]
        y = 5
        for row in rows:
            self._safe_add(y, 2, row, self.color_text)
            y += 2
        self._safe_add(self.height - 4, 2, "Commands: profile add|del|switch <name> | macro set|del|show <name> <json>", self.color_dim)
        self._safe_add(self.height - 3, 2, "Commands: macro list | profile list | layer_cycle <button> | save | reload | vars", self.color_dim)
        if self.command_mode:
            self._safe_add(self.height - 2, 2, f"> {self.command_buf}", self.color_text)
        else:
            self._safe_add(self.height - 2, 2, "Press ':' to enter command mode", self.color_dim)
        if self.command_result:
            self._safe_add(self.height - 1, 2, self.command_result, self.color_dim)
        else:
            self._safe_add(self.height - 1, 2, "Press 'd' for status, 's' for settings", self.color_dim)

    def _run_command(self, command):
        """Execute settings commands entered from command mode."""
        parts = command.strip().split()
        if not parts:
            return
        try:
            action = parts[0].lower()
            if action == "profile" and len(parts) >= 3:
                op = parts[1].lower()
                name = parts[2]
                profiles = self.config_root.setdefault("profiles", {})
                if op == "add":
                    profiles.setdefault(name, {})
                    self.config_root["active_profile"] = name
                elif op == "del":
                    profiles.pop(name, None)
                    if self.config_root.get("active_profile") == name:
                        self.config_root["active_profile"] = next(iter(profiles.keys()), "default")
                elif op == "switch":
                    if name in profiles:
                        self.config_root["active_profile"] = name
                self._refresh_view()
                self._save_config()
                self.command_result = "Profile updated (restart to apply)."
                return
            if action == "profile" and len(parts) == 2 and parts[1] == "list":
                self.command_result = f"Profiles: {', '.join(self.config_root.get('profiles', {}).keys())}"
                return
            if action == "macro" and len(parts) >= 3:
                op = parts[1].lower()
                name = parts[2]
                profile = self._active_profile()
                macros = profile.setdefault("macros", {})
                if op == "del":
                    macros.pop(name, None)
                elif op == "show":
                    self.command_result = f"{name}: {macros.get(name)}"
                    return
                elif op == "set":
                    payload = " ".join(parts[3:])
                    macros[name] = json.loads(payload)
                elif op == "list":
                    self.command_result = f"Macros: {', '.join(macros.keys())}"
                    return
                self._save_config()
                self.command_result = "Macro updated (restart to apply)."
                return
            if action == "macro" and len(parts) == 2 and parts[1] == "list":
                profile = self._active_profile()
                macros = profile.get("macros", {})
                self.command_result = f"Macros: {', '.join(macros.keys())}"
                return
            if action == "layer_cycle" and len(parts) == 2:
                profile = self._active_profile()
                profile["layer_cycle_button"] = parts[1]
                self._save_config()
                self.command_result = "Layer cycle button updated (restart to apply)."
                return
            if action == "save":
                self._save_config()
                self.command_result = "Config saved."
                return
            if action == "reload":
                if self.reload_callback is not None:
                    self.reload_callback()
                    self.command_result = "Reloaded config."
                else:
                    self.command_result = "Reload callback not set."
                return
            if action == "vars" and len(parts) >= 2:
                op = parts[1].lower()
                if self.reload_callback is not None:
                    self.reload_callback(vars_only=True, clear_vars=(op == "clear"))
                    self.command_result = "Vars updated."
                else:
                    self.command_result = "Reload callback not set."
                return
            self.command_result = "Unknown command."
        except Exception as exc:
            self.command_result = f"Command error: {exc}"

    def _active_profile(self):
        """Return mutable active profile dictionary from config root."""
        profiles = self.config_root.setdefault("profiles", {})
        name = self.config_root.get("active_profile", "default")
        return profiles.setdefault(name, {})

    def _refresh_view(self):
        """Rebuild flattened config view used by settings page."""
        profile = self._active_profile()
        view = dict(self.config_root)
        view.update(profile)
        self.config_view = view

    def _save_config(self):
        """Persist current config root to disk."""
        import json
        from pathlib import Path

        Path(self.config_path).write_text(json.dumps(self.config_root, indent=2))
