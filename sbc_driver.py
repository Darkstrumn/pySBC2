#!/usr/bin/python3
import time
import random
import usb.core
import usb.util
from collections import deque


class SBCDriver:
    VID = 0x0A7B
    PID = 0xD000
    INTERFACE = 0
    SETTING = 0
    ENDPOINT_READER = 0
    ENDPOINT_WRITER = 1

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

    def __init__(self, ui=None):
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
        self.ui = ui
        self.usb_ok = False
        self.touch_enabled = False
        self.calibration_configured = False
        self.diag_status = {
            "usb": "PENDING",
            "led": "PENDING",
            "control": "PENDING",
            "calibration": "PENDING",
            "input": "PENDING",
        }
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
        self.led_name_alias = {name.lower(): name for name in self.led_name_to_id.keys()}
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
        self.led_name_to_button_index = {v: k for k, v in self.button_to_led_name.items()}
        self.led_modes = {}
        self.analog_config = {}
        self.analog_samples = {}
        self.logical_state = {}
        self.last_values = {}
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
        self.shutdown_hold_start = None
        self.shutdown_hold_seconds = 5.0
        self.shutdown_buttons = {
            "Eject",
            "CockpitHatch",
            "Ignition",
            "Start",
        }
        self.shutdown_toggle_switches = {
            "ToggleFilterControl",
            "ToggleOxygenSupply",
            "ToggleFuelFlowRate",
            "ToggleBufferMaterial",
            "ToggleVTLocation",
        }
        self.logical_state = {name: False for name in self.button_names}

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
        self.usb_ok = True
        self.diag_status["usb"] = "OK"

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
        raw_state = self.parse_raw_state(buf)
        state = self.apply_analog_processing(raw_state)
        self.last_values = {
            "aim_x": state["aim_x"],
            "aim_y": state["aim_y"],
            "rotation": state["rotation"],
            "sight_x": state["sight_x"],
            "sight_y": state["sight_y"],
            "left_pedal": state["left_pedal"],
            "middle_pedal": state["middle_pedal"],
            "right_pedal": state["right_pedal"],
            "tuner": state["tuner"],
            "gear": state["gear"],
        }
        return state

    def parse_raw_state(self, buf):
        gear_raw = int(buf[25])
        if gear_raw == 255:
            gear_value = -1
        elif gear_raw == 254:
            gear_value = -2
        else:
            gear_value = gear_raw
        return {
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
            "gear": gear_value,
        }

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

            deadzone_mode = str(axis_cfg.get("deadzone_mode", "center")).lower()
            center = int(axis_cfg.get("center", 0))
            deadzone = int(axis_cfg.get("deadzone", 0))
            value = state[axis_name]

            if deadzone_mode == "center":
                value -= center

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
            value = int(sum(samples) / len(samples))

            if deadzone_mode == "center":
                if abs(value) <= deadzone:
                    value = 0
            elif deadzone_mode == "low":
                if value <= deadzone:
                    value = 0

            state[axis_name] = value

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
            mode_raw = self.led_modes.get(led_name, led_mode)
            mode, latched_peers = self._parse_led_mode(mode_raw)

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

            if mode == "latched":
                if self.button_changed(button_index) and self.get_button_state(button_index):
                    new_intensity = (
                        self.MIN_LIGHT_INTENSITY
                        if self.led_state.get(led_id, 0) > 0
                        else self.MAX_LIGHT_INTENSITY
                    )
                    self.set_led(led_id, new_intensity, send=False)
                    dirty = True
                    if new_intensity == self.MAX_LIGHT_INTENSITY:
                        for peer_name in latched_peers:
                            peer_key = self.led_name_alias.get(peer_name.lower(), peer_name)
                            peer_id = self.led_name_to_id.get(peer_key)
                            if peer_id is None:
                                continue
                            if self.led_state.get(peer_id, 0) > 0:
                                self.set_led(peer_id, self.MIN_LIGHT_INTENSITY, send=False)
                                dirty = True

                for peer_name in latched_peers:
                    peer_key = self.led_name_alias.get(peer_name.lower(), peer_name)
                    peer_button = self.led_name_to_button_index.get(peer_key)
                    if peer_button is None:
                        continue
                    if self.button_changed(peer_button) and self.get_button_state(peer_button):
                        if self.led_state.get(led_id, 0) > 0:
                            self.set_led(led_id, self.MIN_LIGHT_INTENSITY, send=False)
                            dirty = True
                continue

            if mode == "momentary":
                intensity = self.MAX_LIGHT_INTENSITY if self.get_button_state(button_index) else self.MIN_LIGHT_INTENSITY
                if self.led_state.get(led_id, 0) != intensity:
                    self.set_led(led_id, intensity, send=False)
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

    def update_logical_states(self, led_mode):
        if self.raw_control_data is None:
            return

        for name in self.button_names:
            idx = self.button_name_to_index.get(name)
            if idx is None:
                continue
            physical = self.get_button_state(idx)

            led_name = self.button_to_led_name.get(idx)
            if led_name is None:
                self.logical_state[name] = physical
                continue

            mode_raw = self.led_modes.get(led_name, led_mode)
            mode, _ = self._parse_led_mode(mode_raw)
            led_id = self.led_name_to_id.get(led_name)
            led_on = self.led_state.get(led_id, 0) > 0 if led_id is not None else False

            if mode in ("toggle", "latched"):
                self.logical_state[name] = led_on
            elif mode in ("flash", "breathe", "momentary"):
                self.logical_state[name] = physical
            else:
                self.logical_state[name] = physical

    def get_logical_state(self, name):
        return bool(self.logical_state.get(name, False))

    def get_held_controls(self, pressed):
        held = []
        for name, value in self.logical_state.items():
            if value and name not in pressed:
                held.append(name)
        return held

    @staticmethod
    def _parse_led_mode(mode_raw):
        if not isinstance(mode_raw, str):
            return mode_raw, []
        parts = mode_raw.split(":", 1)
        mode = parts[0].strip().lower()
        if mode != "latched" or len(parts) == 1:
            return mode, []
        peers = [p.strip() for p in parts[1].split(",") if p.strip()]
        return mode, peers

    def demo_led_sequence(self):
        self.set_all_leds(self.MIN_LIGHT_INTENSITY, send=True)
        for led_id in range(self.LOWEST_LIGHT_VAL, self.HIGHEST_LIGHT_VAL):
            if led_id in self.LED_ID_UNUSED:
                continue
            self.set_led(led_id, self.MAX_LIGHT_INTENSITY, send=True)
            time.sleep(0.05)
        for intensity in range(self.MAX_LIGHT_INTENSITY, self.MIN_LIGHT_INTENSITY - 1, -1):
            self.set_all_leds(intensity, send=True)
            time.sleep(0.03)
        for _ in range(3):
            self.set_all_leds(self.MAX_LIGHT_INTENSITY, send=True)
            time.sleep(0.15)
            self.set_all_leds(self.MIN_LIGHT_INTENSITY, send=True)
            time.sleep(0.15)
        self.set_all_leds(self.MIN_LIGHT_INTENSITY, send=True)

    def power_down_sequence(self):
        for _ in range(3):
            self.set_all_leds(self.MAX_LIGHT_INTENSITY, send=True)
            time.sleep(0.15)
            self.set_all_leds(self.MIN_LIGHT_INTENSITY, send=True)
            time.sleep(0.15)
        for intensity in range(self.MIN_LIGHT_INTENSITY, self.MAX_LIGHT_INTENSITY + 1):
            self.set_all_leds(intensity, send=True)
            time.sleep(0.03)
        for led_id in range(self.HIGHEST_LIGHT_VAL - 1, self.LOWEST_LIGHT_VAL - 1, -1):
            if led_id in self.LED_ID_UNUSED:
                continue
            self.set_led(led_id, self.MIN_LIGHT_INTENSITY, send=True)
            time.sleep(0.05)
        self.set_all_leds(self.MIN_LIGHT_INTENSITY, send=True)

    def graceful_shutdown(self):
        self.power_down_sequence()

    def should_terminate(self):
        if self.raw_control_data is None:
            self.shutdown_hold_start = None
            return False

        all_down = all(
            self.get_button_state(self.button_name_to_index[name])
            for name in self.shutdown_buttons
        )
        toggles_off = all(
            not self.get_button_state(self.button_name_to_index[name])
            for name in self.shutdown_toggle_switches
        )

        if all_down and toggles_off:
            if self.shutdown_hold_start is None:
                self.shutdown_hold_start = time.monotonic()
            elif time.monotonic() - self.shutdown_hold_start >= self.shutdown_hold_seconds:
                return True
        else:
            self.shutdown_hold_start = None

        return False

    def _update_flash_state(self):
        now = time.monotonic()
        if now - self._last_flash_toggle >= self.FLASH_PERIOD_S:
            self._flash_on = not self._flash_on
            self._last_flash_toggle = now

    def _wait_for_button(self, button_name, led_name):
        button_index = self.button_name_to_index[button_name]
        led_id = self.led_name_to_id[led_name]
        while True:
            buf = self.read_raw()
            self.prev_control_data = self.raw_control_data
            self.raw_control_data = bytearray(buf)
            self._update_flash_state()
            if self.ui is not None:
                self.ui.update_boot(stage=button_name, message=f"Waiting for {button_name}...")
                self.ui.render(self.parse_raw_state(buf))

            intensity = self.MAX_LIGHT_INTENSITY if self._flash_on else self.MIN_LIGHT_INTENSITY
            if self.led_state.get(led_id, 0) != intensity:
                self.set_led(led_id, intensity, send=False)
                self.write_leds()

            if self.button_changed(button_index) and self.get_button_state(button_index):
                self.set_led(led_id, self.MAX_LIGHT_INTENSITY, send=True)
                return

            time.sleep(self.TIME_BETWEEN_POLLS_MS / 1000.0)

    def _wait_for_toggles_on(self):
        toggle_names = [
            "ToggleFilterControl",
            "ToggleOxygenSupply",
            "ToggleFuelFlowRate",
            "ToggleBufferMaterial",
            "ToggleVTLocation",
        ]
        toggle_indices = [self.button_name_to_index[name] for name in toggle_names]
        toggle_leds = {
            "ToggleFilterControl": "Comm1",
            "ToggleOxygenSupply": "Comm2",
            "ToggleFuelFlowRate": "Comm3",
            "ToggleBufferMaterial": "Comm4",
            "ToggleVTLocation": "Comm5",
        }
        toggle_led_ids = {k: self.led_name_to_id[v] for k, v in toggle_leds.items()}
        while True:
            buf = self.read_raw()
            self.prev_control_data = self.raw_control_data
            self.raw_control_data = bytearray(buf)
            all_on = True
            for name, idx in zip(toggle_names, toggle_indices):
                if not self.get_button_state(idx):
                    all_on = False
            self._update_flash_state()
            if self.ui is not None:
                self.ui.update_boot(stage="Toggles", message="Set all toggles ON")
                self.ui.render(self.parse_raw_state(buf))
            phase = (time.monotonic() % 2.0) / 2.0
            breathe = int(self.MIN_LIGHT_INTENSITY + (self.MAX_LIGHT_INTENSITY - self.MIN_LIGHT_INTENSITY) * (0.5 - 0.5 * (1 - 2 * abs(phase - 0.5))))
            for name in toggle_names:
                led_id = toggle_led_ids[name]
                if self.get_button_state(self.button_name_to_index[name]):
                    target = self.MAX_LIGHT_INTENSITY
                else:
                    target = breathe
                if self.led_state.get(led_id, 0) != target:
                    self.set_led(led_id, target, send=False)
            self.write_leds()
            if all_on:
                return
            time.sleep(self.TIME_BETWEEN_POLLS_MS / 1000.0)

    def startup_sequence(self):
        if self.ui is not None:
            self.ui.set_boot_mode(True, stage="Boot", message="Initializing systems")
            self.ui.render(self.parse_raw_state(self.read_raw()))
        self._run_boot_diagnostics()
        self._wait_for_button("CockpitHatch", "CockpitHatch")
        self._wait_for_toggles_on()
        self._wait_for_button("Ignition", "Ignition")
        self._wait_for_button("Start", "Start")
        if self.ui is not None:
            self.ui.update_boot(stage="Power", message="Power-up sequence")
            self.ui.render(self.parse_raw_state(self.read_raw()))
        self.demo_led_sequence()
        if self.ui is not None:
            self.ui.set_boot_mode(False)

    def _run_boot_diagnostics(self):
        self._diag_usb()
        self._diag_led_interface()
        self._diag_control_channels()
        self._diag_calibration()
        self._diag_input_matrix()
        if self.ui is not None:
            self.ui.update_boot(stage="Diagnostics", message="Diagnostics complete")
            self.ui.render(self.parse_raw_state(self.read_raw()))

    def _diag_usb(self):
        self.diag_status["usb"] = "OK" if self.usb_ok else "FAIL"

    def _diag_led_interface(self):
        try:
            comm_names = {"Comm1", "Comm2", "Comm3", "Comm4", "Comm5"}
            led_ids = [
                led_id
                for name, led_id in self.led_name_to_id.items()
                if name not in comm_names
            ]
            random.shuffle(led_ids)
            for led_id in led_ids:
                for intensity in range(self.MIN_LIGHT_INTENSITY, self.MAX_LIGHT_INTENSITY + 1):
                    self.set_led(led_id, intensity, send=False)
                    self.write_leds()
                    time.sleep(0.01)
            for led_id in led_ids:
                self.set_led(led_id, self.MIN_LIGHT_INTENSITY, send=False)
            self.write_leds()
            self.diag_status["led"] = "OK"
        except Exception:
            self.diag_status["led"] = "FAIL"

    def _diag_control_channels(self):
        try:
            comm_names = ["Comm1", "Comm2", "Comm3", "Comm4", "Comm5"]
            for name in comm_names:
                led_id = self.led_name_to_id.get(name)
                if led_id is None:
                    continue
                self.set_led(led_id, self.MAX_LIGHT_INTENSITY, send=False)
                self.write_leds()
                time.sleep(0.1)
            for name in comm_names:
                led_id = self.led_name_to_id.get(name)
                if led_id is None:
                    continue
                self.set_led(led_id, self.MIN_LIGHT_INTENSITY, send=False)
            self.write_leds()
            self.diag_status["control"] = "OK"
        except Exception:
            self.diag_status["control"] = "FAIL"

    def _diag_calibration(self):
        self.diag_status["calibration"] = "OK" if self.calibration_configured else "NOT SET"

    def _diag_input_matrix(self):
        self.diag_status["input"] = "OK" if self.touch_enabled else "NOT SET"
