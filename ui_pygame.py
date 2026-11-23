import json
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

from ui_common import build_dashboard, gear_label

"""Pygame-based MFD UI backend."""


class PygameMFD:
    """Graphical dashboard UI used as an alternative to curses console UI."""

    def __init__(self, sbc, config_view, config_root, config_path, reload_callback=None):
        """Initialize pygame window, fonts, colors, and runtime UI state."""
        self.sbc = sbc
        self.config_view = config_view
        self.config_root = config_root
        self.config_path = Path(config_path)
        self.reload_callback = reload_callback
        self.tab = "main"
        self.targets = []
        self.pending_gates = None
        self.pending_n52 = None
        try:
            import pygame as _pygame
        except ImportError as exc:
            raise RuntimeError(f"pygame import failed: {exc}") from exc
        self.pygame = _pygame
        self.pygame.init()
        try:
            self.screen = self.pygame.display.set_mode((800, 480))
        except self.pygame.error:
            self.pygame.quit()
            raise
        self.pygame.display.set_caption("SBC MFD")
        self.clock = self.pygame.time.Clock()
        self.font_title = self.pygame.font.SysFont("DejaVu Sans", 22)
        self.font_label = self.pygame.font.SysFont("DejaVu Sans", 18)
        self.font_small = self.pygame.font.SysFont("DejaVu Sans", 16)
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

    def _text(self, label, x, y, font=None, color=None):
        self.screen.blit((font or self.font_small).render(str(label), True, color or self.text), (x, y))

    def _box(self, rect, color=None):
        self.pygame.draw.rect(self.screen, color or self.panel, rect)

    def _button(self, label, rect, action, selected=False):
        self._box(rect, (26, 82, 100) if selected else self.panel)
        self._text(label, rect[0] + 12, rect[1] + 13, self.font_label)
        self.targets.append((self.pygame.Rect(rect), action))

    def _open_settings(self):
        self.pending_gates = dict(self.config_view.get("aux_surface_switches", {}))
        self.pending_n52 = dict(self.config_view.get("aux_key_macros", {}).get("nostromo_n52", {}))
        self.tab = "settings"

    def _next_gate(self, surface):
        other_gates = {gate for name, gate in self.pending_gates.items() if name != surface}
        choices = [None] + [
            name for name in self.sbc.button_names
            if name.startswith("Toggle") and name not in other_gates
        ]
        current = self.pending_gates.get(surface)
        index = choices.index(current) if current in choices else -1
        self.pending_gates[surface] = choices[(index + 1) % len(choices)]

    def _next_macro(self, key):
        choices = [None] + sorted(self.config_view.get("macros", {}))
        current = self.pending_n52.get(key)
        index = choices.index(current) if current in choices else -1
        self.pending_n52[key] = choices[(index + 1) % len(choices)]

    def _save_settings(self):
        root = dict(self.config_root)
        profiles = dict(root.get("profiles", {}))
        active = root.get("active_profile", "default")
        profile = dict(profiles.get(active, {}))
        profile["aux_surface_switches"] = dict(self.pending_gates)
        bindings = dict(self.config_view.get("aux_key_macros", {}))
        bindings["nostromo_n52"] = dict(self.pending_n52)
        profile["aux_key_macros"] = bindings
        profiles[active] = profile
        root["profiles"] = profiles
        temp_path = None
        try:
            with NamedTemporaryFile(mode="w", dir=self.config_path.parent, delete=False) as handle:
                temp_path = Path(handle.name)
                json.dump(root, handle, indent=2)
                handle.write("\n")
            temp_path.replace(self.config_path)
            if self.reload_callback is not None:
                self.reload_callback()
            else:
                self.config_root = root
                self.config_view = dict(self.config_view, **profile)
            self.status_message = "Auxiliary settings saved"
        except OSError as exc:
            self.status_message = f"Save failed: {exc}"
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def _render_main(self, state):
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

    def _render_settings(self):
        self._text("AUXILIARY SWITCH ASSIGNMENTS", 22, 82, self.font_label, self.accent)
        for surface, label, y in (("game_voice", "Game Voice", 115), ("nostromo_n52", "Nostromo n52", 172)):
            self._text(label, 22, y + 15, self.font_label)
            gate = self.pending_gates.get(surface)
            self._button(gate[6:] if gate and gate.startswith("Toggle") else (gate or "Disabled"),
                         (235, y, 340, 46), lambda surface=surface: self._next_gate(surface))
        self._text("N52 KEY MAPPINGS", 22, 238, self.font_label, self.accent)
        for index, key in enumerate(("KEY_Q", "KEY_E", "KEY_R", "KEY_F", "KEY_A", "KEY_Z")):
            x = 22 + (index // 3) * 378
            y = 263 + (index % 3) * 43
            macro = self.pending_n52.get(key) or "Unassigned"
            label = f"{key[4:]}  {macro}"[:29]
            rect = (x, y, 360, 39)
            self._box(rect)
            self._text(label, x + 12, y + 10)
            self.targets.append((self.pygame.Rect(rect), lambda key=key: self._next_macro(key)))
        self._button("Save & Apply", (604, 399, 180, 45), self._save_settings, selected=True)

    def render(self, state):
        """Render the startup view or the active MFD page."""
        pygame = self.pygame
        for event in pygame.event.get():
            if self.boot_mode:
                continue
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_s:
                    self._open_settings()
                elif event.key == pygame.K_d:
                    self.tab = "main"
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.handle_touch(*event.pos)
        if self.boot_mode:
            self._render_boot()
            return
        self.targets.clear()
        self.screen.fill(self.bg)
        self._text("SBC MFD", 20, 22, self.font_title)
        self._button("Main", (490, 10, 135, 48), lambda: setattr(self, "tab", "main"), self.tab == "main")
        self._button("Settings", (638, 10, 146, 48), self._open_settings, self.tab == "settings")
        if self.tab == "settings":
            self._render_settings()
        else:
            self._render_main(state)
        status = self._footer_status()
        if status:
            self._text(status, 22, 450, color=self.dim)
        pygame.display.flip()

    def handle_touch(self, x, y):
        """Activate the visible control at the release coordinate."""
        if not self.boot_mode:
            for rect, action in self.targets:
                if rect.collidepoint(x, y):
                    action()
                    self.targets.clear()
                    break

    def _render_boot(self):
        """Render simplified boot status page."""
        spinner = ["-", "\\", "|", "/"][self._boot_spinner % 4]
        self._boot_spinner += 1
        self.screen.fill(self.bg)
        title = self.font_title.render("STEEL BATTALION CONTROLLER BIOS", True, self.text)
        self.screen.blit(title, (30, 30))
        line1 = self.font_label.render(f"[{spinner}] Stage: {self.boot_stage}", True, self.text)
        line2 = self.font_label.render(f"Status: {self.boot_message}", True, self.text)
        self.screen.blit(line1, (30, 70))
        self.screen.blit(line2, (30, 95))
        self.pygame.display.flip()
        self.clock.tick(10)
