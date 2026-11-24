import platform
import re
import subprocess
import time
from functools import lru_cache
from pathlib import Path

from mfd_layout import MFDLayout
from mfd_pages import MFDSettingsPages
from mfd_settings import MFDSettings, THEMES
from ship_power import POWER_CONTROLS, PREFLIGHT_SWITCHES
from ui_common import build_dashboard, gear_label

"""Pygame-based MFD UI backend."""


N52_CONTROLS = (
    ("KEY_TAB", "01  Tab"), ("KEY_Q", "02  Q"), ("KEY_W", "03  W"),
    ("KEY_E", "04  E"), ("KEY_R", "05  R"), ("KEY_CAPSLOCK", "06  Caps"),
    ("KEY_A", "07  A"), ("KEY_S", "08  S"), ("KEY_D", "09  D"),
    ("KEY_F", "10  F"), ("KEY_LEFTSHIFT", "11  Shift"), ("KEY_Z", "12  Z"),
    ("KEY_X", "13  X"), ("KEY_C", "14  C"), ("BTN_MIDDLE", "15  Wheel click"),
    ("REL_WHEEL_UP", "Wheel up"), ("REL_WHEEL_DOWN", "Wheel down"),
    ("KEY_UP", "D-pad up"), ("KEY_DOWN", "D-pad down"),
    ("KEY_LEFT", "D-pad left"), ("KEY_RIGHT", "D-pad right"),
    ("KEY_SPACE", "Thumb pad"), ("KEY_LEFTALT", "Thumb button"),
)


THEME_ACCENTS = dict(zip(THEMES, (
    (255, 147, 46), (255, 176, 68), (101, 204, 250), (108, 227, 180),
    (185, 222, 112), (184, 164, 255), (246, 212, 109),
)))


