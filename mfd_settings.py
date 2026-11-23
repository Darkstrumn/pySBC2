"""Profile updates shared by the local MFD settings pages."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from macro_engine import MacroEngine

THEMES = {
    "elite": "Elite Dangerous", "horizons": "Elite Horizons",
    "star_citizen": "Star Citizen", "eve": "EVE Online",
    "mechwarrior": "MechWarrior", "obs": "OBS", "kerbal": "Kerbal Space Program",
}
LED_MODES = ("toggle", "latched", "momentary", "flash")


class MFDSettings:
    def _apply_setting(self, update):
        profiles = dict(self.config_root.get("profiles", {}))
        active = self.config_root.get("active_profile", "default")
        profile = dict(profiles.get(active, {}))
        kind = update.get("kind")
        if kind == "profile":
            name = update["name"]
            if name not in profiles and name != "default":
                raise ValueError("Unknown profile")
            active, profile = name, dict(profiles.get(name, {}))
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
                profile.update(control_macros={}, aux_key_macros={}, analog_zones={}, gear_zones=[])
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
            if mode not in LED_MODES and mode != self.sbc.led_modes.get(led):
                raise ValueError("Invalid LED mode")
            action = update["action"]
            if action and action not in self.config_view.get("macros", {}) and not action.startswith("KEY_"):
                raise ValueError("Select a named macro or enter a KEY_ code")
            duration = int(update["hold_ms"])
            if not 0 <= duration <= 10000:
                raise ValueError("Hold duration must be between 0 and 10000 ms")
            previous = self.config_view.get("control_macros", {}).get(control)
            if isinstance(previous, dict):
                mapping = dict(previous, action=action)
            elif isinstance(previous, list) and previous:
                mapping = list(previous)
                mapping[update["layer"] % len(mapping)] = action
            else:
                mapping = action
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
        elif kind == "auxiliary":
            profile.update(update["settings"])
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
        if self.reload_callback is not None:
            self.reload_callback()
        else:
            self.config_root = root
            self.config_view = dict(root, **profile)
