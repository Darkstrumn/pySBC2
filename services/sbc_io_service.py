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

from process_services_common import (
    MqttJsonClient,
    RuntimeContextLog,
    load_effective_config,
    resolve_topics,
)


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _apply_config(sbc, effective):
    sbc.FLASH_PERIOD_S = float(effective.get("flash_period_s", 0.3))
    sbc.TIME_BETWEEN_POLLS_MS = int(effective.get("poll_interval_ms", 4))
    sbc.set_gear_lights(
        bool(effective.get("update_gear_lights", True)),
        int(effective.get("gear_light_intensity", 8)),
    )
    sbc.GEAR_REVERSE_FLASH = bool(effective.get("gear_reverse_flash", True))
    if isinstance(effective.get("analog"), dict):
        sbc.set_analog_config(effective["analog"])
        sbc.calibration_configured = True
    else:
        sbc.calibration_configured = False


def _apply_led_frame(sbc, frame):
    frame = dict(frame or {})
    leds = frame.get("leds", {})
    if not isinstance(leds, dict):
        return

    clear_missing = bool(frame.get("clear_missing", False))
    target_by_id = {}
    for led_name, intensity in leds.items():
        if led_name is None:
            continue
        lookup = str(led_name).strip()
        resolved = sbc.led_name_alias.get(lookup.lower(), lookup)
        led_id = sbc.led_name_to_id.get(resolved)
        if led_id is None:
            continue
        target_by_id[led_id] = sbc._clamp_intensity(_safe_int(intensity, 0))

    dirty = False
    for led_id, target in target_by_id.items():
        if sbc.led_state.get(led_id, 0) != target:
            sbc.set_led(led_id, target, send=False)
            dirty = True

    if clear_missing:
        for led_id in range(sbc.LED_ID_MIN, sbc.LED_ID_MAX + 1):
            if led_id in sbc.LED_ID_UNUSED:
                continue
            if led_id in target_by_id:
                continue
            if sbc.led_state.get(led_id, 0) != 0:
                sbc.set_led(led_id, 0, send=False)
                dirty = True

    if dirty:
        sbc.write_leds()


def main():
    effective = load_effective_config("sbc_config.json")
    topics = resolve_topics(effective)
    mqtt_cfg = effective.get("mqtt", {})
    services_cfg = effective.get("services", {})
    audit_cfg = effective.get("audit", {})
    log = RuntimeContextLog(str(audit_cfg.get("path", "runtime_context.log")))

    sbc = SBCDriver()
    _apply_config(sbc, effective)
    sbc.open()

    mqtt = MqttJsonClient(mqtt_cfg, client_id="sbc-io-service", log=log)
    frame_queue = deque(maxlen=8)
    queue_lock = threading.Lock()

    def _on_led_frame(payload, topic):
        with queue_lock:
            frame_queue.append(dict(payload or {}))

    mqtt.subscribe(topics["io_led_frame"], _on_led_frame)
    mqtt.start()

    poll_ms = max(1, _safe_int(services_cfg.get("reader_poll_ms", effective.get("poll_interval_ms", 4)), 4))
    stop_event = threading.Event()

    def _stop_handler(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)

    log.write("sbc-io-service", "started", {"poll_ms": poll_ms, "topic_raw": topics["io_raw_state"], "topic_led_frame": topics["io_led_frame"]})
    try:
        while not stop_event.is_set():
            state = sbc.parse_state(sbc.read_raw())
            mqtt.publish(
                topics["io_raw_state"],
                {
                    "type": "io_raw_state",
                    "state": state,
                    "timestamp_ms": int(time.time() * 1000),
                },
            )

            next_frame = None
            with queue_lock:
                if frame_queue:
                    next_frame = frame_queue.pop()
                    frame_queue.clear()
            if next_frame is not None:
                _apply_led_frame(sbc, next_frame)

            time.sleep(poll_ms / 1000.0)
    finally:
        mqtt.stop()
        try:
            sbc.set_all_leds(0, send=True)
        except Exception:
            pass
        log.write("sbc-io-service", "stopped", {})


if __name__ == "__main__":
    main()
