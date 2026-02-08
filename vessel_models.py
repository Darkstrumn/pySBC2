import time

"""
Vessel-side semantic model layer.

This module sits between raw controls and macro orchestration:
- Runtime feeds physical edge changes into `on_control_change(...)`.
- Model classes maintain semantic vessel state (`offline`, `reactor_ready`, etc.).
- Models emit semantic events and can enqueue synthetic button/macro events.
- The input matrix drains those queued events and routes them through macro handling
  as if a user operated the controls.

How to model a new behavior profile:
1. Pick or add a model class (mech/ship/app/custom).
2. Map symbolic controls in config: `vessel_model.control_map`.
3. Implement transitions in `on_control_change` and optional periodic rules in `tick`.
4. Use `_emit(...)` for semantic events and `_queue_button/_queue_macro(...)`
   when the model should automatically trigger control/macro actions.
"""


class CoreVesselModel:
    """Base model for symbolic control mapping, state tracking, and event emission."""

    def __init__(self, effective_config, input_matrix=None, event_sink=None):
        self.effective_config = effective_config or {}
        self.model_config = dict(self.effective_config.get("vessel_model", {}))
        self.input_matrix = input_matrix
        self.event_sink = event_sink
        self.model_type = "core"
        self.control_map = dict(self.model_config.get("control_map", {}))
        self.state = {
            "power_state": "offline",
            "startup_state": "idle",
            "reactor_ready": False,
            "online": False,
        }
        self._control_state = {}

    def reload_config(self, effective_config):
        """Reload model-specific config without resetting runtime state."""
        self.effective_config = effective_config or {}
        self.model_config = dict(self.effective_config.get("vessel_model", {}))
        self.control_map = dict(self.model_config.get("control_map", {}))

    def on_control_change(self, control_name, pressed, logical_state=None):
        """
        Edge-driven control hook.

        Called by the runtime for physical control changes. Subclasses should call
        `super().on_control_change(...)` first so baseline tracking/event telemetry
        stays consistent.
        """
        if not control_name:
            return
        pressed = bool(pressed)
        previous = self._control_state.get(control_name, False)
        if previous == pressed:
            return
        self._control_state[control_name] = pressed
        self._emit(
            "vessel_control",
            {
                "control": control_name,
                "pressed": pressed,
                "logical_state": bool(logical_state) if logical_state is not None else None,
            },
        )

    def on_boot_complete(self):
        """Mark baseline online state after controller startup sequence completes."""
        self.state["online"] = True
        self.state["startup_state"] = "boot_complete"
        self._emit("vessel_boot_complete", {"state": self.snapshot()})

    def tick(self):
        """Optional periodic hook for time-based state logic. Override as needed."""
        return

    def snapshot(self):
        """Return model state for external status views/telemetry."""
        return {
            "model_type": self.model_type,
            "state": dict(self.state),
            "control_map": dict(self.control_map),
        }

    def _map_control(self, symbolic_name, fallback=None):
        """Resolve symbolic model controls to concrete control names."""
        if symbolic_name in self.control_map:
            return self.control_map[symbolic_name]
        return fallback or symbolic_name

    def _is_on(self, symbolic_name):
        """Check current tracked press/toggle state by symbolic control name."""
        control_name = self._map_control(symbolic_name)
        return bool(self._control_state.get(control_name, False))

    def _queue_button(self, symbolic_name, pressed, reason):
        """Queue a synthetic button event for macro dispatch via the input matrix."""
        if self.input_matrix is None:
            return
        control_name = self._map_control(symbolic_name)
        if control_name:
            self.input_matrix.queue_button(
                control_name,
                pressed,
                source=f"vessel:{self.model_type}",
                payload={"reason": reason},
            )

    def _queue_macro(self, macro_name, reason):
        """Queue a synthetic macro execution request."""
        if self.input_matrix is None or not macro_name:
            return
        self.input_matrix.queue_macro(
            macro_name,
            source=f"vessel:{self.model_type}",
            payload={"reason": reason},
        )

    def _emit(self, event_type, payload):
        """Publish semantic model events to network sink and input queue telemetry."""
        event = {
            "type": event_type,
            "vessel_type": self.model_type,
            "timestamp_ms": int(time.time() * 1000),
            "payload": payload,
        }
        if self.event_sink is not None:
            try:
                self.event_sink.publish(event)
            except Exception:
                pass
        if self.input_matrix is not None:
            self.input_matrix.queue_event(
                event_type,
                source=f"vessel:{self.model_type}",
                payload=payload,
            )


