"""Gated evdev input for the SBC auxiliary control surfaces."""

import time

from ship_power import POWER_CONTROLS


# Stable USB IDs from the Pi probe. The N52 exposes multiple evdev nodes.
SURFACE_IDS = {"game_voice": (0x045E, 0x003B), "nostromo_n52": (0x050D, 0x0815)}


class AuxInput:
    """Capture auxiliary input and publish it only while its profile gate is on."""

    def __init__(self, sbc, config, event_sink, run_macro, key_feedback=None):
        self.sbc = sbc
        self.event_sink = event_sink
        self.run_macro = run_macro
        self.key_feedback = key_feedback
        self.devices = {}
        self.next_scan = 0.0
        self.reload(config)
        try:
            import evdev
        except ImportError:
            evdev = None
        self.evdev = evdev
        if evdev is not None:
            self._scan()

    def reload(self, config):
        self.switches = config.get("aux_surface_switches", {})
        self.macros = config.get("aux_key_macros", {})

    def _scan(self):
        for path in self.evdev.list_devices():
            if path in self.devices:
                continue
            device = None
            try:
                device = self.evdev.InputDevice(path)
                identity = (device.info.vendor, device.info.product)
                surface = next((name for name, ids in SURFACE_IDS.items() if ids == identity), None)
                if surface is None:
                    device.close()
                    continue
                device.grab()
            except OSError:
                if device is not None:
                    device.close()
                continue
            self.devices[path] = (device, surface, set())

    def _publish(self, surface, kind, code, value):
        self.event_sink.publish({
            "type": "aux_input",
            "surface": surface,
            "event_type": kind,
            "code": code,
            "value": value,
            "timestamp_ms": int(time.time() * 1000),
        })

    def _key_aliases(self, code):
        name = self.evdev.ecodes.bytype[self.evdev.ecodes.EV_KEY].get(code, str(code))
        return tuple(name) if isinstance(name, (list, tuple)) else (name,)

    def key_bindings(self, surface):
        """List discovered key codes with their existing binding keys."""
        if self.evdev is None:
            return {}
        keys = {}
        bindings = self.macros.get(surface, {})
        for device, name, _ in self.devices.values():
            if name != surface:
                continue
            try:
                codes = device.capabilities().get(self.evdev.ecodes.EV_KEY, [])
            except OSError:
                continue
            for code in codes:
                aliases = self._key_aliases(code)
                key = next((item for item in (str(code), *aliases) if item in bindings), str(code))
                keys[key] = aliases[0]
        return keys

    def _key(self, surface, code, pressed):
        self._publish(surface, "key", code, int(pressed))
        aliases = self._key_aliases(code)
        bindings = self.macros.get(surface, {})
        action = next((bindings[key] for key in (str(code), *aliases, "*") if key in bindings), None)
        if self.key_feedback is not None:
            self.key_feedback(surface, code, aliases[0], pressed, action)
        if pressed and action:
            self.run_macro(action)

    def _release(self, surface, pressed):
        for code in sorted(pressed):
            self._key(surface, code, False)
        pressed.clear()

    def poll(self, now_s, active=True):
        if self.evdev is None:
            return
        if now_s >= self.next_scan:
            self._scan()
            self.next_scan = now_s + 1.0
        ecodes = self.evdev.ecodes
        for path, (device, surface, pressed) in list(self.devices.items()):
            gate = self.switches.get(surface)
            index = self.sbc.button_name_to_index.get(gate)
            enabled = active and index is not None and (
                self.sbc.ship_power.enabled(gate) if gate in POWER_CONTROLS else self.sbc.get_button_state(index)
            )
            if not enabled:
                self._release(surface, pressed)
            try:
                # Limit the work per poll even if a wheel or keypad floods the device.
                for _ in range(32):
                    event = device.read_one()
                    if event is None:
                        break
                    if not enabled:
                        continue
                    if event.type == ecodes.EV_KEY:
                        if event.value == 1 and event.code not in pressed:
                            pressed.add(event.code)
                            self._key(surface, event.code, True)
                        elif event.value == 0 and event.code in pressed:
                            pressed.remove(event.code)
                            self._key(surface, event.code, False)
                    elif event.type == ecodes.EV_REL:
                        self._publish(surface, "relative", event.code, event.value)
                        if event.code == ecodes.REL_WHEEL and event.value:
                            key = "REL_WHEEL_UP" if event.value > 0 else "REL_WHEEL_DOWN"
                            action = self.macros.get(surface, {}).get(key)
                            if action:
                                self.run_macro(action)
            except OSError:
                self._release(surface, pressed)
                device.close()
                del self.devices[path]

    def close(self):
        for device, surface, pressed in self.devices.values():
            self._release(surface, pressed)
            device.close()
        self.devices.clear()
