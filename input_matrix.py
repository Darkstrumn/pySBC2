import time
from collections import deque

"""
Input event queue for synthetic control/macro orchestration.

Runtime uses this queue to merge automated events with physical input handling:
- producers: vessel models, macro scripts, or any automation logic
- consumer: main loop drains events and dispatches them through macro handlers

This keeps automation behavior aligned with user-driven behavior paths.
"""


class InputMatrix:
    """Bounded in-memory queue for automation events."""

    def __init__(self, event_sink=None, max_events=256):
        self.event_sink = event_sink
        self._events = deque(maxlen=max(1, int(max_events)))

    def queue_button(self, control_name, pressed, source="automation", payload=None):
        """Queue a synthetic control edge (press/release) for macro routing."""
        if not control_name:
            return
        self._push(
            {
                "type": "button",
                "control": str(control_name),
                "pressed": bool(pressed),
                "source": str(source),
                "payload": payload or {},
            }
        )

    def queue_macro(self, macro_name, source="automation", payload=None):
        """Queue a macro execution request by name."""
        if not macro_name:
            return
        self._push(
            {
                "type": "macro",
                "macro": str(macro_name),
                "source": str(source),
                "payload": payload or {},
            }
        )

    def queue_event(self, event_name, source="automation", payload=None):
        """Queue a generic telemetry/event marker."""
        if not event_name:
            return
        self._push(
            {
                "type": "event",
                "name": str(event_name),
                "source": str(source),
                "payload": payload or {},
            }
        )

    def drain(self):
        """Return and clear all currently queued events."""
        events = list(self._events)
        self._events.clear()
        return events

    def __len__(self):
        return len(self._events)

    def _push(self, event):
        """Internal append with timestamp and optional network publication."""
        event = dict(event)
        event.setdefault("timestamp_ms", int(time.time() * 1000))
        self._events.append(event)
        if self.event_sink is not None:
            try:
                self.event_sink.publish({"type": "input_queue", "event": event})
            except Exception:
                pass