class MechVesselModel(CoreVesselModel):
    """Mech startup model: hatch -> subsystem toggles -> ignition -> start."""

    def __init__(self, effective_config, input_matrix=None, event_sink=None):
        super().__init__(effective_config, input_matrix=input_matrix, event_sink=event_sink)
        self.model_type = "mech"
        defaults = {
            "hatch": "CockpitHatch",
            "ignition": "Ignition",
            "start": "Start",
            "filter": "ToggleFilterControl",
            "life_support": "ToggleOxygenSupply",
            "coolant": "ToggleFuelFlowRate",
            "buffer_material": "ToggleBufferMaterial",
            "shielding": "ToggleVTLocation",
        }
        for key, value in defaults.items():
            self.control_map.setdefault(key, value)
        self.state["startup_state"] = "await_hatch"

    def on_control_change(self, control_name, pressed, logical_state=None):
        super().on_control_change(control_name, pressed, logical_state=logical_state)
        hatch_name = self._map_control("hatch")
        ignition_name = self._map_control("ignition")
        start_name = self._map_control("start")

        # Hatch close transitions from fully offline to capacitor/boot preparation.
        if control_name == hatch_name and pressed and self.state["power_state"] == "offline":
            self.state["power_state"] = "capacitor"
            self.state["startup_state"] = "await_subsystems"
            self._emit("vessel_startup_begin", {"reason": "hatch_closed"})

        # Reactor readiness is gated by all required subsystem toggles.
        if control_name in {
            self._map_control("filter"),
            self._map_control("life_support"),
            self._map_control("coolant"),
            self._map_control("buffer_material"),
            self._map_control("shielding"),
        }:
            ready = all(
                self._is_on(name)
                for name in ["filter", "life_support", "coolant", "buffer_material", "shielding"]
            )
            self.state["reactor_ready"] = ready
            if ready:
                self.state["startup_state"] = "reactor_ready"
                self._emit("vessel_reactor_ready", {"mode": "mech"})

        # Ignition can arm once reactor prerequisites are met.
        if control_name == ignition_name and pressed and self.state.get("reactor_ready"):
            self.state["startup_state"] = "ignition_armed"
            self._emit("vessel_ignition_armed", {"mode": "mech"})
            # Optional auto-start queue to drive downstream macros as if user pressed Start.
            if bool(self.model_config.get("auto_queue_start", False)):
                self._queue_button("start", True, "ignition_armed")
                self._queue_button("start", False, "ignition_armed")

        # Start commits to online/main reactor state.
        if control_name == start_name and pressed and self.state.get("reactor_ready"):
            self.state["power_state"] = "main_reactor"
            self.state["startup_state"] = "online"
            self.state["online"] = True
            self._emit("vessel_online", {"mode": "mech"})
            # Optional: queue a macro once the vessel is online.
            if bool(self.model_config.get("auto_queue_powerup_macro", False)):
                macro_name = self.effective_config.get("powerup_macro", "powerup")
                self._queue_macro(macro_name, "vessel_online")


