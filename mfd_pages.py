"""Touch settings pages for profiles, LED actions and macros."""

import json

from mfd_settings import BUTTON_PRESETS, THEMES
from ship_power import POWER_CONTROLS


class MFDSettingsPages:
    def _apply_from_panel(self, **update):
        try:
            self._apply_setting(update)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self.set_status(f"Settings error: {exc}")
            return False
        self.set_status("Settings applied")
        return True

    def _choose(self, label, choices, callback, y):
        self._text(label, 22, y - 22, color=self.accent)
        for index, (value, name) in enumerate(choices):
            self._button(name, (22 + index * 252, y, 240, 44),
                         lambda value=value: callback(value))

    def _step(self, label, current, choices, callback, y):
        index = choices.index(current) if current in choices else 0
        self._text(label, 22, y - 22, color=self.accent)
        self._button("<", (22, y, 52, 43), lambda: callback(choices[(index - 1) % len(choices)]))
        self._box((82, y, 612, 43))
        self._text(current, 94, y + 12, self.font_label)
        self._button(">", (702, y, 52, 43), lambda: callback(choices[(index + 1) % len(choices)]))

    def _render_profiles(self):
        profiles = list(self.config_root.get("profiles", {}))
        active = self.config_root.get("active_profile", "default")
        if active not in profiles:
            profiles.insert(0, active)
        profile = self.profile_choice if self.profile_choice in profiles else active
        self._step(f"Active profile: {active}", profile, profiles,
                   lambda value: setattr(self, "profile_choice", value), 105)
        self._step("Theme or starter profile", THEMES[self.theme_choice], list(THEMES.values()),
                   self._select_theme, 200)
        self._choose("Apply selection", [
            ("profile", "Load profile"), ("theme", "Set theme"), ("template", "Create starter"),
        ], lambda kind: self._apply_from_panel(kind=kind, name=profile, theme=self.theme_choice), 300)

    def _select_theme(self, label):
        self.theme_choice = next(key for key, name in THEMES.items() if name == label)

    def _select_control(self, name):
        self.control = name
        self.control_layer = self.layer
        led = self.sbc.button_to_led_name[self.sbc.button_name_to_index[name]]
        action = self.config_view.get("control_macros", {}).get(name)
        if isinstance(action, dict):
            action = action.get("action")
        elif isinstance(action, list):
            action = action[self.control_layer % len(action)] if action else ""
        self.control_action = action or ""
        self.control_mode = self.sbc.led_modes.get(led, "toggle")
        duration = self.config_view.get("button_confirm_ms", {}).get(led, 0)
        self.control_hold = str(duration or (1200 if name in POWER_CONTROLS else 0))
        self.control_preset = "Current configuration"
        _, peers = self.sbc._parse_led_mode(self.control_mode)
        self.control_peers = ",".join(peers)

    def _select_preset(self, value):
        if value == "Current configuration":
            self._select_control(self.control)
            return
        self.control_preset = value
        self.control_mode, duration = BUTTON_PRESETS[value]
        self.control_hold = str(duration)

    def _edit_control_action(self, field):
        fields = {"action": ("KEY_ action or macro name", "control_action"),
                  "hold": ("Hold duration in milliseconds", "control_hold"),
                  "peers": ("Comma-separated LED names, e.g. F2,F3", "control_peers")}
        self._edit_text(*fields[field])

    def _render_buttons(self):
        controls = [self.sbc.button_names[index] for index in self.sbc.button_to_led_name]
        if self.control not in controls:
            self._select_control(controls[0])
        self._step("Choose an SBC control", self.control, controls, self._select_control, 98)
        if self.control in POWER_CONTROLS:
            label = "Guarded Ignition: Off / On / Standby" if self.control == "Ignition" else "Guarded Drive Start: Standby / On"
            self._text(label, 22, 172, self.font_label, self.accent)
        else:
            self._step("Button preset", self.control_preset, ["Current configuration", *BUTTON_PRESETS],
                       self._select_preset, 171)
        choices = list(dict.fromkeys(["", *sorted(self.config_view.get("macros", {})), self.control_action]))
        self._step("Action (blank clears mapping)", self.control_action, choices,
                   lambda value: setattr(self, "control_action", value), 244)
        linked = self.control_mode in ("exclusive", "selective")
        self._choose(f"Peers: {self.control_peers}" if linked else f"Hold: {self.control_hold} ms", [
            ("action", "Enter KEY_ action"), ("peers", "Edit LED peers") if linked else ("hold", "Edit hold time"),
            ("save", "Save & Apply"),
        ], self._button_setting, 330)

    def _button_setting(self, field):
        if field != "save":
            self._edit_control_action(field)
        else:
            self._apply_from_panel(kind="button", name=self.control, mode=self.control_mode,
                                   action=self.control_action, hold_ms=self.control_hold,
                                   layer=self.control_layer, preset=self.control_preset, peers=self.control_peers)

    def _select_macro(self, name):
        self.macro_name = name
        macro = self.config_view.get("macros", {}).get(name, {"keys": ["KEY_A"]})
        self.macro_body = json.dumps(macro, ensure_ascii=True)

    def _render_macros(self):
        names = list(dict.fromkeys(["", *sorted(self.config_view.get("macros", {})), self.macro_name]))
        self._step("Choose a macro (blank starts a new one)", self.macro_name, names, self._select_macro, 105)
        self._choose("Edit or apply", [
            ("macro_name", "Edit name"), ("macro_body", "Edit JSON"), ("save", "Save & Apply"),
        ], self._macro_setting, 196)
        self._text(self.macro_body[:84], 22, 265)
        self._text('Example: {"keys": ["KEY_A"], "press_ms": 20, "release_ms": 20}', 22, 315, color=self.dim)
        self._text("Use a JSON step list for sequences. See the system guide for macro syntax.",
                   22, 345, color=self.dim)

    def _macro_setting(self, field):
        if field == "save":
            try:
                macro = json.loads(self.macro_body)
            except ValueError as exc:
                self.set_status(f"Invalid macro JSON: {exc}")
                return
            self._apply_from_panel(kind="macro", name=self.macro_name, macro=macro)
        else:
            self._edit_text("Macro name" if field == "macro_name" else "Macro JSON", field)

    def _edit_text(self, title, field):
        self.editor = title, field
        self.edit_text = getattr(self, field)
        self.edit_cursor = len(self.edit_text)
        self.edit_symbols = 0

    def _edit_key(self, key):
        cursor = self.edit_cursor
        if key == "Done":
            setattr(self, self.editor[1], self.edit_text)
            self.editor = None
        elif key == "Cancel":
            self.editor = None
        elif key == "Layout":
            self.edit_symbols = (self.edit_symbols + 1) % 3
        elif key in ("<", ">"):
            self.edit_cursor = max(0, min(len(self.edit_text), cursor + (-1 if key == "<" else 1)))
        elif key == "Delete":
            if cursor:
                self.edit_text = self.edit_text[:cursor - 1] + self.edit_text[cursor:]
                self.edit_cursor -= 1
        else:
            self._insert_text(key)

    def _insert_text(self, text):
        cursor = self.edit_cursor
        self.edit_text = self.edit_text[:cursor] + text + self.edit_text[cursor:]
        self.edit_cursor += len(text)

    def _render_editor(self):
        self._text(self.editor[0], 22, 80, self.font_title)
        before = self.edit_text[:self.edit_cursor][-45:]
        after = self.edit_text[self.edit_cursor:][:32]
        self._box((22, 116, 752, 43))
        self._text(before + "|" + after, 30, 129)
        alphabet = ("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", '0123456789_-"[]{}:,.+*/!=()<>')[self.edit_symbols]
        for index, char in enumerate(alphabet):
            rect = (22 + index % 10 * 75, 178 + index // 10 * 53, 69, 46)
            self._button(char, rect, lambda char=char: self._insert_text(char))
        for index, key in enumerate(("<", ">", "Delete", "Space", "Layout", "Cancel", "Done")):
            self._button(key, (22 + 108 * index, 352, 103, 48),
                         lambda key=key: self._edit_key(" " if key == "Space" else key))
