import json
import threading
import time
from collections import deque
from pathlib import Path

from gear_effects import GearEffectController

"""
Microservice-like polling runtime for SBC v1.0.

This module decomposes the old monolithic read loop into explicit services:
- ReaderService: polls hardware and updates parsed state
- WriterService: owns LED/output updates and LED animation commands
- ModelService: feeds vessel semantic model from physical edge changes
- MacroDispatchService: runs button/analog/gear macro dispatch + queued events
- TelemetryService: publishes sampled raw-state snapshots
- UIService: renders UI and touch interactions
- ShutdownService: watches gesture-based shutdown conditions
"""


class EventSinkFanout:
    """Fan out publish(payload) calls to multiple event sinks."""

    def __init__(self, sinks=None):
        self._sinks = list(sinks or [])

    def add(self, sink):
        if sink is None:
            return
        self._sinks.append(sink)

    def publish(self, payload):
        for sink in list(self._sinks):
            try:
                sink.publish(payload)
            except Exception:
                pass


class RuntimeAuditSink:
    """Append-only NDJSON runtime audit log for replay/troubleshooting."""

    def __init__(self, path, enabled=True, max_bytes=0, include_raw_state=False):
        self.enabled = bool(enabled)
        self.path = Path(path)
        self.max_bytes = max(0, int(max_bytes))
        self.include_raw_state = bool(include_raw_state)
        self._lock = threading.Lock()

    def publish(self, payload):
        payload = dict(payload or {})
        if not self.include_raw_state and payload.get("type") == "raw_state":
            return
        self.log("event", payload)

    def log(self, event_type, payload, service=None):
        if not self.enabled:
            return
        record = {
            "timestamp_ms": int(time.time() * 1000),
            "event_type": str(event_type),
            "service": str(service) if service else None,
            "payload": payload,
        }
        line = json.dumps(record, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.max_bytes > 0 and self.path.exists():
                    current_size = self.path.stat().st_size
                    line_size = len(line.encode("utf-8"))
                    if current_size + line_size > self.max_bytes:
                        keep_bytes = max(0, self.max_bytes - line_size)
                        previous = self.path.read_bytes()[-keep_bytes:] if keep_bytes else b""
                        self.path.write_bytes(previous + line.encode("utf-8"))
                        return
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            except OSError:
                pass


class LocalEventBus:
    """In-process topic bus for service-to-service messaging."""

    def __init__(self):
        self._handlers = {}
        self._lock = threading.Lock()

    def subscribe(self, topic, handler):
        if not topic or handler is None:
            return
        with self._lock:
            self._handlers.setdefault(str(topic), []).append(handler)

    def publish(self, topic, payload):
        with self._lock:
            handlers = list(self._handlers.get(str(topic), []))
        for handler in handlers:
            try:
                handler(payload)
            except Exception:
                pass


class PollingService:
    """Base class for simple fixed-interval polling services."""

    def __init__(self, name, interval_ms):
        self.name = str(name)
        self.interval_s = max(0.0, float(interval_ms) / 1000.0)
        self.next_run_s = 0.0

    def due(self, now_s):
        return now_s >= self.next_run_s

    def run(self, now_s):
        if self.interval_s <= 0:
            self.next_run_s = now_s
        else:
            self.next_run_s = now_s + self.interval_s
        self.tick(now_s)

    def tick(self, now_s):
        return


class ReaderService(PollingService):
    """Poll USB input and update runtime state cache."""

    def __init__(self, sbc, interval_ms, bus=None, audit_sink=None):
        super().__init__("reader", interval_ms)
        self.sbc = sbc
        self.bus = bus
        self.audit_sink = audit_sink
        self.latest_state = None

    def tick(self, now_s):
        buf = self.sbc.read_raw()
        self.latest_state = self.sbc.parse_state(buf)
        if self.bus is not None:
            self.bus.publish("reader.state", self.latest_state)
        if self.audit_sink is not None:
            self.audit_sink.log(
                "service_tick",
                {"service": self.name, "buttons": sum(1 for b in self.latest_state["buttons"] if b)},
                service=self.name,
            )


class WriterService(PollingService):
    """Own LED write path and external LED animation commands."""

    def __init__(
        self,
        sbc,
        macro_engine,
        effective_config,
        led_mode,
        state_provider,
        interval_ms,
        bus=None,
    ):
        super().__init__("writer", interval_ms)
        self.sbc = sbc
        self.macro_engine = macro_engine
        self.effective_config = effective_config
        self.led_mode = led_mode
        self.state_provider = state_provider
        self.bus = bus
        self.gear_effects = GearEffectController(sbc, macro_engine, effective_config)
        self._command_lock = threading.Lock()
        self._queued_commands = deque()
        self._steady_overrides = {}
        self._effect_overrides = {}
        self._pattern_overrides = {}
        if self.bus is not None:
            self.bus.subscribe("command.led", self._enqueue_led_command)

    def _enqueue_led_command(self, payload):
        with self._command_lock:
            self._queued_commands.append(dict(payload or {}))

    def _normalize_led_name(self, led_name):
        if not led_name:
            return None
        raw = str(led_name).strip()
        if raw in self.sbc.led_name_to_id:
            return raw
        alias = self.sbc.led_name_alias.get(raw.lower())
        return alias

    @staticmethod
    def _safe_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _process_pending_commands(self, now_s):
        with self._command_lock:
            commands = list(self._queued_commands)
            self._queued_commands.clear()
        for command in commands:
            self._apply_command(command, now_s)

    def _apply_command(self, command, now_s):
        led_name = self._normalize_led_name(command.get("led"))
        if led_name is None:
            return
        mode = str(command.get("mode", "steady")).strip().lower()
        intensity = self.sbc._clamp_intensity(
            self._safe_int(command.get("intensity", self.sbc.MAX_LIGHT_INTENSITY), self.sbc.MAX_LIGHT_INTENSITY)
        )
        duration_ms = command.get("duration_ms")
        duration_ms = self._safe_int(duration_ms, 0) if duration_ms is not None else None

        if mode in ("clear", "default"):
            self._steady_overrides.pop(led_name, None)
            self._effect_overrides.pop(led_name, None)
            self._pattern_overrides.pop(led_name, None)
            return

        if mode in ("off", "steady", "on"):
            target = 0 if mode == "off" else intensity
            self._steady_overrides[led_name] = target
            self._effect_overrides.pop(led_name, None)
            self._pattern_overrides.pop(led_name, None)
            return

        if mode == "blink":
            period_ms = max(1, self._safe_int(command.get("period_ms", 500), 500))
            on_ms = max(1, self._safe_int(command.get("on_ms", period_ms // 2), period_ms // 2))
            self._steady_overrides.pop(led_name, None)
            self._pattern_overrides.pop(led_name, None)
            self._effect_overrides[led_name] = {
                "type": "blink",
                "start": now_s,
                "duration_ms": duration_ms,
                "period_ms": period_ms,
                "on_ms": on_ms,
                "intensity": intensity,
            }
            return

        if mode == "breathe":
            period_ms = max(1, self._safe_int(command.get("period_ms", 2000), 2000))
            min_val = self.sbc._clamp_intensity(self._safe_int(command.get("min", 0), 0))
            max_val = self.sbc._clamp_intensity(self._safe_int(command.get("max", intensity), intensity))
            self._steady_overrides.pop(led_name, None)
            self._pattern_overrides.pop(led_name, None)
            self._effect_overrides[led_name] = {
                "type": "breathe",
                "start": now_s,
                "duration_ms": duration_ms,
                "period_ms": period_ms,
                "min": min_val,
                "max": max_val,
            }
            return

        if mode == "pattern":
            steps = []
            for step in command.get("steps", []):
                if not isinstance(step, dict):
                    continue
                step_ms = max(1, self._safe_int(step.get("duration_ms", 100), 100))
                step_intensity = self.sbc._clamp_intensity(self._safe_int(step.get("intensity", 0), 0))
                steps.append({"duration_ms": step_ms, "intensity": step_intensity})
            if not steps:
                return
            self._steady_overrides.pop(led_name, None)
            self._effect_overrides.pop(led_name, None)
            self._pattern_overrides[led_name] = {
                "type": "pattern",
                "start": now_s,
                "steps": steps,
                "repeat": bool(command.get("repeat", True)),
                "hold_final": bool(command.get("hold_final", False)),
            }

    @staticmethod
    def _effect_expired(effect, now_s):
        duration_ms = effect.get("duration_ms")
        if duration_ms is None:
            return False
        return (now_s - effect["start"]) * 1000.0 >= float(duration_ms)

    def _effect_intensity(self, effect, now_s):
        if self._effect_expired(effect, now_s):
            return None
        kind = effect.get("type")
        elapsed_s = max(0.0, now_s - effect.get("start", now_s))
        if kind == "blink":
            period_s = max(0.001, float(effect.get("period_ms", 500)) / 1000.0)
            on_s = max(0.0, float(effect.get("on_ms", 250)) / 1000.0)
            phase = elapsed_s % period_s
            return int(effect.get("intensity", 15)) if phase <= on_s else 0
        if kind == "breathe":
            period_s = max(0.001, float(effect.get("period_ms", 2000)) / 1000.0)
            cycle = (elapsed_s % period_s) / period_s
            tri = 1.0 - abs(2.0 * cycle - 1.0)
            min_val = int(effect.get("min", 0))
            max_val = int(effect.get("max", 15))
            return int(min_val + (max_val - min_val) * tri)
        return None

    def _pattern_intensity(self, pattern, now_s):
        steps = pattern.get("steps", [])
        if not steps:
            return None
        total_ms = sum(step["duration_ms"] for step in steps)
        if total_ms <= 0:
            return None
        elapsed_ms = int((now_s - pattern.get("start", now_s)) * 1000.0)
        if not pattern.get("repeat", True) and elapsed_ms >= total_ms:
            if pattern.get("hold_final", False):
                return steps[-1]["intensity"]
            return None
        phase_ms = elapsed_ms % total_ms
        cursor = 0
        for step in steps:
            cursor += step["duration_ms"]
            if phase_ms < cursor:
                return step["intensity"]
        return steps[-1]["intensity"]

    def _apply_overrides(self, now_s):
        dirty = False
        expired_effects = []
        expired_patterns = []

        for led_name, intensity in self._steady_overrides.items():
            led_id = self.sbc.led_name_to_id.get(led_name)
            if led_id is None:
                continue
            target = self.sbc._clamp_intensity(int(intensity))
            if self.sbc.led_state.get(led_id, 0) != target:
                self.sbc.set_led(led_id, target, send=False)
                dirty = True

        for led_name, effect in self._effect_overrides.items():
            led_id = self.sbc.led_name_to_id.get(led_name)
            if led_id is None:
                continue
            target = self._effect_intensity(effect, now_s)
            if target is None:
                expired_effects.append(led_name)
                continue
            target = self.sbc._clamp_intensity(int(target))
            if self.sbc.led_state.get(led_id, 0) != target:
                self.sbc.set_led(led_id, target, send=False)
                dirty = True

        for led_name, pattern in self._pattern_overrides.items():
            led_id = self.sbc.led_name_to_id.get(led_name)
            if led_id is None:
                continue
            target = self._pattern_intensity(pattern, now_s)
            if target is None:
                expired_patterns.append(led_name)
                continue
            target = self.sbc._clamp_intensity(int(target))
            if self.sbc.led_state.get(led_id, 0) != target:
                self.sbc.set_led(led_id, target, send=False)
                dirty = True

        for led_name in expired_effects:
            self._effect_overrides.pop(led_name, None)
        for led_name in expired_patterns:
            self._pattern_overrides.pop(led_name, None)

        if dirty:
            self.sbc.write_leds()

    def tick(self, now_s):
        state = self.state_provider()
        if state is None:
            return
        self._process_pending_commands(now_s)
        self.sbc.handle_button_leds(self.led_mode)
        self.sbc.update_logical_states(self.led_mode)
        if self.sbc.update_gear_lights:
            self.gear_effects.update(state.get("gear"))
        self.macro_engine.tick()
        self._apply_overrides(now_s)


class ModelService(PollingService):
    """Drive vessel model transitions from current physical edge state."""

    def __init__(self, sbc, vessel_model, interval_ms, event_sink=None, snapshot_interval_ms=250):
        super().__init__("model", interval_ms)
        self.sbc = sbc
        self.vessel_model = vessel_model
        self.event_sink = event_sink
        self.snapshot_interval_s = max(0.0, float(snapshot_interval_ms) / 1000.0)
        self._next_snapshot_s = 0.0

    def tick(self, now_s):
        if self.sbc.raw_control_data is None:
            return
        for control_name, index in self.sbc.button_name_to_index.items():
            if self.sbc.button_changed(index):
                self.vessel_model.on_control_change(
                    control_name,
                    self.sbc.get_button_state(index),
                    logical_state=self.sbc.get_logical_state(control_name),
                )
        self.vessel_model.tick()
        if self.event_sink is not None and now_s >= self._next_snapshot_s:
            self.event_sink.publish(
                {
                    "type": "vessel_snapshot",
                    "snapshot": self.vessel_model.snapshot(),
                }
            )
            self._next_snapshot_s = now_s + self.snapshot_interval_s


class MacroDispatchService(PollingService):
    """Run macro dispatch paths from physical and queued synthetic input."""

    def __init__(self, macro_engine, input_matrix, led_mode, state_provider, interval_ms, event_sink=None):
        super().__init__("macro_dispatch", interval_ms)
        self.macro_engine = macro_engine
        self.input_matrix = input_matrix
        self.led_mode = led_mode
        self.state_provider = state_provider
        self.event_sink = event_sink

    def tick(self, now_s):
        state = self.state_provider()
        if state is None:
            return
        self.macro_engine.handle_layer_cycle()
        self.macro_engine.handle_buttons(state, self.led_mode)
        self.macro_engine.handle_analogs(state)
        self.macro_engine.handle_gears(state)

        for queued in self.input_matrix.drain():
            event_type = queued.get("type")
            if event_type == "button":
                self.macro_engine.handle_button_event(
                    queued.get("control"),
                    bool(queued.get("pressed")),
                    changed=True,
                    default_led_mode=self.led_mode,
                )
            elif event_type == "macro":
                self.macro_engine.run_macro(queued.get("macro"))
            elif event_type == "event" and self.event_sink is not None:
                self.event_sink.publish({"type": "input_event", "event": queued})


class TelemetryService(PollingService):
    """Publish sampled raw-state telemetry to configured event sink."""

    def __init__(self, state_provider, interval_ms, event_sink=None):
        super().__init__("telemetry", interval_ms)
        self.state_provider = state_provider
        self.event_sink = event_sink

    def tick(self, now_s):
        if self.event_sink is None:
            return
        state = self.state_provider()
        if state is None:
            return
        self.event_sink.publish(
            {
                "type": "raw_state",
                "buttons": [1 if pressed else 0 for pressed in state["buttons"]],
                "analogs": {
                    "aim_x": state["aim_x"],
                    "aim_y": state["aim_y"],
                    "rotation": state["rotation"],
                    "sight_x": state["sight_x"],
                    "sight_y": state["sight_y"],
                    "left_pedal": state["left_pedal"],
                    "middle_pedal": state["middle_pedal"],
                    "right_pedal": state["right_pedal"],
                },
                "tuner": state["tuner"],
                "gear": state["gear"],
            }
        )


class UIService(PollingService):
    """Render UI and process touch input at UI-oriented cadence."""

    def __init__(self, ui, touch, macro_engine, state_provider, interval_ms):
        super().__init__("ui", interval_ms)
        self.ui = ui
        self.touch = touch
        self.macro_engine = macro_engine
        self.state_provider = state_provider

    def tick(self, now_s):
        if self.ui is None:
            return
        state = self.state_provider()
        if state is None:
            return
        self.ui.set_layer(self.macro_engine.layer)
        if self.touch is not None:
            point = self.touch.poll()
            if point:
                self.ui.handle_touch(*point)
        self.ui.render(state)


class ShutdownService(PollingService):
    """Stop runtime when shutdown gesture is held."""

    def __init__(self, sbc, interval_ms, stop_callback):
        super().__init__("shutdown", interval_ms)
        self.sbc = sbc
        self.stop_callback = stop_callback

    def tick(self, now_s):
        if self.sbc.should_terminate():
            self.stop_callback()


class CommandRouter:
    """Route inbound Node-RED/MQTT commands into runtime queues."""

    def __init__(self, bus, input_matrix, event_sink=None):
        self.bus = bus
        self.input_matrix = input_matrix
        self.event_sink = event_sink
        if self.bus is not None:
            self.bus.subscribe("command.button", self._on_button_command)
            self.bus.subscribe("command.macro", self._on_macro_command)
            self.bus.subscribe("command.event", self._on_event_command)

    def _on_button_command(self, payload):
        control_name = (payload or {}).get("control")
        pressed = bool((payload or {}).get("pressed", True))
        self.input_matrix.queue_button(control_name, pressed, source="mqtt", payload=payload or {})
        if self.event_sink is not None:
            self.event_sink.publish({"type": "command_button", "control": control_name, "pressed": pressed})

    def _on_macro_command(self, payload):
        macro_name = (payload or {}).get("macro")
        self.input_matrix.queue_macro(macro_name, source="mqtt", payload=payload or {})
        if self.event_sink is not None:
            self.event_sink.publish({"type": "command_macro", "macro": macro_name})

    def _on_event_command(self, payload):
        name = (payload or {}).get("name")
        self.input_matrix.queue_event(name, source="mqtt", payload=payload or {})
        if self.event_sink is not None:
            self.event_sink.publish({"type": "command_event", "name": name})


class ServiceRuntime:
    """Simple cooperative scheduler for polling services."""

    def __init__(self, services, audit_sink=None):
        self.services = list(services or [])
        self.audit_sink = audit_sink
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True

    def run(self):
        for service in self.services:
            service.next_run_s = 0.0

        while not self.stop_requested:
            now_s = time.monotonic()
            ran_any = False
            next_due_s = None

            for service in self.services:
                if service.due(now_s):
                    service.run(now_s)
                    ran_any = True
                due_s = service.next_run_s
                if next_due_s is None or due_s < next_due_s:
                    next_due_s = due_s

            if not ran_any:
                if next_due_s is None:
                    time.sleep(0.001)
                    continue
                sleep_s = max(0.0005, min(0.02, next_due_s - time.monotonic()))
                time.sleep(sleep_s)


def build_services(
    sbc,
    macro_engine,
    vessel_model,
    input_matrix,
    effective,
    led_mode,
    ui=None,
    touch=None,
    event_sink=None,
    bus=None,
    runtime=None,
):
    """Create the v1.0 service set and return list ordered by dependency."""
    services_cfg = effective.get("services", {}) if isinstance(effective, dict) else {}
    net_cfg = effective.get("net_server", {}) if isinstance(effective, dict) else {}
    reader_ms = int(services_cfg.get("reader_poll_ms", effective.get("poll_interval_ms", 4)))
    writer_ms = int(services_cfg.get("writer_poll_ms", effective.get("poll_interval_ms", 4)))
    model_ms = int(services_cfg.get("model_poll_ms", effective.get("poll_interval_ms", 4)))
    macro_ms = int(services_cfg.get("macro_poll_ms", effective.get("poll_interval_ms", 4)))
    ui_ms = int(services_cfg.get("ui_poll_ms", 20))
    shutdown_ms = int(services_cfg.get("shutdown_poll_ms", 20))
    telemetry_ms = int(services_cfg.get("telemetry_poll_ms", net_cfg.get("send_interval_ms", 20)))
    model_snapshot_ms = int(services_cfg.get("model_snapshot_ms", 250))

    reader_service = ReaderService(sbc, interval_ms=reader_ms, bus=bus)
    state_provider = lambda: reader_service.latest_state
    writer_service = WriterService(
        sbc=sbc,
        macro_engine=macro_engine,
        effective_config=effective,
        led_mode=led_mode,
        state_provider=state_provider,
        interval_ms=writer_ms,
        bus=bus,
    )
    model_service = ModelService(
        sbc=sbc,
        vessel_model=vessel_model,
        interval_ms=model_ms,
        event_sink=event_sink,
        snapshot_interval_ms=model_snapshot_ms,
    )
    macro_service = MacroDispatchService(
        macro_engine=macro_engine,
        input_matrix=input_matrix,
        led_mode=led_mode,
        state_provider=state_provider,
        interval_ms=macro_ms,
        event_sink=event_sink,
    )
    telemetry_service = TelemetryService(
        state_provider=state_provider,
        interval_ms=telemetry_ms,
        event_sink=event_sink,
    )

    service_list = [
        reader_service,
        writer_service,
        model_service,
        macro_service,
        telemetry_service,
    ]
    if ui is not None:
        service_list.append(UIService(ui, touch, macro_engine, state_provider, interval_ms=ui_ms))
    if runtime is not None:
        service_list.append(ShutdownService(sbc, interval_ms=shutdown_ms, stop_callback=runtime.stop))
    return service_list
