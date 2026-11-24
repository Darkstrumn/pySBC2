"""Profile updates shared by the local MFD settings pages."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from button_states import ButtonStates
from macro_engine import MacroEngine
from ship_power import POWER_CONTROLS

THEMES = {
    "elite": "Elite Dangerous", "horizons": "Elite Horizons",
    "star_citizen": "Star Citizen", "eve": "EVE Online",
    "mechwarrior": "MechWarrior", "obs": "OBS", "kerbal": "Kerbal Space Program",
}
BUTTON_PRESETS = {
    "Momentary": ("momentary", 0),
    "Latched Toggle": ("latched", 0),
    "Momentary Flash": ("flash", 0),
    "Mutually Exclusive Group": ("exclusive", 0),
    "Selective Interlock": ("selective", 0),
    "Multi-state": ("latched", 1200),
    "Hold to Confirm": ("flash", 1200),
}


class MFDSettings:
    def _button_mode(self, led, update):
        mode = update["mode"]
        if led in POWER_CONTROLS:
            return "latched"
        if mode in ("toggle", "latched", "momentary", "flash"):
            return mode
        preset = update.get("preset")
        if preset not in ("Mutually Exclusive Group", "Selective Interlock"):
            if mode == self.sbc.led_modes.get(led):
                return mode
            raise ValueError("Invalid button preset")
        peers = tuple(dict.fromkeys(
            name.strip() for name in update.get("peers", "").split(",") if name.strip()
        ))
        minimum = 2 if preset == "Selective Interlock" else 1
        if len(peers) < minimum or any(
            peer == led or peer in POWER_CONTROLS or peer in self.config_view.get("button_states", {})
            or peer not in self.sbc.led_name_to_button_index
            for peer in peers
        ):
            raise ValueError("Enter valid, distinct LED peer names")
        modes = dict(self.config_view.get("led_modes", {}))
        for member in (led, *peers):
            current = self.sbc.led_modes.get(member, "toggle")
            # Replace links among these members, retaining unrelated groups.
            _, previous = self.sbc._parse_led_mode(current)
            linked = set(previous) - {led, *peers}
            if member == led:
                linked.update(peers)
            elif preset == "Mutually Exclusive Group":
                linked.update({led, *peers} - {member})
            modes[member] = "latched:" + ",".join(sorted(linked)) if linked else "latched"
        return modes

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
            mode = self._button_mode(led, update)
            action = update["action"]
            if action and action not in self.config_view.get("macros", {}) and not action.startswith("KEY_"):
                raise ValueError("Select a named macro or enter a KEY_ code")
            duration = int(update["hold_ms"])
            if not 0 <= duration <= 10000 or led in POWER_CONTROLS and duration == 0:
                raise ValueError("Enter 1–10000 ms for power controls, or 0–10000 ms for other controls")
            states = dict(self.config_view.get("button_states", {}))
            if update.get("preset") == "Multi-state":
                transitions = json.loads(update["states"])
                ButtonStates(transitions, duration, self.sbc.button_name_to_index)
                states[led] = transitions
                mode = "latched"
            elif update.get("preset") != "Current configuration":
                states.pop(led, None)
            profile["button_states"] = states
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
                if key == "button_confirm_ms" and isinstance(mode, dict):
                    for peer in update["peers"].split(","):
                        if peer.strip():
                            values[peer.strip()] = 0
                    values[name] = duration
                elif key == "led_modes" and isinstance(value, dict):
                    values.update(value)
                else:
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
