#!/usr/bin/python3
import sys
import time
import usb.core
import usb.util
import json
from pathlib import Path
import shutil
from collections import deque


class SBCDriver:
    # USB identifiers
    VID = 0x0A7B
    PID = 0xD000
    INTERFACE = 0
    SETTING = 0
    ENDPOINT_READER = 0
    ENDPOINT_WRITER = 1

    # LED packing per SBC/src/SBCController.cpp
    LED_ID_MIN = 4
    LED_ID_MAX = 41
    LED_ID_UNUSED = {34}
    GEAR_LED_MIN = 35
    GEAR_LED_MAX = 41
    GEAR_LED_NEUTRAL = 36
    GEAR_LED_FIRST = 37
    RAW_LED_DATA_LENGTH = 22
    INTENSITY_MIN = 0x00
    INTENSITY_MAX = 0x0F
    LOWEST_LIGHT_VAL = 4
    HIGHEST_LIGHT_VAL = 41
    MAX_LIGHT_INTENSITY = 15
    MIN_LIGHT_INTENSITY = 0
    TIME_BETWEEN_POLLS_MS = 4
    FLASH_PERIOD_S = 0.3
    GEAR_REVERSE_FLASH = True

    def __init__(self):
        self.dev = None
        self.ep_in = None
        self.ep_out = None
        self.raw_led_data = bytearray(self.RAW_LED_DATA_LENGTH)
        self.raw_control_data = None
        self.prev_control_data = None
        self.update_gear_lights = True
        self.gear_light_intensity = 8
        self.led_state = {i: 0 for i in range(self.LED_ID_MIN, self.LED_ID_MAX + 1)}
        self._last_flash_toggle = time.monotonic()
        self._flash_on = False
        self.led_name_to_id = {
            "Eject": 4,
            "CockpitHatch": 5,
            "Ignition": 6,
            "Start": 7,
            "OpenClose": 8,
            "MapZoomInOut": 9,
            "ModeSelect": 10,
            "SubMonitorModeSelect": 11,
            "MainMonitorZoomIn": 12,
            "MainMonitorZoomOut": 13,
            "ForecastShootingSystem": 14,
            "Manipulator": 15,
            "LineColorChange": 16,
            "Washing": 17,
            "Extinguisher": 18,
            "Chaff": 19,
            "TankDetach": 20,
            "Override": 21,
            "NightScope": 22,
            "F1": 23,
            "F2": 24,
            "F3": 25,
            "MainWeaponControl": 26,
            "SubWeaponControl": 27,
            "MagazineChange": 28,
            "Comm1": 29,
            "Comm2": 30,
            "Comm3": 31,
            "Comm4": 32,
            "Comm5": 33,
            "GearR": 35,
            "GearN": 36,
            "Gear1": 37,
            "Gear2": 38,
            "Gear3": 39,
            "Gear4": 40,
            "Gear5": 41,
        }
        self.button_to_led_name = {
            3: "Eject",
            4: "CockpitHatch",
            5: "Ignition",
            6: "Start",
            7: "OpenClose",
            8: "MapZoomInOut",
            9: "ModeSelect",
            10: "SubMonitorModeSelect",
            11: "MainMonitorZoomIn",
            12: "MainMonitorZoomOut",
            13: "ForecastShootingSystem",
            14: "Manipulator",
            15: "LineColorChange",
            16: "Washing",
            17: "Extinguisher",
            18: "Chaff",
            19: "TankDetach",
            20: "Override",
            21: "NightScope",
            22: "F1",
            23: "F2",
            24: "F3",
            25: "MainWeaponControl",
            26: "SubWeaponControl",
            27: "MagazineChange",
            28: "Comm1",
            29: "Comm2",
            30: "Comm3",
            31: "Comm4",
            32: "Comm5",
        }
        self.led_modes = {}
        self.analog_config = {}
        self.analog_samples = {}
        self.button_names = [
            "RightJoyMainWeapon",
            "RightJoyFire",
            "RightJoyLockOn",
            "Eject",
            "CockpitHatch",
            "Ignition",
            "Start",
            "MultiMonOpenClose",
            "MultiMonMapZoomInOut",
            "MultiMonModeSelect",
            "MultiMonSubMonitor",
            "MainMonZoomIn",
            "MainMonZoomOut",
            "FunctionFSS",
            "FunctionManipulator",
            "FunctionLineColorChange",
            "Washing",
            "Extinguisher",
            "Chaff",
            "FunctionTankDetach",
            "FunctionOverride",
            "FunctionNightScope",
            "FunctionF1",
            "FunctionF2",
            "FunctionF3",
            "WeaponCtrlMain",
            "WeaponCtrlSub",
            "WeaponCtrlMagazineChange",
            "Comm1",
            "Comm2",
            "Comm3",
            "Comm4",
            "Comm5",
            "LeftJoySightChange",
            "ToggleFilterControl",
            "ToggleOxygenSupply",
            "ToggleFuelFlowRate",
            "ToggleBufferMaterial",
            "ToggleVTLocation",
        ]
        self.button_name_to_index = {name: idx for idx, name in enumerate(self.button_names)}

    def open(self):
        self.dev = usb.core.find(idVendor=self.VID, idProduct=self.PID)
        if self.dev is None:
            raise RuntimeError("Steel Battalion Controller not found.")

        if self.dev.is_kernel_driver_active(self.INTERFACE):
            self.dev.detach_kernel_driver(self.INTERFACE)
            usb.util.claim_interface(self.dev, self.INTERFACE)

        self.dev.set_configuration()
        cfg = self.dev.get_active_configuration()
        self.ep_in = cfg[(self.INTERFACE, self.SETTING)][self.ENDPOINT_READER]
        self.ep_out = cfg[(self.INTERFACE, self.SETTING)][self.ENDPOINT_WRITER]

    def read_raw(self):
        return self.dev.read(
            self.ep_in.bEndpointAddress,
            self.ep_in.wMaxPacketSize,
            timeout=1000,
        )

    @staticmethod
    def _axis_value(buf, first_index, second_index):
        temp = int(buf[first_index]) << 2
        temp2 = int(buf[second_index]) >> 6
        return (temp | temp2) & 0x3FF

    @staticmethod
    def _signed_axis_value(buf, first_index, second_index):
        temp = int(buf[first_index]) << 2
        temp2 = int(buf[second_index]) >> 6
        temp = (temp | temp2) & 0x3FF
        if buf[first_index] >= 128:
            temp |= 0xFC00
        return temp - 0x10000 if temp & 0x8000 else temp

    @staticmethod
    def _button_state(buf, button_index):
        if button_index >= 39:
            return False
        byte_pos = 2 + (button_index // 8)
        mask = 1 << (button_index % 8)
        return (buf[byte_pos] & mask) != 0

    def parse_state(self, buf):
        self.prev_control_data = self.raw_control_data
        self.raw_control_data = bytearray(buf)
        raw_state = {
            "buttons": [self._button_state(buf, i) for i in range(39)],
            "aim_x": self._axis_value(buf, 9, 10),
            "aim_y": self._axis_value(buf, 11, 12),
            "rotation": self._signed_axis_value(buf, 13, 14),
            "sight_x": self._signed_axis_value(buf, 15, 16),
            "sight_y": self._signed_axis_value(buf, 17, 18),
            "left_pedal": self._axis_value(buf, 19, 20),
            "middle_pedal": self._axis_value(buf, 21, 22),
            "right_pedal": self._axis_value(buf, 23, 24),
            "tuner": int(buf[24]) & 0x0F,
            "gear": int(buf[25]),
        }
        return self.apply_analog_processing(raw_state)

    def set_analog_config(self, config):
        self.analog_config = config
        for name, axis_cfg in config.items():
            samples = int(axis_cfg.get("smoothing_samples", 1))
            if samples < 1:
                samples = 1
            self.analog_samples[name] = deque(maxlen=samples)

    def apply_analog_processing(self, state):
        if not self.analog_config:
            return state

        for axis_name, axis_cfg in self.analog_config.items():
            if axis_name not in state:
                continue

            trim = int(axis_cfg.get("trim", 0))
            value = state[axis_name] - trim

            minimum = axis_cfg.get("min")
            maximum = axis_cfg.get("max")
            if minimum is not None and value < minimum:
                value = minimum
            if maximum is not None and value > maximum:
                value = maximum

            samples = self.analog_samples.get(axis_name)
            if samples is None:
                samples = deque(maxlen=max(int(axis_cfg.get("smoothing_samples", 1)), 1))
                self.analog_samples[axis_name] = samples
            samples.append(value)
            state[axis_name] = int(sum(samples) / len(samples))

        return state

    def _clamp_intensity(self, value):
        if value < self.INTENSITY_MIN:
            return self.INTENSITY_MIN
        if value > self.INTENSITY_MAX:
            return self.INTENSITY_MAX
        return value

    def set_led(self, led_id, intensity, send=True):
        if led_id in self.LED_ID_UNUSED or led_id < self.LED_ID_MIN or led_id > self.LED_ID_MAX:
            return

        capped = self._clamp_intensity(intensity)
        hex_pos = led_id % 2
        byte_pos = (led_id - hex_pos) // 2

        self.raw_led_data[byte_pos] &= 0x0F if hex_pos == 1 else 0xF0
        self.raw_led_data[byte_pos] += capped * (0x10 if hex_pos == 1 else 0x01)
        self.led_state[led_id] = capped

        if send:
            self.write_leds()

    def set_all_leds(self, intensity, send=True):
        for led_id in range(self.LED_ID_MIN, self.LED_ID_MAX + 1):
            if led_id in self.LED_ID_UNUSED:
                continue
            self.set_led(led_id, intensity, send=False)
        if send:
            self.write_leds()

    def write_leds(self):
        self.ep_out.write(self.raw_led_data)

    def update_gear_leds(self, gear_value, intensity=8):
        dirty = False
        for led_id in range(self.GEAR_LED_MIN, self.GEAR_LED_MAX + 1):
            if self.led_state.get(led_id, 0) != 0:
                self.set_led(led_id, 0, send=False)
                dirty = True

        if gear_value is None:
            if dirty:
                self.write_leds()
            return

        if gear_value < 0:
            target = self.GEAR_LED_FIRST + gear_value
        else:
            target = self.GEAR_LED_NEUTRAL + gear_value

        if target < self.GEAR_LED_MIN or target > self.GEAR_LED_MAX:
            if dirty:
                self.write_leds()
            return

        self.set_led(target, intensity, send=False)
        dirty = True
        if dirty:
            self.write_leds()

    def set_gear_lights(self, update, intensity):
        self.update_gear_lights = bool(update)
        self.gear_light_intensity = self._clamp_intensity(intensity)

    def set_led_modes(self, modes):
        self.led_modes = modes

    def get_button_state(self, button_index):
        if self.raw_control_data is None:
            return False
        return self._button_state(self.raw_control_data, button_index)

    def button_changed(self, button_index):
        if self.raw_control_data is None or self.prev_control_data is None:
            return False
        current = self._button_state(self.raw_control_data, button_index)
        previous = self._button_state(self.prev_control_data, button_index)
        return current != previous

    def handle_button_leds(self, led_mode):
        if self.raw_control_data is None:
            return

        dirty = False
        now = time.monotonic()
        if now - self._last_flash_toggle >= self.FLASH_PERIOD_S:
            self._flash_on = not self._flash_on
            self._last_flash_toggle = now

        for button_index, led_name in self.button_to_led_name.items():
            led_id = self.led_name_to_id[led_name]
            mode = self.led_modes.get(led_name, led_mode)

            if mode == "toggle":
                if self.button_changed(button_index) and self.get_button_state(button_index):
                    new_intensity = (
                        self.MIN_LIGHT_INTENSITY
                        if self.led_state.get(led_id, 0) > 0
                        else self.MAX_LIGHT_INTENSITY
                    )
                    self.set_led(led_id, new_intensity, send=False)
                    dirty = True
                continue

            if mode == "flash":
                if self.get_button_state(button_index):
                    intensity = self.MAX_LIGHT_INTENSITY if self._flash_on else self.MIN_LIGHT_INTENSITY
                else:
                    intensity = self.MIN_LIGHT_INTENSITY
                if self.led_state.get(led_id, 0) != intensity:
                    self.set_led(led_id, intensity, send=False)
                    dirty = True

        if dirty:
            self.write_leds()

    def demo_led_sequence(self):
        self.set_all_leds(self.MIN_LIGHT_INTENSITY, send=True)
        for led_id in range(self.LOWEST_LIGHT_VAL, self.HIGHEST_LIGHT_VAL):
            if led_id in self.LED_ID_UNUSED:
                continue
            self.set_led(led_id, self.MAX_LIGHT_INTENSITY, send=True)
            time.sleep(0.05)
        self.set_all_leds(self.MIN_LIGHT_INTENSITY, send=True)


def load_config(path):
    defaults = {
        "led_mode": "toggle",
        "led_modes": {},
        "flash_period_s": 0.3,
        "poll_interval_ms": 4,
        "update_gear_lights": True,
        "gear_light_intensity": 8,
        "gear_reverse_flash": True,
        "active_profile": "default",
        "profiles": {},
    }
    cfg_path = Path(path)
    if not cfg_path.exists():
        return defaults
    try:
        data = json.loads(cfg_path.read_text())
    except (OSError, json.JSONDecodeError):
        return defaults
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    return data


def build_default_led_modes(led_name_to_id):
    defaults = {}
    flash_names = {"Eject", "CockpitHatch", "Ignition", "Start"}
    for name in led_name_to_id.keys():
        defaults[name] = "flash" if name in flash_names else "toggle"
    return defaults


def gear_label(value):
    if value == -2:
        return "R"
    if value == -1:
        return "N"
    if value in (1, 2, 3, 4, 5):
        return str(value)
    return str(value)


def format_state(state, sbc, width):
    pressed = [name for i, name in enumerate(sbc.button_names) if state["buttons"][i]]
    header = "STEEL BATTALION CONTROLLER DIAGNOSTICS"
    title = header[:width].ljust(width)
    separator = "-" * min(width, len(title))

    axis_lines = [
        f"Aim: X {state['aim_x']:>4}  Y {state['aim_y']:>4}",
        f"Sight: X {state['sight_x']:>4}  Y {state['sight_y']:>4}",
        f"Rotation: {state['rotation']:>5}",
        f"Pedals: L {state['left_pedal']:>4}  M {state['middle_pedal']:>4}  R {state['right_pedal']:>4}",
        f"Tuner: {state['tuner']:>2}  Gear: {gear_label(state['gear'])}",
    ]

    col_width = max(12, (width - 2) // 3)
    columns = [[], [], []]
    for idx, name in enumerate(pressed):
        columns[idx % 3].append(name)

    max_rows = max(len(col) for col in columns) if pressed else 0
    button_lines = []
    for row in range(max_rows):
        cells = []
        for col in columns:
            text = col[row] if row < len(col) else ""
            cells.append(text.ljust(col_width))
        button_lines.append(" ".join(cells).rstrip())

    lines = [title, separator]
    lines.extend(axis_lines)
    lines.append("")
    lines.append("Pressed Buttons:")
    if button_lines:
        lines.extend(button_lines)
    else:
        lines.append("(none)")
    return "\n".join(lines)


def render_state(state, sbc):
    width = shutil.get_terminal_size((80, 24)).columns
    text = format_state(state, sbc, width)
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.write(text)
    sys.stdout.flush()


class MacroEngine:
    def __init__(self, config, sbc):
        self.sbc = sbc
        self.control_macros = config.get("control_macros", {})
        self.macros = config.get("macros", {})
        self.analog_zones = config.get("analog_zones", {})
        self.gear_zones = config.get("gear_zones", [])
        self.output_mode = str(config.get("macro_output", "log")).lower()
        self.active_keys = set()
        self.axis_active = {}
        self.gear_active = None
        self.ui = None
        self.ecodes = None

        if self.output_mode in ("auto", "uinput"):
            try:
                from evdev import UInput, ecodes
            except Exception:
                if self.output_mode == "uinput":
                    raise
            else:
                self.ecodes = ecodes
                all_keys = self._collect_keys()
                if all_keys:
                    self.ui = UInput({ecodes.EV_KEY: all_keys}, name="sbc-macro")
                self.output_mode = "uinput"

        if self.ui is None:
            self.output_mode = "log"

    def _collect_keys(self):
        keys = set()
        for macro in self.macros.values():
            for key in macro.get("keys", []):
                code = getattr(self.ecodes, key, None)
                if code is not None:
                    keys.add(code)
        return list(keys)

    def _emit(self, key_name, pressed):
        if self.output_mode == "uinput" and self.ui and self.ecodes:
            code = getattr(self.ecodes, key_name, None)
            if code is None:
                return
            self.ui.write(self.ecodes.EV_KEY, code, 1 if pressed else 0)
            self.ui.syn()
            return
        state = "DOWN" if pressed else "UP"
        print(f"MACRO {state}: {key_name}")

    def _press_keys(self, keys):
        for key in keys:
            if key not in self.active_keys:
                self._emit(key, True)
                self.active_keys.add(key)

    def _release_keys(self, keys):
        for key in keys:
            if key in self.active_keys:
                self._emit(key, False)
                self.active_keys.remove(key)

    def _resolve_macro(self, action_name):
        if action_name in self.macros:
            return self.macros[action_name]
        if action_name.startswith("KEY_"):
            return {"keys": [action_name], "press_ms": 20, "release_ms": 20}
        return None

    def _run_tap(self, macro, press_ms=None, release_ms=None):
        keys = macro.get("keys", [])
        if not keys:
            return
        press_delay = int(press_ms if press_ms is not None else macro.get("press_ms", 20))
        release_delay = int(release_ms if release_ms is not None else macro.get("release_ms", 20))
        self._press_keys(keys)
        time.sleep(press_delay / 1000.0)
        self._release_keys(keys)
        time.sleep(release_delay / 1000.0)

    def _run_hold_press(self, macro):
        keys = macro.get("keys", [])
        if keys:
            self._press_keys(keys)

    def _run_hold_release(self, macro):
        keys = macro.get("keys", [])
        if keys:
            self._release_keys(keys)

    def _behavior_from_led(self, led_name, default_led_mode):
        led_mode = self.sbc.led_modes.get(led_name, default_led_mode)
        return "hold" if led_mode == "flash" else "tap"

    def handle_buttons(self, state, default_led_mode):
        for control_name, mapping in self.control_macros.items():
            if isinstance(mapping, str):
                action_name = mapping
                behavior = "from_led"
                press_ms = None
                release_ms = None
            elif isinstance(mapping, dict):
                action_name = mapping.get("action")
                behavior = mapping.get("behavior", "from_led")
                press_ms = mapping.get("press_ms")
                release_ms = mapping.get("release_ms")
            else:
                continue

            if not action_name:
                continue

            index = self.sbc.button_name_to_index.get(control_name)
            if index is None:
                continue

            pressed = self.sbc.get_button_state(index)
            changed = self.sbc.button_changed(index)

            led_name = self.sbc.button_to_led_name.get(index, control_name)
            if behavior == "from_led":
                behavior = self._behavior_from_led(led_name, default_led_mode)

            macro = self._resolve_macro(action_name)
            if macro is None:
                continue

            if behavior == "tap":
                if changed and pressed:
                    self._run_tap(macro, press_ms, release_ms)
            elif behavior == "hold":
                if changed and pressed:
                    self._run_hold_press(macro)
                elif changed and not pressed:
                    self._run_hold_release(macro)

    def handle_analogs(self, state):
        for axis_name, zones in self.analog_zones.items():
            value = state.get(axis_name)
            if value is None:
                continue

            current_action = None
            current_behavior = "hold"
            for zone in zones:
                min_val = zone.get("min")
                max_val = zone.get("max")
                if min_val is None or max_val is None:
                    continue
                if min_val <= value <= max_val:
                    current_action = zone.get("action")
                    current_behavior = zone.get("behavior", "hold")
                    break

            prev_action, prev_behavior = self.axis_active.get(axis_name, (None, "hold"))
            if current_action == prev_action:
                continue

            if prev_action:
                prev_macro = self._resolve_macro(prev_action)
                if prev_macro and prev_behavior == "hold":
                    self._run_hold_release(prev_macro)

            if current_action:
                macro = self._resolve_macro(current_action)
                if macro:
                    if current_behavior == "tap":
                        self._run_tap(macro)
                    else:
                        self._run_hold_press(macro)

            self.axis_active[axis_name] = (current_action, current_behavior)

    def handle_gears(self, state):
        gear_value = state.get("gear")
        if gear_value is None:
            return

        current_action = None
        current_behavior = "hold"
        for zone in self.gear_zones:
            values = zone.get("values")
            value = zone.get("value")
            if values is not None:
                if gear_value in values:
                    current_action = zone.get("action")
                    current_behavior = zone.get("behavior", "hold")
                    break
            elif value is not None:
                if gear_value == value:
                    current_action = zone.get("action")
                    current_behavior = zone.get("behavior", "hold")
                    break

        prev_action, prev_behavior = self.gear_active or (None, "hold")
        if current_action == prev_action:
            return

        if prev_action:
            prev_macro = self._resolve_macro(prev_action)
            if prev_macro and prev_behavior == "hold":
                self._run_hold_release(prev_macro)

        if current_action:
            macro = self._resolve_macro(current_action)
            if macro:
                if current_behavior == "tap":
                    self._run_tap(macro)
                else:
                    self._run_hold_press(macro)

        self.gear_active = (current_action, current_behavior)

def main():
    mode = "read"
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()

    sbc = SBCDriver()
    config = load_config("sbc_config.json")
    active_profile = str(config.get("active_profile", "default"))
    profile_data = {}
    if isinstance(config.get("profiles"), dict):
        profile_data = config["profiles"].get(active_profile, {})

    effective = dict(config)
    if isinstance(profile_data, dict):
        effective.update(profile_data)

    sbc.FLASH_PERIOD_S = float(effective["flash_period_s"])
    sbc.TIME_BETWEEN_POLLS_MS = int(effective["poll_interval_ms"])
    sbc.set_gear_lights(effective["update_gear_lights"], effective["gear_light_intensity"])
    sbc.GEAR_REVERSE_FLASH = bool(effective["gear_reverse_flash"])
    if isinstance(effective.get("analog"), dict):
        sbc.set_analog_config(effective["analog"])
    led_mode = str(effective["led_mode"]).lower()
    led_modes = build_default_led_modes(sbc.led_name_to_id)
    if isinstance(effective.get("led_modes"), dict):
        for key, value in effective["led_modes"].items():
            key_norm = str(key).strip().lower()
            for name in sbc.led_name_to_id.keys():
                if name.lower() == key_norm:
                    led_modes[name] = str(value).strip().lower()
                    break
    sbc.set_led_modes(led_modes)
    sbc.open()
    macro_engine = MacroEngine(effective, sbc)

    if mode == "led":
        sbc.demo_led_sequence()
        return

    if mode == "read":
        sbc.demo_led_sequence()
        while True:
            buf = sbc.read_raw()
            state = sbc.parse_state(buf)
            sbc.handle_button_leds(led_mode)
            macro_engine.handle_buttons(state, led_mode)
            macro_engine.handle_analogs(state)
            macro_engine.handle_gears(state)
            if sbc.update_gear_lights:
                gear_value = state["gear"]
                if sbc.GEAR_REVERSE_FLASH and gear_value == -2:
                    intensity = sbc.MAX_LIGHT_INTENSITY if sbc._flash_on else sbc.MIN_LIGHT_INTENSITY
                    sbc.update_gear_leds(gear_value, intensity)
                else:
                    sbc.update_gear_leds(gear_value, sbc.gear_light_intensity)
            render_state(state, sbc)
            time.sleep(sbc.TIME_BETWEEN_POLLS_MS / 1000.0)


if __name__ == "__main__":
    main()
