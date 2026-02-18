#!/usr/bin/python3
import signal
import threading
import time
from collections import deque
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import build_default_led_modes
from input_matrix import InputMatrix
from macro_engine import MacroEngine
from sbc_driver import SBCDriver

from process_services_common import (
    MqttEventSink,
    MqttJsonClient,
    RuntimeContextLog,
    load_effective_config,
    resolve_topics,
)


class MacroSBCProxy:
    """Minimal SBC adapter for macro processing in a process-isolated service."""

    def __init__(self, effective, mqtt, topics):
        self.template = SBCDriver()
        self.mqtt = mqtt
        self.topics = topics
        self.button_names = list(self.template.button_names)
        self.button_name_to_index = dict(self.template.button_name_to_index)
        self.button_to_led_name = dict(self.template.button_to_led_name)
        self.led_name_to_id = dict(self.template.led_name_to_id)
        self.led_name_alias = dict(self.template.led_name_alias)
        self.led_state = {i: 0 for i in range(self.template.LED_ID_MIN, self.template.LED_ID_MAX + 1)}
        self.logical_state = {name: False for name in self.button_names}
        self.last_values = {
            "aim_x": 0,
            "aim_y": 0,
            "rotation": 0,
            "sight_x": 0,
            "sight_y": 0,
            "left_pedal": 0,
            "middle_pedal": 0,
            "right_pedal": 0,
            "tuner": 0,
            "gear": 0,
        }
        self._buttons = [False] * 39
        self._prev_buttons = [False] * 39
        self._changed_buttons = set()
        self._led_dirty = False

        base_led_mode = str(effective.get("led_mode", "toggle")).strip().lower()
        led_modes = build_default_led_modes(self.led_name_to_id)
        if isinstance(effective.get("led_modes"), dict):
            for key, value in effective["led_modes"].items():
                key_norm = str(key).strip().lower()
                for name in self.led_name_to_id.keys():
                    if name.lower() == key_norm:
                        led_modes[name] = str(value).strip()
                        break
        self.base_led_mode = base_led_mode
        self.led_modes = led_modes

    _parse_led_mode = staticmethod(SBCDriver._parse_led_mode)

    def set_led_modes(self, modes):
        if isinstance(modes, dict):
            self.led_modes = dict(modes)

    def _clamp_intensity(self, value):
        return self.template._clamp_intensity(value)

    def update_from_event_state(self, state):
        buttons = [bool(v) for v in (state.get("buttons") or [])]
        if len(buttons) < 39:
            buttons.extend([False] * (39 - len(buttons)))
        elif len(buttons) > 39:
            buttons = buttons[:39]
        self._prev_buttons = list(self._buttons)
        self._buttons = buttons
        self._changed_buttons = {idx for idx in range(39) if self._buttons[idx] != self._prev_buttons[idx]}

        analogs = state.get("analogs", {}) if isinstance(state.get("analogs"), dict) else {}
        self.last_values["aim_x"] = analogs.get("aim_x", self.last_values["aim_x"])
        self.last_values["aim_y"] = analogs.get("aim_y", self.last_values["aim_y"])
        self.last_values["rotation"] = analogs.get("rotation", self.last_values["rotation"])
        self.last_values["sight_x"] = analogs.get("sight_x", self.last_values["sight_x"])
        self.last_values["sight_y"] = analogs.get("sight_y", self.last_values["sight_y"])
        self.last_values["left_pedal"] = analogs.get("left_pedal", self.last_values["left_pedal"])
        self.last_values["middle_pedal"] = analogs.get("middle_pedal", self.last_values["middle_pedal"])
        self.last_values["right_pedal"] = analogs.get("right_pedal", self.last_values["right_pedal"])
        self.last_values["tuner"] = state.get("tuner", self.last_values["tuner"])
        self.last_values["gear"] = state.get("gear", self.last_values["gear"])

        for name, idx in self.button_name_to_index.items():
            physical = self._buttons[idx]
            led_name = self.button_to_led_name.get(idx)
            if led_name is None:
                self.logical_state[name] = physical
                continue
            mode_raw = self.led_modes.get(led_name, self.base_led_mode)
            mode, _ = self._parse_led_mode(mode_raw)
            led_id = self.led_name_to_id.get(led_name)
            led_on = self.led_state.get(led_id, 0) > 0 if led_id is not None else False
            if mode in ("toggle", "latched"):
                self.logical_state[name] = led_on
            else:
                self.logical_state[name] = physical

    def get_button_state(self, button_index):
        if button_index is None or button_index < 0 or button_index >= len(self._buttons):
            return False
        return bool(self._buttons[button_index])

    def button_changed(self, button_index):
        return button_index in self._changed_buttons

    def get_logical_state(self, name):
        return bool(self.logical_state.get(name, False))

    def set_led(self, led_id, intensity, send=True):
        if led_id in self.template.LED_ID_UNUSED:
            return
        if led_id < self.template.LED_ID_MIN or led_id > self.template.LED_ID_MAX:
            return
        value = self._clamp_intensity(intensity)
        if self.led_state.get(led_id, 0) == value:
            return
        self.led_state[led_id] = value
        self._led_dirty = True
        if send:
            self.write_leds()

    def write_leds(self):
        if not self._led_dirty:
            return
        led_map = {name: int(self.led_state.get(led_id, 0)) for name, led_id in self.led_name_to_id.items()}
        self.mqtt.publish(
            self.topics["cmd_led_frame"],
            {
                "type": "cmd_led_frame",
                "source": "macro_service",
                "mode": "replace",
                "leds": led_map,
                "timestamp_ms": int(time.time() * 1000),
            },
        )
        self._led_dirty = False