class ShipVesselModel(CoreVesselModel):
    """Ship startup model with thematic crew-ready gate instead of cockpit hatch."""

    def __init__(self, effective_config, input_matrix=None, event_sink=None):
        super().__init__(effective_config, input_matrix=input_matrix, event_sink=event_sink)
        self.model_type = "ship"
        defaults = {
            "crew_ready": "MultiMonOpenClose",
            "ignition": "Ignition",
            "start": "Start",
            "life_support": "ToggleOxygenSupply",
            "coolant": "ToggleFuelFlowRate",
            "shielding": "ToggleVTLocation",
        }
        for key, value in defaults.items():
            self.control_map.setdefault(key, value)
        self.state["startup_state"] = "await_crew_ready"

    def on_control_change(self, control_name, pressed, logical_state=None):
        super().on_control_change(control_name, pressed, logical_state=logical_state)
        crew_ready_name = self._map_control("crew_ready")
        ignition_name = self._map_control("ignition")
        start_name = self._map_control("start")

        # Crew-ready signal starts capacitor/bootstrap phase.
        if control_name == crew_ready_name and pressed and self.state["power_state"] == "offline":
            self.state["power_state"] = "capacitor"
            self.state["startup_state"] = "await_subsystems"
            self._emit("vessel_startup_begin", {"reason": "crew_ready"})

        # Ship profile uses a smaller prerequisite set for reactor-ready.
        if control_name in {
            self._map_control("life_support"),
            self._map_control("coolant"),
            self._map_control("shielding"),
        }:
            ready = all(self._is_on(name) for name in ["life_support", "coolant", "shielding"])
            self.state["reactor_ready"] = ready
            if ready:
                self.state["startup_state"] = "reactor_ready"
                self._emit("vessel_reactor_ready", {"mode": "ship"})

        if control_name == ignition_name and pressed and self.state.get("reactor_ready"):
            self.state["startup_state"] = "ignition_armed"
            self._emit("vessel_ignition_armed", {"mode": "ship"})
            if bool(self.model_config.get("auto_queue_start", False)):
                self._queue_button("start", True, "ship_ignition_armed")
                self._queue_button("start", False, "ship_ignition_armed")

        # Final start transition into online state.
        if control_name == start_name and pressed and self.state.get("reactor_ready"):
            self.state["power_state"] = "main_reactor"
            self.state["startup_state"] = "online"
            self.state["online"] = True
            self._emit("vessel_online", {"mode": "ship"})


class AppVesselModel(CoreVesselModel):
    """Non-vehicle profile: simple activate/deactivate semantic lifecycle."""

    def __init__(self, effective_config, input_matrix=None, event_sink=None):
        super().__init__(effective_config, input_matrix=input_matrix, event_sink=event_sink)
        self.model_type = "app"
        defaults = {
            "activate": "Start",
            "deactivate": "Eject",
        }
        for key, value in defaults.items():
            self.control_map.setdefault(key, value)
        self.state["startup_state"] = "idle"

    def on_control_change(self, control_name, pressed, logical_state=None):
        super().on_control_change(control_name, pressed, logical_state=logical_state)
        # Activate/deactivate are intentionally minimal for app-centric profiles.
        if control_name == self._map_control("activate") and pressed:
            self.state["power_state"] = "active"
            self.state["startup_state"] = "online"
            self.state["online"] = True
            self._emit("vessel_online", {"mode": "app"})
        if control_name == self._map_control("deactivate") and pressed:
            self.state["power_state"] = "offline"
            self.state["startup_state"] = "idle"
            self.state["online"] = False
            self._emit("vessel_offline", {"mode": "app"})


def build_vessel_model(effective_config, input_matrix=None, event_sink=None):
    """Factory used by runtime to choose the active vessel model implementation."""
    vessel_model = (effective_config or {}).get("vessel_model", {})
    vessel_type = str(vessel_model.get("type", "mech")).strip().lower()
    if vessel_type == "ship":
        return ShipVesselModel(effective_config, input_matrix=input_matrix, event_sink=event_sink)
    if vessel_type == "app":
        return AppVesselModel(effective_config, input_matrix=input_matrix, event_sink=event_sink)
    return MechVesselModel(effective_config, input_matrix=input_matrix, event_sink=event_sink)
