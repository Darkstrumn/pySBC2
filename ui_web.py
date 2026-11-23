"""Loopback HTML MFD for the controller runtime."""

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Full, Queue
from tempfile import NamedTemporaryFile

from macro_engine import MacroEngine
from ui_common import build_dashboard

THEMES = {
    "elite": "Elite Dangerous", "horizons": "Elite Horizons",
    "star_citizen": "Star Citizen", "eve": "EVE Online",
    "mechwarrior": "MechWarrior", "obs": "OBS", "kerbal": "Kerbal Space Program",
}
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/panel.css": ("panel.css", "text/css"),
    "/panel.js": ("panel.js", "text/javascript"),
}


class WebMFD:
    def __init__(self, sbc, config_view, config_root, config_path, reload_callback):
        self.sbc = sbc
        self.config_view = config_view
        self.config_root = config_root
        self.config_path = Path(config_path)
        self.reload_callback = reload_callback
        self.token = secrets.token_urlsafe(24)
        self.pending = Queue(maxsize=1)
        self.status = ""
        self.boot = None
        self.layer = 0
        self.snapshot = b"{}"
        self.settings = b"{}"
        self._publish_settings()
        panel = self
        assets = Path(__file__).resolve().parent / "mfd"

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def log_message(self, *args):
                pass

            def reply(self, status, content, media="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", media)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)

            def local_host(self):
                return self.headers.get("Host") in ("127.0.0.1:8766", "localhost:8766")

            def do_GET(self):
                if not self.local_host():
                    self.send_error(403)
                    return
                if self.path == "/state":
                    self.reply(200, panel.snapshot)
                elif self.path == "/settings":
                    self.reply(200, panel.settings)
                elif self.path in ASSETS:
                    name, media = ASSETS[self.path]
                    self.reply(200, (assets / name).read_bytes(), media)
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != "/settings":
                    self.send_error(404)
                    return
                if not self.local_host() or self.headers.get("X-MFD-Token") != panel.token:
                    self.send_error(403)
                    return
                if panel.boot is not None:
                    self.send_error(409, "Complete controller startup first")
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 65536:
                        raise ValueError("body size")
                    update = json.loads(self.rfile.read(size))
                    if not isinstance(update, dict):
                        raise ValueError("expected object")
                    panel.pending.put_nowait(update)
                except Full:
                    self.send_error(409, "A settings change is pending")
                    return
                except (ValueError, OSError):
                    self.send_error(400, "Invalid settings request")
                    return
                self.reply(202, b'{"queued":true}')

        self.server = ThreadingHTTPServer(("127.0.0.1", 8766), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print("SBC HTML MFD: http://127.0.0.1:8766/")

    def _publish_settings(self):
        profile = self.config_root.get("active_profile", "default")
        self.settings = json.dumps({
            "token": self.token,
            "profile": profile,
            "profiles": list(self.config_root.get("profiles", {})),
            "themes": THEMES,
            "theme": self.config_view.get("mfd_theme", "elite"),
            "led_modes": self.sbc.led_modes,
            "button_macros": self.config_view.get("control_macros", {}),
            "confirm_ms": self.config_view.get("button_confirm_ms", {}),
            "macros": self.config_view.get("macros", {}),
        }).encode()

    def _apply(self, update):
        profiles = dict(self.config_root.get("profiles", {}))
        active = self.config_root.get("active_profile", "default")
        profile = dict(profiles.get(active, {}))
        kind = update.get("kind")
        if kind == "profile":
            name = update["name"]
            if name not in profiles:
                raise ValueError("Unknown profile")
            active, profile = name, dict(profiles[name])
        elif kind == "template":
            theme = update["theme"]
            if theme not in THEMES:
                raise ValueError("Unknown starter profile")
            if theme in profiles:
                raise ValueError("Starter profile already exists. Load it from Active profile.")
            active = theme
            profile = dict(profiles.get("default", profile), mfd_theme=theme)
            if theme not in ("elite", "horizons"):
                # Keep hardware settings. Assign application controls during setup.
                profile.update(control_macros={}, aux_key_macros={}, analog_zones={}, gear_zones={})
        elif kind == "theme":
            theme = update["theme"]
            if theme not in THEMES:
                raise ValueError("Unknown theme")
            profile["mfd_theme"] = theme
        elif kind == "button":
            control = update["name"]
            index = self.sbc.button_name_to_index.get(control)
            led = self.sbc.button_to_led_name.get(index)
            if led is None:
                raise ValueError("Choose a control with a button LED")
            mode = update["mode"]
            if mode not in ("toggle", "latched", "momentary", "flash", self.sbc.led_modes.get(led)):
                raise ValueError("Invalid LED mode")
            action = update["action"]
            if action and action not in self.config_view.get("macros", {}) and not action.startswith("KEY_"):
                raise ValueError("Select a named macro or enter a KEY_ code")
            duration = int(update["hold_ms"])
            if not 0 <= duration <= 10000:
                raise ValueError("Hold duration must be between 0 and 10000 ms")
            previous = self.config_view.get("control_macros", {}).get(control)
            mapping = dict(previous, action=action) if isinstance(previous, dict) else action
            for key, name, value in (
                ("led_modes", led, mode), ("control_macros", control, mapping),
                ("button_confirm_ms", led, duration),
            ):
                values = dict(self.config_view.get(key, {}))
                values[name] = value
                profile[key] = values
        elif kind == "macro":
            name, macro = update["name"].strip(), update["macro"]
            if not name or len(name) > 64:
                raise ValueError("Enter a macro name of up to 64 characters")
            if isinstance(macro, dict) and (
                not isinstance(macro.get("keys"), list)
                or not all(isinstance(key, str) and key.startswith("KEY_") for key in macro["keys"])
                or any(not isinstance(macro.get(key, 20), int) or macro.get(key, 20) < 0
                       for key in ("press_ms", "release_ms"))
            ):
                raise ValueError("Invalid key list or timing")
            validator = MacroEngine.__new__(MacroEngine)
            validator.macros = {name: macro}
            errors = validator.validate_macros()
            if errors:
                raise ValueError(errors[0])
            macros = dict(self.config_view.get("macros", {}))
            macros[name] = macro
            profile["macros"] = macros
        else:
            raise ValueError("Unknown settings operation")

        profiles[active] = profile
        root = dict(self.config_root, profiles=profiles, active_profile=active)
        temp_path = None
        try:
            with NamedTemporaryFile(mode="w", dir=self.config_path.parent, delete=False) as handle:
                temp_path = Path(handle.name)
                json.dump(root, handle, indent=2)
                handle.write("\n")
            temp_path.replace(self.config_path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        self.reload_callback()
        self._publish_settings()

    def set_boot_mode(self, enabled, stage="", message=""):
        self.boot = {"stage": stage, "message": message} if enabled else None

    def update_boot(self, stage=None, message=None):
        if self.boot is not None:
            if stage is not None:
                self.boot["stage"] = stage
            if message is not None:
                self.boot["message"] = message

    def set_status(self, message):
        self.status = message

    def set_layer(self, layer):
        self.layer = layer

    def render(self, state):
        if self.boot is None:
            try:
                update = self.pending.get_nowait()
            except Empty:
                pass
            else:
                try:
                    self._apply(update)
                    self.status = "Settings applied"
                except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
                    self.status = f"Settings error: {exc}"
        buttons = []
        for index, name in enumerate(self.sbc.button_names):
            led = self.sbc.button_to_led_name.get(index)
            level = self.sbc.led_state.get(self.sbc.led_name_to_id.get(led), 0)
            confirmation = self.sbc.hold_confirmations.get(led)
            buttons.append({
                "name": name, "led": led, "level": level,
                "held": state["buttons"][index],
                "phase": confirmation.phase if confirmation else None,
            })
        self.snapshot = json.dumps({
            "boot": self.boot, "status": self.status, "layer": self.layer,
            "theme": self.config_view.get("mfd_theme", "elite"),
            "profile": self.config_root.get("active_profile", "default"),
            "gear": state["gear"], "tuner": state["tuner"],
            "diagnostics": build_dashboard(state, self.sbc), "buttons": buttons,
        }).encode()

    def teardown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
