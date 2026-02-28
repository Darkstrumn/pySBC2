#!/usr/bin/python3
import math
import signal
import threading
import time
from collections import deque
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from process_services_common import MqttJsonClient, RuntimeContextLog, load_effective_config, resolve_topics


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class AICopilotEngine:
    """Intent/diagnostic inference and command policy layer."""

    def __init__(self, config, log=None):
        cfg = dict(config or {})
        self.log = log
        self.enabled = bool(cfg.get("enabled", True))
        self.mode = str(cfg.get("mode", "advisory")).strip().lower()
        self.emit_interval_s = max(0.05, _safe_float(cfg.get("emit_interval_ms", 200), 200.0) / 1000.0)
        self.command_cooldown_s = max(
            0.1,
            _safe_float(cfg.get("command_cooldown_ms", 700), 700.0) / 1000.0,
        )
        self.intent_threshold = _safe_float(cfg.get("confidence_threshold", 0.65), 0.65)
        self.auto_macro_threshold = _safe_float(cfg.get("auto_macro_threshold", 0.8), 0.8)
        self.diagnostic_threshold = _safe_float(cfg.get("diagnostic_threshold", 0.75), 0.75)
        self.intent_macro_map = dict(cfg.get("intent_macro_map", {}))
        self.intent_led_map = dict(cfg.get("intent_led_map", {}))
        self.window_size = max(4, _safe_int(cfg.get("window_size", 12), 12))
        self.feature_window = deque(maxlen=self.window_size)
        self.last_raw_state = None
        self.last_vessel_snapshot = None
        self.last_intent_emit_s = 0.0
        self.last_diag_emit_s = 0.0
        self.last_command_s = 0.0
        self.last_intent_name = None
        self.labels = list(cfg.get("labels", []))
        self.model_type = str(cfg.get("model_type", "heuristic")).strip().lower()
        self.model_path = str(cfg.get("model_path", "models/copilot_model.keras"))
        self._model = None
        self._tflite = None
        self._np = None
        self._load_model()

    def _load_model(self):
        if self.model_type == "heuristic":
            return
        path = Path(self.model_path)
        if not path.exists():
            self._log("model_missing", {"path": self.model_path})
            return
        if self.model_type in {"auto", "tensorflow", "keras"}:
            try:
                import tensorflow as tf
                import numpy as np
            except Exception:
                tf = None
                np = None
            if tf is not None and np is not None:
                try:
                    self._model = tf.keras.models.load_model(str(path))
                    self._np = np
                    self._log("model_loaded", {"type": "tensorflow", "path": self.model_path})
                    return
                except Exception:
                    self._model = None
                    self._np = None
                    self._log("model_load_failed", {"type": "tensorflow", "path": self.model_path})
        if self.model_type in {"auto", "tflite"}:
            interpreter = None
            try:
                from tflite_runtime.interpreter import Interpreter

                interpreter = Interpreter(model_path=str(path))
            except Exception:
                try:
                    import tensorflow as tf

                    interpreter = tf.lite.Interpreter(model_path=str(path))
                except Exception:
                    interpreter = None
            if interpreter is not None:
                try:
                    interpreter.allocate_tensors()
                    self._tflite = interpreter
                    self._log("model_loaded", {"type": "tflite", "path": self.model_path})
                    return
                except Exception:
                    self._tflite = None
                    self._log("model_load_failed", {"type": "tflite", "path": self.model_path})

    def set_mode(self, mode):
        new_mode = str(mode or "").strip().lower()
        if new_mode not in {"advisory", "assist", "auto"}:
            return False
        if new_mode == self.mode:
            return True
        self.mode = new_mode
        self._log("mode_changed", {"mode": self.mode})
        return True

    def update_raw_state(self, state):
        state = dict(state or {})
        self.last_raw_state = state
        self.feature_window.append(self._extract_features(state))

    def update_vessel_snapshot(self, snapshot):
        if isinstance(snapshot, dict):
            self.last_vessel_snapshot = snapshot

    def _extract_features(self, state):
        analogs = state.get("analogs", {}) if isinstance(state.get("analogs"), dict) else {}
        buttons = state.get("buttons", [])
        pressed_count = sum(1 for b in buttons if bool(b))
        gear = _safe_int(state.get("gear", 0), 0)
        gear_norm = (max(-2, min(5, gear)) + 2.0) / 7.0
        return [
            _safe_float(analogs.get("aim_x", 0), 0.0) / 512.0,
            _safe_float(analogs.get("aim_y", 0), 0.0) / 512.0,
            _safe_float(analogs.get("rotation", 0), 0.0) / 512.0,
            _safe_float(analogs.get("sight_x", 0), 0.0) / 512.0,
            _safe_float(analogs.get("sight_y", 0), 0.0) / 512.0,
            _safe_float(analogs.get("left_pedal", 0), 0.0) / 1023.0,
            _safe_float(analogs.get("middle_pedal", 0), 0.0) / 1023.0,
            _safe_float(analogs.get("right_pedal", 0), 0.0) / 1023.0,
            _safe_float(state.get("tuner", 0), 0.0) / 15.0,
            gear_norm,
            pressed_count / 39.0,
        ]

    def infer(self):
        if not self.enabled or self.last_raw_state is None:
            return None, None
        intent = self._infer_intent()
        diagnostic = self._infer_diagnostic()
        return intent, diagnostic

    def _infer_intent(self):
        model_intent = self._infer_intent_from_model()
        if model_intent is not None:
            return model_intent
        return self._infer_intent_heuristic()

    def _infer_intent_from_model(self):
        if not self.feature_window:
            return None
        if self._model is None and self._tflite is None:
            return None
        try:
            features = list(self.feature_window)
            if len(features) < self.window_size:
                first = features[0]
                pad = [first for _ in range(self.window_size - len(features))]
                features = pad + features
            else:
                features = features[-self.window_size :]
            if self._model is not None and self._np is not None:
                x = self._np.array([features], dtype=self._np.float32)
                out = self._model.predict(x, verbose=0)
                logits = out[0] if hasattr(out, "__len__") else out
                return self._decode_logits(logits, source="tensorflow")
            if self._tflite is not None:
                import numpy as np

                input_details = self._tflite.get_input_details()
                output_details = self._tflite.get_output_details()
                x = np.array([features], dtype=np.float32)
                self._tflite.set_tensor(input_details[0]["index"], x)
                self._tflite.invoke()
                logits = self._tflite.get_tensor(output_details[0]["index"])[0]
                return self._decode_logits(logits, source="tflite")
        except Exception:
            return None
        return None

    def _decode_logits(self, logits, source):
        values = [float(v) for v in logits]
        if not values:
            return None
        max_index = max(range(len(values)), key=lambda i: values[i])
        max_val = values[max_index]
        # Treat output as probabilities if sum ~ 1, else softmax.
        total = sum(values)
        if total <= 0.0 or total > 1.5:
            exp_vals = [math.exp(v) for v in values]
            exp_total = sum(exp_vals)
            probs = [v / exp_total for v in exp_vals]
        else:
            probs = [v / total for v in values]
        confidence = float(probs[max_index])
        label = self.labels[max_index] if max_index < len(self.labels) else f"intent_{max_index}"
        return {
            "intent": label,
            "confidence": confidence,
            "source": source,
        }

    def _infer_intent_heuristic(self):
        state = self.last_raw_state or {}
        analogs = state.get("analogs", {}) if isinstance(state.get("analogs"), dict) else {}
        aim_x = abs(_safe_float(analogs.get("aim_x", 0), 0.0))
        aim_y = abs(_safe_float(analogs.get("aim_y", 0), 0.0))
        left = _safe_float(analogs.get("left_pedal", 0), 0.0)
        middle = _safe_float(analogs.get("middle_pedal", 0), 0.0)
        right = _safe_float(analogs.get("right_pedal", 0), 0.0)
        gear = _safe_int(state.get("gear", 0), 0)

        if gear == 5 and right > 700:
            return {"intent": "supercruise_transition", "confidence": 0.84, "source": "heuristic"}
        if middle > 820 and right < 180:
            return {"intent": "hard_brake", "confidence": 0.81, "source": "heuristic"}
        if aim_x > 280 and aim_y > 260 and right > 300:
            return {"intent": "evasive_maneuver", "confidence": 0.76, "source": "heuristic"}
        if aim_x > 260 and right > 250:
            return {"intent": "target_lock", "confidence": 0.71, "source": "heuristic"}
        if left > 850 and right > 850:
            return {"intent": "boost_vector", "confidence": 0.69, "source": "heuristic"}
        return {"intent": "steady_control", "confidence": 0.55, "source": "heuristic"}

    def _infer_diagnostic(self):
        state = self.last_raw_state or {}
        analogs = state.get("analogs", {}) if isinstance(state.get("analogs"), dict) else {}
        left = _safe_float(analogs.get("left_pedal", 0), 0.0)
        middle = _safe_float(analogs.get("middle_pedal", 0), 0.0)
        right = _safe_float(analogs.get("right_pedal", 0), 0.0)
        gear = _safe_int(state.get("gear", 0), 0)

        if left > 930 and middle > 930 and right > 930:
            return {
                "diagnostic": "sensor_conflict_pedals",
                "severity": "critical",
                "confidence": 0.9,
                "source": "heuristic",
            }
        snapshot = self.last_vessel_snapshot if isinstance(self.last_vessel_snapshot, dict) else {}
        state_map = snapshot.get("state", {}) if isinstance(snapshot.get("state"), dict) else {}
        online = bool(state_map.get("online", False))
        if not online and gear > 0:
            return {
                "diagnostic": "startup_state_mismatch",
                "severity": "warning",
                "confidence": 0.78,
                "source": "heuristic",
            }
        return None

    def should_emit_intent(self, now_s, intent):
        if intent is None:
            return False
        if now_s - self.last_intent_emit_s >= self.emit_interval_s:
            return True
        if intent.get("intent") != self.last_intent_name:
            return True
        return False

    def mark_intent_emitted(self, now_s, intent):
        self.last_intent_emit_s = now_s
        self.last_intent_name = intent.get("intent")

    def should_emit_diag(self, now_s, diag):
        if diag is None:
            return False
        if now_s - self.last_diag_emit_s >= self.emit_interval_s:
            return True
        return False

    def mark_diag_emitted(self, now_s):
        self.last_diag_emit_s = now_s

    def should_issue_command(self, now_s):
        return (now_s - self.last_command_s) >= self.command_cooldown_s

    def mark_command(self, now_s):
        self.last_command_s = now_s

    def command_plan(self, intent):
        if intent is None:
            return []
        intent_name = intent.get("intent")
        confidence = _safe_float(intent.get("confidence", 0.0), 0.0)
        if confidence < self.intent_threshold:
            return []

        commands = []
        cue_led = self.intent_led_map.get(intent_name)
        if cue_led:
            commands.append(
                {
                    "topic_type": "led",
                    "payload": {
                        "led": cue_led,
                        "mode": "blink",
                        "period_ms": 400,
                        "on_ms": 200,
                        "intensity": 15,
                        "duration_ms": 1200,
                        "source": "ai_copilot",
                        "intent": intent_name,
                    },
                }
            )
        macro_name = self.intent_macro_map.get(intent_name)
        if macro_name and confidence >= self.auto_macro_threshold:
            commands.append(
                {
                    "topic_type": "macro",
                    "payload": {
                        "macro": macro_name,
                        "source": "ai_copilot",
                        "intent": intent_name,
                        "confidence": confidence,
                    },
                }
            )
        return commands

    def _log(self, message, payload):
        if self.log is None:
            return
        self.log.write("sbc-ai-copilot-service", message, payload)