class PygameMFD(MFDSettingsPages, MFDSettings):
    """Graphical dashboard UI used as an alternative to curses console UI."""

    def __init__(self, sbc, config_view, config_root, config_path, reload_callback=None):
        """Initialize pygame window, fonts, colors, and runtime UI state."""
        self.sbc = sbc
        self.config_view = config_view
        self.config_root = config_root
        self.config_path = Path(config_path)
        self.reload_callback = reload_callback
        self.tab = "main"
        project = Path(__file__).resolve().parent
        self.layout = MFDLayout(project / "mfd" / "panel.html")
        try:
            revision = subprocess.check_output(
                ["git", "describe", "--tags", "--always", "--dirty"],
                cwd=str(project), stderr=subprocess.DEVNULL, timeout=1,
            ).decode().strip()
        except (OSError, subprocess.SubprocessError):
            revision = "revision unavailable"
        self.build = f"Build: {revision}"
        self.editor = None
        self.profile_choice = None
        self.control = None
        self._select_macro("")
        self.labels = [self._indicator_label(name) for name in self.sbc.button_names]
        self.targets = []
        self.pending_gates = None
        self.pending_bindings = None
        self.settings_surface = None
        self.settings_page = 0
        self.game_voice_keys = {}
        self.aux_key_bindings = lambda surface: {}
        try:
            import pygame as _pygame
        except ImportError as exc:
            raise RuntimeError(f"pygame import failed: {exc}") from exc
        self.pygame = _pygame
        self.pygame.init()
        try:
            self.screen = self.pygame.display.set_mode((800, 480))
            self.pygame.mouse.set_visible(False)
        except self.pygame.error:
            self.pygame.quit()
            raise
        self.pygame.display.set_caption("SBC MFD")
        self.clock = self.pygame.time.Clock()
        self.font_title = self.pygame.font.SysFont("DejaVu Sans", 22)
        self.font_label = self.pygame.font.SysFont("DejaVu Sans", 18)
        self.font_small = self.pygame.font.SysFont("DejaVu Sans", 16)
        self._render_text = lru_cache(maxsize=384)(self._render_label)
        self.bg = (10, 12, 18)
        self.panel = (20, 24, 36)
        self.accent = (70, 170, 200)
        self.text = (220, 230, 240)
        self.dim = (130, 140, 150)
        self.status_message = ""
        self.aux_held = {}
        self.aux_released = ""
        self.aux_release_until = 0.0
        self.boot_mode = False
        self.boot_stage = ""
        self.boot_message = ""
        self._boot_spinner = 0
        self.layer = 0

    def teardown(self):
        """Shut down pygame cleanly."""
        try:
            self.pygame.quit()
        except Exception:
            pass

    def set_boot_mode(self, enabled, stage="", message=""):
        """Switch into/out of boot status view."""
        self.boot_mode = enabled
        self.boot_stage = stage
        self.boot_message = message
        if enabled:
            self.status_message = ""

    def update_boot(self, stage=None, message=None):
        """Update boot status text."""
        if stage is not None:
            self.boot_stage = stage
        if message is not None:
            self.boot_message = message
            self.status_message = ""

    def set_status(self, message):
        """Set transient status message."""
        self.status_message = message

    def set_aux_key(self, surface, code, name, pressed, action):
        """Display the physical key state independently of the timed macro output."""
        label = {"game_voice": "GameVoice", "nostromo_n52": "N52"}.get(surface, surface)
        mapping = f"  /  {action}" if action else ""
        identity = (surface, code)
        if pressed:
            self.aux_held[identity] = f"{label} {name} held{mapping}"
        else:
            self.aux_held.pop(identity, None)
            self.aux_released = f"{label} {name} released{mapping}"
            self.aux_release_until = time.monotonic() + 2.0

    def _footer_status(self):
        if self.aux_held:
            return list(self.aux_held.values())[-1]
        if time.monotonic() < self.aux_release_until:
            return self.aux_released
        return self.status_message

    def set_layer(self, layer):
        """Expose active macro layer in UI."""
        self.layer = layer

    @staticmethod
    def _render_label(font, label, color):
        return font.render(label, True, color)

    def _text(self, label, x, y, font=None, color=None, max_width=None):
        surface = self._render_text(font or self.font_small, str(label), color or self.text)
        area = None if max_width is None else (0, 0, max_width, surface.get_height())
        self.screen.blit(surface, (x, y), area)

    def _box(self, rect, color=None):
        self.pygame.draw.rect(self.screen, color or self.panel, rect)

    def _button(self, label, rect, action, selected=False):
        self._box(rect, tuple(value // 4 for value in self.accent) if selected else self.panel)
        self._text(label, rect[0] + 12, rect[1] + 13, self.font_label)
        self.targets.append((self.pygame.Rect(rect), action))

    def _open_page(self, page):
        self.tab = page
        self.editor = None
        if page == "auxiliary":
            self._open_auxiliary()
        elif page == "profiles":
            theme = self.config_view.get("mfd_theme", "elite")
            self.theme_choice = theme if theme in THEMES else "elite"

    def _open_auxiliary(self):
        self.pending_gates = dict(self.config_view.get("aux_surface_switches", {}))
        self.pending_bindings = {
            surface: dict(bindings)
            for surface, bindings in self.config_view.get("aux_key_macros", {}).items()
        }
        self._select_settings_surface(None)

    def _select_settings_surface(self, surface):
        self.settings_surface = surface
        self.settings_page = 0
        if surface == "game_voice":
            self.game_voice_keys = self.aux_key_bindings(surface)

    def _next_gate(self, surface):
        other_gates = {gate for name, gate in self.pending_gates.items() if name != surface}
        choices = [None] + [
            name for name in self.sbc.button_names
            if (name.startswith("Toggle") or name in POWER_CONTROLS) and name not in other_gates
        ]
        current = self.pending_gates.get(surface)
        index = choices.index(current) if current in choices else -1
        self.pending_gates[surface] = choices[(index + 1) % len(choices)]

    def _next_macro(self, key):
        choices = [None] + sorted(self.config_view.get("macros", {}))
        bindings = self.pending_bindings.setdefault(self.settings_surface, {})
        current = bindings.get(key, bindings.get("*"))
        index = choices.index(current) if current in choices else -1
        bindings[key] = choices[(index + 1) % len(choices)]

    def _save_settings(self):
        self._apply_from_panel(kind="auxiliary", settings={
            "aux_surface_switches": dict(self.pending_gates),
            "aux_key_macros": self.pending_bindings,
        })

    @staticmethod
    def _indicator_label(name):
        for prefix, short in (("MultiMon", "Multi "), ("MainMon", "Main "),
                              ("Function", ""), ("WeaponCtrl", "Weapon "),
                              ("RightJoy", "R "), ("LeftJoy", "L "), ("Toggle", "")):
            if name.startswith(prefix):
                name = short + name[len(prefix):]
                break
        return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)

    def _render_indicators(self, state, rect):
        left, top, width, _ = rect
        column = width // 5
        for index, name in enumerate(self.labels):
            x = left + 10 + index % 5 * column
            y = top + 35 + index // 5 * 30
            led = self.sbc.button_to_led_name.get(index)
            held = state["buttons"][index]
            level = self.sbc.led_state.get(self.sbc.led_name_to_id.get(led), 0)
            if led is None:
                level = self.sbc.INTENSITY_MAX if held else 0
            fraction = level / self.sbc.INTENSITY_MAX
            color = tuple(int(42 + (value - 42) * fraction) for value in self.accent)
            self.pygame.draw.circle(self.screen, color, (x + 5, y + 10), 5)
            self._text(name, x + 15, y, color=self.text if held or level else self.dim,
                       max_width=column - 22)
            if held:
                self._box((x + 14, y + 19, column - 24, 2), self.accent)

    def _render_diagnostics(self, state):
        data = build_dashboard(state, self.sbc)
        self._box((16, 76, 475, 338))
        self._box((505, 76, 279, 338))
        self._text("FLIGHT CONTROLS", 32, 90, self.font_label, self.accent)
        self._text(gear_label(state["gear"]), 34, 125, self.font_title)
        self._text("GEAR", 66, 129, color=self.dim)
        self._text(f"TUNER  {state['tuner']}     LAYER  {self.layer}", 180, 129, color=self.dim)
        for index, line in enumerate(data["lines"][:4]):
            self._text(line, 34, 168 + index * 26)
        for index, (surface, label) in enumerate((("game_voice", "Game Voice"), ("nostromo_n52", "Nostromo n52"))):
            switch = self.config_view.get("aux_surface_switches", {}).get(surface)
            button = self.sbc.button_name_to_index.get(switch)
            enabled = button is not None and state["buttons"][button]
            y = 294 + index * 42
            color = self.accent if enabled else self.dim
            self.pygame.draw.circle(self.screen, color, (42, y + 9), 5)
            self._text(label, 57, y)
            self._text("SWITCH ON" if enabled else "SWITCH OFF", 278, y, color=color)
        self._text("ACTIVE BUTTONS", 520, 90, self.font_label, self.accent)
        for index, name in enumerate(data["pressed"][:12] or ["None"]):
            self._text(name, 520, 125 + index * 22)

    def _render_auxiliary(self):
        for index, (surface, label) in enumerate((
            (None, "Switches"), ("nostromo_n52", "Nostromo N52"), ("game_voice", "GameVoice"),
        )):
            self._button(label, (22 + index * 230, 73, 214, 45),
                         lambda surface=surface: self._select_settings_surface(surface),
                         self.settings_surface == surface)

        if self.settings_surface is None:
            for surface, label, y in (
                ("game_voice", "Game Voice", 151), ("nostromo_n52", "Nostromo n52", 214),
            ):
                self._text(label, 22, y + 15, self.font_label)
                gate = self.pending_gates.get(surface)
                self._button(gate[6:] if gate and gate.startswith("Toggle") else (gate or "Disabled"),
                             (235, y, 340, 46), lambda surface=surface: self._next_gate(surface))
        else:
            self._render_binding_page()
        self._button("Save & Apply", (604, 399, 180, 45), self._save_settings, selected=True)

    def _render_binding_page(self):
        bindings = self.pending_bindings.get(self.settings_surface, {})
        if self.settings_surface == "nostromo_n52":
            controls = dict(N52_CONTROLS)
        else:
            controls = {"*": "Unmapped buttons"}
            controls.update(self.game_voice_keys)
        for key in bindings:
            controls.setdefault(key, key)
        entries = list(controls.items())
        page_size = 10
        start = self.settings_page * page_size
        for index, (key, label) in enumerate(entries[start:start + page_size]):
            x = 22 + (index // 5) * 378
            y = 131 + (index % 5) * 50
            macro = bindings.get(key, bindings.get("*")) or "Unassigned"
            rect = (x, y, 360, 46)
            self._box(rect)
            self._text(label[:36], x + 10, y + 4, color=self.accent)
            self._text(macro[:36], x + 10, y + 24)
            self.targets.append((self.pygame.Rect(rect), lambda key=key: self._next_macro(key)))
        if start:
            self._button("Previous", (22, 399, 130, 45), lambda: self._move_settings_page(-1))
        if start + page_size < len(entries):
            self._button("Next", (164, 399, 110, 45), lambda: self._move_settings_page(1))
        self._text(f"Page {self.settings_page + 1} / {max(1, (len(entries) + 9) // 10)}", 300, 414)
        if self.settings_surface == "game_voice" and not self.game_voice_keys:
            self._text("Connect GameVoice and reopen this tab to see its buttons.", 22, 363, color=self.dim)

    def _move_settings_page(self, offset):
        self.settings_page += offset

    def render(self, state):
        """Render the startup view or the active MFD page."""
        pygame = self.pygame
        for event in pygame.event.get():
            if self.boot_mode:
                continue
            if event.type == pygame.KEYDOWN:
                if self.editor:
                    keys = {pygame.K_RETURN: "Done", pygame.K_ESCAPE: "Cancel",
                            pygame.K_BACKSPACE: "Delete", pygame.K_LEFT: "<", pygame.K_RIGHT: ">"}
                    if event.key in keys:
                        self._edit_key(keys[event.key])
                    elif getattr(event, "unicode", "") and event.unicode.isprintable():
                        self._insert_text(event.unicode)
                elif event.key == pygame.K_s:
                    self._open_page("settings")
                elif event.key == pygame.K_d:
                    self._open_page("main")
            if not self.sbc.touch_enabled:
                if event.type == getattr(pygame, "FINGERUP", None):
                    width, height = self.screen.get_size()
                    self.handle_touch(int(event.x * width), int(event.y * height))
                elif (event.type == pygame.MOUSEBUTTONUP and event.button == 1
                      and not getattr(event, "touch", False)):
                    self.handle_touch(*event.pos)
        if self.boot_mode:
            self._render_boot(state)
            return
        self.targets.clear()
        self.screen.fill(self.bg)
        theme = self.config_view.get("mfd_theme", "elite")
        self.accent = THEME_ACCENTS.get(theme, THEME_ACCENTS["elite"])
        confirmation = self.sbc.hold_confirmations.get("TankDetach")
        power = self.sbc.ship_power
        active = self.config_root.get("active_profile", "default")
        values = {
            "theme": THEMES.get(theme, THEMES["elite"]),
            "profile": f"Profile  {active}",
            "flight": f"Gear  {gear_label(state['gear'])}     Tuner  {state['tuner']}     Layer  {self.layer}",
            "confirmation": (
                f"Tank Detach  {confirmation.phase.title()}" if confirmation and confirmation.phase != "idle"
                else f"Hatch {'CLOSED' if power.hatch_closed else 'OPEN'}   "
                     f"Ignition {power.ignition.upper()}   Drives {'ON' if power.engines else 'STANDBY'}"
            ),
        }
        if self.tab == "about":
            import usb
            sdl = ".".join(map(str, pygame.get_sdl_version()))
            values.update({
                "build": self.build,
                "runtime": f"Python {platform.python_version()} / Pygame {pygame.version.ver} / SDL {sdl}",
                "display": f"Display driver: {pygame.display.get_driver()}",
                "touch": "Touch: direct input active" if self.sbc.touch_enabled else "Touch: SDL input",
                "usb": f"PyUSB {getattr(usb, '__version__', 'version unavailable')}",
            })
        widgets = {"indicators": lambda rect: self._render_indicators(state, rect)}
        self.layout.draw(self, self.layout.header, values, widgets)
        if self.tab not in ("main", "settings"):
            self.layout.draw(self, self.layout.pages["settings-back"], values, widgets)
        if self.editor:
            self._render_editor()
        elif self.tab == "main" and power.message.startswith("Hatch interlock"):
            self._preflight(state, "HATCH INTERLOCK", power.message, top=76, required_on=False)
        elif self.tab == "main" and power.message.startswith("Ignition interlock"):
            self._preflight(state, "IGNITION INTERLOCK", power.message, top=76)
        elif self.tab in self.layout.pages:
            self.layout.draw(self, self.layout.pages[self.tab], values, widgets)
        elif self.tab == "diagnostics":
            self._render_diagnostics(state)
        else:
            getattr(self, "_render_" + self.tab)()
        status = self.sbc.ship_power.message or self._footer_status()
        if status:
            self._text(status, 22, 450, color=self.dim, max_width=752)
        pygame.display.flip()

    def handle_touch(self, x, y):
        """Activate the visible control at the release coordinate."""
        if not self.boot_mode:
            for rect, action in self.targets:
                if rect.collidepoint(x, y):
                    action()
                    self.targets.clear()
                    break

    def _preflight(self, state, stage, instruction, top=76, required_on=True):
        amber = (255, 156, 58)
        self._box((18, top, 764, 313), (29, 23, 17))
        self._box((18, top, 764, 3), amber)
        self._text(stage, 38, top + 18, self.font_title, amber)
        self._text(instruction, 38, top + 56, self.font_label, max_width=722)
        for row, (name, label) in enumerate(PREFLIGHT_SWITCHES.items()):
            index = self.sbc.button_name_to_index[name]
            enabled = state["buttons"][index]
            y = top + 94 + row * 31
            self._box((38, y, 720, 27), (39, 31, 23))
            ready = enabled == required_on
            color = (157, 218, 144) if ready else amber
            self._box((48, y + 7, 7, 13), color)
            self._text(label, 68, y + 4)
            position = "ON" if required_on else "OFF"
            self._text(position if ready else f"SET {position}", 646, y + 4, color=color)
        power = self.sbc.ship_power
        self._text(f"HATCH {'CLOSED' if power.hatch_closed else 'OPEN'}     "
                   f"IGNITION {power.ignition.upper()}     DRIVES {'ON' if power.engines else 'STANDBY'}",
                   38, top + 264, self.font_label, amber)

    def _render_boot(self, state):
        """Render the flight computer's preflight checklist."""
        instructions = {
            "Boot": ("FLIGHT COMPUTER", "Stand by while the flight computer initializes."),
            "Diagnostics": ("SELF-TEST COMPLETE", "Tap Cockpit Hatch to secure the cockpit."),
            "CockpitHatch": ("SECURE COCKPIT", "Tap Cockpit Hatch to continue."),
            "Toggles": ("PREFLIGHT CHECKS", "Set each required switch to ON."),
            "Ignition": ("ARM IGNITION", "Press Ignition to power the ship and enable the Nostromo N52."),
            "Start": ("ENGAGE DRIVES", "Press Start to bring the drives and GameVoice online."),
            "Power": ("DRIVES ONLINE", "Stand by while the controller finishes its lamp check."),
        }
        stage, instruction = instructions.get(self.boot_stage, (self.boot_stage, self.boot_message))
        self.screen.fill((15, 13, 11))
        self._text("SHIP SYSTEMS   /   STARTUP", 22, 24, self.font_title, (255, 156, 58))
        self._preflight(state, stage, instruction, top=73)
        self.pygame.display.flip()
        self.clock.tick(10)
