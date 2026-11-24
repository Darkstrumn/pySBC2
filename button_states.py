"""Configurable state transitions for latched controller buttons."""

from hold_confirmation import HoldConfirmation

DEFAULT_TRANSITIONS = {"0": {"short": {"to": 1}}, "1": {"long": {"to": 0}}}
SHORT_PRESS_S = 0.35


class ButtonStates:
    def __init__(self, transitions, hold_ms, controls):
        if not SHORT_PRESS_S * 1000 < hold_ms <= 10000:
            raise ValueError("Multi-state hold must be 351–10000 ms")
        if not isinstance(transitions, dict) or "0" not in transitions:
            raise ValueError("Include initial state 0")
        for state, edges in transitions.items():
            if not state.isascii() or not state.isdigit() or str(int(state)) != state or not isinstance(edges, dict):
                raise ValueError("Use nonnegative integer state IDs")
            for gesture, edge in edges.items():
                if gesture == "led":
                    if edge not in ("off", "solid", "blink", "breathe"):
                        raise ValueError("LED pattern must be off, solid, blink or breathe")
                    continue
                if (gesture not in ("short", "long") or not isinstance(edge, dict)
                        or type(edge.get("to")) is not int or str(edge["to"]) not in transitions):
                    raise ValueError("Each short or long transition needs a valid target state")
                required = edge.get("requires", {})
                if not isinstance(required, dict) or any(
                    name not in controls or type(value) is not bool for name, value in required.items()
                ):
                    raise ValueError("Prerequisites must map SBC control names to true or false")
        self.transitions = transitions
        self.state = 0
        self.gesture = HoldConfirmation(hold_ms)

    def sample(self, now, pressed, rising, logical, flash_s, maximum):
        gesture = self.gesture
        if rising and gesture.phase == "aborted":
            gesture.cancel()
        was_holding = gesture.phase == "holding"
        elapsed = now - gesture.started
        level = gesture.update(now, pressed, rising, flash_s, maximum)
        trigger = None
        if gesture.confirmed:
            trigger = "long"
        elif was_holding and not pressed and elapsed <= SHORT_PRESS_S:
            trigger = "short"

        committed = False
        if trigger:
            edge = self.transitions[str(self.state)].get(trigger)
            if edge and all(logical(name) == value for name, value in edge.get("requires", {}).items()):
                self.state = edge["to"]
                committed = True
                if trigger == "long":
                    gesture.confirmed = False
                    gesture.begin_confirmation(now)
                    level = maximum
                else:
                    gesture.cancel()
            else:
                gesture.abort(now)
        if gesture.phase == "idle":
            pattern = self.transitions[str(self.state)].get("led", "solid" if self.state else "off")
            level = {
                "off": 0, "solid": maximum,
                "blink": maximum if int(now / 0.5) % 2 == 0 else 0,
                "breathe": round(maximum * (1 - abs(2 * (now % 2.4) / 2.4 - 1))),
            }[pattern]
        elif self.state and gesture.phase in ("holding", "aborted"):
            level = maximum - level
        return level, committed