def main():
    effective = load_effective_config("sbc_config.json")
    mqtt_cfg = effective.get("mqtt", {})
    services_cfg = effective.get("services", {})
    ai_cfg = effective.get("ai_copilot", {})
    audit_cfg = effective.get("audit", {})
    topics = resolve_topics(effective)
    log = RuntimeContextLog(str(audit_cfg.get("path", "runtime_context.log")))
    mqtt = MqttJsonClient(mqtt_cfg, client_id="sbc-ai-copilot-service", log=log)
    engine = AICopilotEngine(ai_cfg, log=log)

    raw_queue = deque(maxlen=16)
    vessel_queue = deque(maxlen=16)
    queue_lock = threading.Lock()

    def _on_raw(payload, topic):
        with queue_lock:
            raw_queue.append(dict(payload or {}))

    def _on_vessel(payload, topic):
        with queue_lock:
            vessel_queue.append(dict(payload or {}))

    def _on_mode(payload, topic):
        requested = (payload or {}).get("mode")
        if engine.set_mode(requested):
            mqtt.publish(
                topics["event_ai_intent"],
                {
                    "type": "ai_mode",
                    "mode": engine.mode,
                    "timestamp_ms": int(time.time() * 1000),
                },
            )

    mqtt.subscribe(topics["event_raw_state"], _on_raw)
    mqtt.subscribe(topics["event_vessel_snapshot"], _on_vessel)
    mqtt.subscribe(topics["cmd_ai_mode"], _on_mode)
    mqtt.start()

    poll_ms = int(services_cfg.get("ai_poll_ms", 50))
    if poll_ms < 10:
        poll_ms = 10

    stop_event = threading.Event()

    def _stop_handler(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)

    log.write(
        "sbc-ai-copilot-service",
        "started",
        {
            "poll_ms": poll_ms,
            "mode": engine.mode,
            "intent_topic": topics["event_ai_intent"],
            "diag_topic": topics["event_ai_diagnostic"],
        },
    )
    try:
        while not stop_event.is_set():
            with queue_lock:
                raw_events = list(raw_queue)
                raw_queue.clear()
                vessel_events = list(vessel_queue)
                vessel_queue.clear()

            for event in raw_events:
                if event.get("type") != "raw_state":
                    continue
                engine.update_raw_state(event)

            for event in vessel_events:
                if event.get("type") != "vessel_snapshot":
                    continue
                snapshot = event.get("snapshot", {})
                if isinstance(snapshot, dict):
                    engine.update_vessel_snapshot(snapshot)

            intent, diag = engine.infer()
            now_s = time.monotonic()

            if engine.should_emit_intent(now_s, intent):
                intent_name = intent.get("intent") if isinstance(intent, dict) else None
                confidence = _safe_float((intent or {}).get("confidence", 0.0), 0.0)
                payload = {
                    "type": "ai_intent",
                    "mode": engine.mode,
                    "intent": intent_name,
                    "confidence": confidence,
                    "source": (intent or {}).get("source"),
                    "recommended_macro": engine.intent_macro_map.get(intent_name),
                    "timestamp_ms": int(time.time() * 1000),
                }
                mqtt.publish(topics["event_ai_intent"], payload)
                engine.mark_intent_emitted(now_s, intent or {})

                if engine.mode in {"assist", "auto"} and engine.should_issue_command(now_s):
                    commands = engine.command_plan(intent or {})
                    for command in commands:
                        if command["topic_type"] == "led":
                            mqtt.publish(topics["cmd_led"], command["payload"])
                        elif command["topic_type"] == "macro" and engine.mode == "auto":
                            mqtt.publish(topics["cmd_macro"], command["payload"])
                    if commands:
                        engine.mark_command(now_s)

            if engine.should_emit_diag(now_s, diag):
                confidence = _safe_float((diag or {}).get("confidence", 0.0), 0.0)
                if confidence >= engine.diagnostic_threshold:
                    mqtt.publish(
                        topics["event_ai_diagnostic"],
                        {
                            "type": "ai_diagnostic",
                            "mode": engine.mode,
                            "diagnostic": diag.get("diagnostic"),
                            "severity": diag.get("severity"),
                            "confidence": confidence,
                            "source": diag.get("source"),
                            "timestamp_ms": int(time.time() * 1000),
                        },
                    )
                engine.mark_diag_emitted(now_s)

            time.sleep(poll_ms / 1000.0)
    finally:
        mqtt.stop()
        log.write("sbc-ai-copilot-service", "stopped", {})


if __name__ == "__main__":
    main()
