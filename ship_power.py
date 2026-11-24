"""Guarded cockpit power controls, driven by the existing button sample loop."""

from hold_confirmation import HoldConfirmation

PREFLIGHT_SWITCHES = {
    "ToggleFilterControl": "Filter control",
    "ToggleOxygenSupply": "Oxygen supply",
    "ToggleFuelFlowRate": "Fuel flow rate",
    "ToggleBufferMaterial": "Buffer material",
    "ToggleVTLocation": "VT location measurement",
}
POWER_CONTROLS = ("CockpitHatch", "Ignition", "Start")


class ShipPower:
    def __init__(self):
        self.hatch_closed = False
        self.ignition = "Off"
        self.engines = False
        self.missing = ()
        self.switches_on = ()
        self.message = ""
        self.transitions = []
        self.gestures = {name: HoldConfirmation(1200) for name in POWER_CONTROLS}

    def set_hold_times(self, times):
        for name, gesture in self.gestures.items():
            duration = times.get(name, 1200)
            gesture.hold_s = (duration if isinstance(duration, (int, float)) and duration > 0 else 1200) / 1000

    def boot_close_hatch(self):
        self.hatch_closed = True

    def boot_ignition(self):
        self.ignition = "On"

    def boot_start(self):
        self.engines = True

    def enabled(self, name):
        if name == "CockpitHatch":
            return self.hatch_closed
        return self.ignition == "On" if name == "Ignition" else self.engines

    def sample(self, now, read, rising, maintenance, flash_s, maximum):
        self.transitions.clear()
        switch_states = [(label, read(name)) for name, label in PREFLIGHT_SWITCHES.items()]
        self.missing = tuple(label for label, on in switch_states if not on)
        self.switches_on = tuple(label for label, on in switch_states if on)
        levels = {}
        for name, gesture in self.gestures.items():
            if maintenance:
                gesture.cancel()
                levels[name] = maximum if self.enabled(name) else 0
                continue
            before = gesture.phase
            pressed = read(name)
            level = gesture.update(now, pressed, rising(name), flash_s, maximum)
            if before == "holding" and gesture.phase == "aborted" and not self.enabled(name):
                if self._short_press(name):
                    gesture.cancel()
            elif gesture.confirmed:
                gesture.confirmed = False
                if self._long_press(name):
                    gesture.begin_confirmation(now)
                else:
                    gesture.abort(now)
            if gesture.phase == "idle":
                level = maximum if self.enabled(name) else 0
            elif gesture.phase == "holding" and self.enabled(name):
                level = maximum - level
            elif gesture.phase == "aborted" and self.enabled(name):
                level = maximum - level
            levels[name] = level
        return levels

    def _short_press(self, name):
        if name == "CockpitHatch":
            self.hatch_closed = True
        elif name == "Ignition":
            if not self.hatch_closed:
                self.message = "Ignition interlock: close the cockpit hatch before arming Ignition."
                return False
            if self.missing:
                self.message = "Ignition interlock: set the required switches ON, then press Ignition."
                return False
            self.ignition = "On"
        else:
            if self.ignition != "On":
                self.message = "Start interlock: turn Ignition ON before starting the drives."
                return False
            self.engines = True
        self.message = ""
        self.transitions.append(name)
        return True

    def _long_press(self, name):
        if name == "CockpitHatch":
            if not self.hatch_closed:
                return False
            if self.switches_on:
                self.message = "Hatch interlock: set all five switches OFF, then hold Cockpit Hatch."
                return False
            self.hatch_closed = False
            if self.engines:
                self.engines = False
                self.transitions.append("Start")
            if self.ignition != "Off":
                self.ignition = "Off"
                self.transitions.append("Ignition")
        elif name == "Start":
            if not self.engines:
                return False
            self.engines = False
        elif self.ignition == "On":
            self.ignition = "Standby"
            if self.engines:
                self.engines = False
                self.transitions.append("Start")
        elif self.ignition == "Standby":
            if self.missing:
                self.message = "Ignition interlock: set the required switches ON, then hold Ignition."
                return False
            self.ignition = "Off"
        else:
            return False
        self.message = ""
        self.transitions.append(name)
        return True
