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

from sbc_driver import SBCDriver

from process_services_common import MqttJsonClient, RuntimeContextLog, load_effective_config, resolve_topics


class LedWriterRuntime:
    def __init__(self, template):
        self.template = template
        self._lock = threading.Lock()
        self._queued_led_commands = deque()
        self._queued_frames = deque()
        self._steady = {}
        self._effects = {}
        self._patterns = {}
        self._current = {name: 0 for name in self.template.led_name_to_id.keys()}

    @staticmethod
    def _safe_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def enqueue_led_command(self, payload):
        with self._lock:
            self._queued_led_commands.append(dict(payload or {}))

    def enqueue_led_frame(self, payload):
        with self._lock:
            self._queued_frames.append(dict(payload or {}))

    def _normalize_led(self, name):
        if not name:
            return None
        raw = str(name).strip()
        if raw in self.template.led_name_to_id:
            return raw
        return self.template.led_name_alias.get(raw.lower())

    def _apply_frame(self, frame, now_s):
        leds = frame.get("leds", {})
        if not isinstance(leds, dict):
            return
        mode = str(frame.get("mode", "merge")).strip().lower()
        if mode == "replace":
            for name in self._current.keys():
                self._current[name] = 0
            self._steady.clear()
            self._effects.clear()
            self._patterns.clear()
        for led_name, value in leds.items():
            resolved = self._normalize_led(led_name)
            if resolved is None:
                continue
            intensity = self.template._clamp_intensity(self._safe_int(value, 0))
            self._current[resolved] = intensity
            self._steady[resolved] = intensity
            self._effects.pop(resolved, None)
            self._patterns.pop(resolved, None)

    def _apply_command(self, command, now_s):
        led_name = self._normalize_led(command.get("led"))
        if led_name is None:
            return
        mode = str(command.get("mode", "steady")).strip().lower()
        intensity = self.template._clamp_intensity(self._safe_int(command.get("intensity", 15), 15))
        duration_ms_raw = command.get("duration_ms")
        duration_ms = self._safe_int(duration_ms_raw, 0) if duration_ms_raw is not None else None

        if mode in {"clear", "default"}:
            self._steady.pop(led_name, None)
            self._effects.pop(led_name, None)
            self._patterns.pop(led_name, None)
            return

        if mode in {"off", "steady", "on"}:
            self._steady[led_name] = 0 if mode == "off" else intensity
            self._effects.pop(led_name, None)
            self._patterns.pop(led_name, None)
            return

        if mode == "blink":
            period_ms = max(1, self._safe_int(command.get("period_ms", 500), 500))
            on_ms = max(1, self._safe_int(command.get("on_ms", period_ms // 2), period_ms // 2))
            self._steady.pop(led_name, None)
            self._patterns.pop(led_name, None)
            self._effects[led_name] = {
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
            min_val = self.template._clamp_intensity(self._safe_int(command.get("min", 0), 0))
            max_val = self.template._clamp_intensity(self._safe_int(command.get("max", intensity), intensity))
            self._steady.pop(led_name, None)
            self._patterns.pop(led_name, None)
            self._effects[led_name] = {
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
                step_intensity = self.template._clamp_intensity(self._safe_int(step.get("intensity", 0), 0))
                steps.append({"duration_ms": step_ms, "intensity": step_intensity})
            if not steps:
                return
            self._steady.pop(led_name, None)
            self._effects.pop(led_name, None)
            self._patterns[led_name] = {
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
            return int(effect.get("intensity", 15)) if (elapsed_s % period_s) <= on_s else 0
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

    def tick(self, now_s):
        before = dict(self._current)
        with self._lock:
            queued_led_commands = list(self._queued_led_commands)
            self._queued_led_commands.clear()
            queued_frames = list(self._queued_frames)
            self._queued_frames.clear()

        for frame in queued_frames:
            self._apply_frame(frame, now_s)
        for command in queued_led_commands:
            self._apply_command(command, now_s)

        output = dict(self._current)
        for name, value in self._steady.items():
            output[name] = self.template._clamp_intensity(int(value))

        expired_effects = []
        for name, effect in self._effects.items():
            level = self._effect_intensity(effect, now_s)
            if level is None:
                expired_effects.append(name)
                continue
            output[name] = self.template._clamp_intensity(int(level))
        for name in expired_effects:
            self._effects.pop(name, None)

        expired_patterns = []
        for name, pattern in self._patterns.items():
            level = self._pattern_intensity(pattern, now_s)
            if level is None:
                expired_patterns.append(name)
                continue
            output[name] = self.template._clamp_intensity(int(level))
        for name in expired_patterns:
            self._patterns.pop(name, None)

        changed = output != before
        self._current = output
        return changed, dict(self._current)


def main():
    effective = load_effective_config("sbc_config.json")
    mqtt_cfg = effective.get("mqtt", {})
    services_cfg = effective.get("services", {})
    audit_cfg = effective.get("audit", {})
    topics = resolve_topics(effective)
    log = RuntimeContextLog(str(audit_cfg.get("path", "runtime_context.log")))

    template = SBCDriver()
    runtime = LedWriterRuntime(template)
    mqtt = MqttJsonClient(mqtt_cfg, client_id="sbc-writer-service", log=log)

    mqtt.subscribe(topics["cmd_led"], lambda payload, topic: runtime.enqueue_led_command(payload))
    mqtt.subscribe(topics["cmd_led_frame"], lambda payload, topic: runtime.enqueue_led_frame(payload))
    mqtt.start()

    poll_ms = int(services_cfg.get("writer_poll_ms", effective.get("poll_interval_ms", 4)))
    if poll_ms < 1:
        poll_ms = 1

    stop_event = threading.Event()

    def _stop_handler(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)

    log.write("sbc-writer-service", "started", {"poll_ms": poll_ms, "topic_cmd_led": topics["cmd_led"], "topic_io_led_frame": topics["io_led_frame"]})
    try:
        while not stop_event.is_set():
            changed, led_map = runtime.tick(time.monotonic())
            if changed:
                mqtt.publish(
                    topics["io_led_frame"],
                    {
                        "type": "io_led_frame",
                        "source": "writer_service",
                        "clear_missing": True,
                        "leds": led_map,
                        "timestamp_ms": int(time.time() * 1000),
                    },
                )
            time.sleep(poll_ms / 1000.0)
    finally:
        mqtt.stop()
        log.write("sbc-writer-service", "stopped", {})


if __name__ == "__main__":
    main()
