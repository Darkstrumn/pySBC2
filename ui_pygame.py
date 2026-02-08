from ui_common import build_dashboard

"""Pygame-based MFD UI backend."""


class PygameMFD:
    """Graphical dashboard UI used as an alternative to curses console UI."""

    def __init__(self, sbc):
        """Initialize pygame window, fonts, colors, and runtime UI state."""
        self.sbc = sbc
        try:
            import pygame as _pygame
        except Exception as exc:
            raise RuntimeError("pygame not available") from exc
        self.pygame = _pygame
        self.pygame.init()
        self.screen = self.pygame.display.set_mode((800, 480))
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

    def set_layer(self, layer):
        """Expose active macro layer in UI."""
        self.layer = layer

    def render(self, state):
        """Render one frame from current parsed state."""
        for event in self.pygame.event.get():
            if event.type == self.pygame.QUIT:
                return
        if self.boot_mode:
            self._render_boot()
            return
        data = build_dashboard(state, self.sbc)
        self.screen.fill(self.bg)
        self.pygame.draw.rect(self.screen, self.panel, (20, 20, 520, 180), border_radius=6)
        self.pygame.draw.rect(self.screen, self.panel, (560, 20, 220, 440), border_radius=6)
        title = self.font_title.render(data["title"], True, self.text)
        self.screen.blit(title, (30, 26))
        y = 60
        for line in data["lines"]:
            surf = self.font_label.render(line, True, self.text)
            self.screen.blit(surf, (30, y))
            y += 22
        layer_label = self.font_small.render(f"Layer: {self.layer}", True, self.dim)
        self.screen.blit(layer_label, (30, 200))
        pressed_label = self.font_label.render("Pressed Buttons", True, self.accent)
        self.screen.blit(pressed_label, (570, 30))
        y = 60
        for name in data["pressed"][:20]:
            surf = self.font_small.render(name, True, self.text)
            self.screen.blit(surf, (570, y))
            y += 18
        if self.status_message:
            surf = self.font_small.render(self.status_message, True, self.dim)
            self.screen.blit(surf, (30, 440))
        self.pygame.display.flip()
        self.clock.tick(30)

    def handle_touch(self, x, y):
        """Placeholder touch tab mapping; kept for API parity with console UI."""
        if y <= 30:
            if 0 <= x <= 120:
                self.tab = "status"
            elif 130 <= x <= 260:
                self.tab = "settings"

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
