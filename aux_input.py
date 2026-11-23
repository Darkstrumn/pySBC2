"""Gated evdev input for the SBC auxiliary control surfaces."""

import time


# Stable USB IDs from the Pi probe. The N52 exposes multiple evdev nodes.
SURFACE_IDS = {"game_voice": (0x045E, 0x003B), "nostromo_n52": (0x050D, 0x0815)}


class AuxInput:
    """Capture auxiliary input and publish it only while its profile gate is on."""

    def __init__(self, sbc, config, event_sink, run_macro):
        self.sbc = sbc
        self.event_sink = event_sink
        self.run_macro = run_macro
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

    def _release(self, surface, pressed):
        for code in sorted(pressed):
            self._publish(surface, "key", code, 0)
        pressed.clear()

    def poll(self, now_s, active=True):
        if self.evdev is None:
            return
        if now_s >= self.next_scan:
            self._scan()
            self.next_scan = now_s + 1.0
        ecodes = self.evdev.ecodes
        for path, (device, surface, pressed) in list(self.devices.items()):
            index = self.sbc.button_name_to_index.get(self.switches.get(surface))
            enabled = active and index is not None and self.sbc.get_button_state(index)
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
                            self._publish(surface, "key", event.code, 1)
                            bindings = self.macros.get(surface, {})
                            names = ecodes.bytype[ecodes.EV_KEY]
                            name = names.get(event.code)
                            action = bindings.get(str(event.code))
                            for alias in name if isinstance(name, list) else (name,):
                                action = action or bindings.get(alias)
                            if action:
                                self.run_macro(action)
                        elif event.value == 0 and event.code in pressed:
                            pressed.remove(event.code)
                            self._publish(surface, "key", event.code, 0)
                    elif event.type == ecodes.EV_REL:
                        self._publish(surface, "relative", event.code, event.value)
            except OSError:
                self._release(surface, pressed)
                device.close()
                del self.devices[path]

    def close(self):
        for device, surface, pressed in self.devices.values():
            self._release(surface, pressed)
            device.close()
        self.devices.clear()