def main():
    effective = load_effective_config("sbc_config.json")
    mqtt_cfg = effective.get("mqtt", {})
    services_cfg = effective.get("services", {})
    audit_cfg = effective.get("audit", {})
    topics = resolve_topics(effective)
    base_topic = str(mqtt_cfg.get("base_topic", "sbc")).strip("/")
    log = RuntimeContextLog(str(audit_cfg.get("path", "runtime_context.log")))

    mqtt = MqttJsonClient(mqtt_cfg, client_id="sbc-macro-service", log=log)
    event_sink = MqttEventSink(mqtt, base_topic=base_topic)
    sbc_proxy = MacroSBCProxy(effective, mqtt, topics)
    input_matrix = InputMatrix(event_sink=event_sink, max_events=int(effective.get("input_queue_size", 256)))
    macro_engine = MacroEngine(effective, sbc_proxy, ui=None, event_sink=event_sink, input_matrix=input_matrix)

    raw_state_queue = deque(maxlen=8)
    cmd_button_queue = deque(maxlen=512)
    cmd_macro_queue = deque(maxlen=256)
    queue_lock = threading.Lock()

    def _on_raw_state(payload, topic):
        with queue_lock:
            raw_state_queue.append(dict(payload or {}))

    def _on_cmd_button(payload, topic):
        with queue_lock:
            cmd_button_queue.append(dict(payload or {}))

    def _on_cmd_macro(payload, topic):
        with queue_lock:
            cmd_macro_queue.append(dict(payload or {}))

    mqtt.subscribe(topics["event_raw_state"], _on_raw_state)
    mqtt.subscribe(topics["cmd_button"], _on_cmd_button)
    mqtt.subscribe(topics["cmd_macro"], _on_cmd_macro)
    mqtt.start()

    poll_ms = int(services_cfg.get("macro_poll_ms", effective.get("poll_interval_ms", 4)))
    if poll_ms < 1:
        poll_ms = 1
    led_mode = str(effective.get("led_mode", "toggle")).strip().lower()
    errors = macro_engine.validate_macros()
    if errors:
        log.write("sbc-macro-service", "macro_validation_error", {"error": errors[0]})

    stop_event = threading.Event()

    def _stop_handler(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)
    log.write("sbc-macro-service", "started", {"poll_ms": poll_ms})

    try:
        while not stop_event.is_set():
            with queue_lock:
                states = list(raw_state_queue)
                raw_state_queue.clear()
                button_cmds = list(cmd_button_queue)
                cmd_button_queue.clear()
                macro_cmds = list(cmd_macro_queue)
                cmd_macro_queue.clear()

            for payload in states:
                state_payload = dict(payload or {})
                sbc_proxy.update_from_event_state(state_payload)
                macro_engine.handle_layer_cycle()
                macro_engine.handle_buttons(state_payload, led_mode)
                macro_engine.handle_analogs(state_payload)
                macro_engine.handle_gears(state_payload)

            for payload in button_cmds:
                control_name = payload.get("control")
                pressed = bool(payload.get("pressed", True))
                macro_engine.handle_button_event(control_name, pressed, changed=True, default_led_mode=led_mode)

            for payload in macro_cmds:
                macro_engine.run_macro(payload.get("macro"))

            for queued in input_matrix.drain():
                event_type = queued.get("type")
                if event_type == "button":
                    macro_engine.handle_button_event(
                        queued.get("control"),
                        bool(queued.get("pressed")),
                        changed=True,
                        default_led_mode=led_mode,
                    )
                elif event_type == "macro":
                    macro_engine.run_macro(queued.get("macro"))
                elif event_type == "event":
                    event_sink.publish({"type": "input_event", "event": queued})

            macro_engine.tick()
            sbc_proxy.write_leds()
            time.sleep(poll_ms / 1000.0)
    finally:
        mqtt.stop()
        log.write("sbc-macro-service", "stopped", {})


if __name__ == "__main__":
    main()
