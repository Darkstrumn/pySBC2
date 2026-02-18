#!/usr/bin/python3
import signal
import threading
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbc_driver import SBCDriver

from process_services_common import MqttJsonClient, RuntimeContextLog, load_effective_config, resolve_topics


def main():
    effective = load_effective_config("sbc_config.json")
    mqtt_cfg = effective.get("mqtt", {})
    services_cfg = effective.get("services", {})
    audit_cfg = effective.get("audit", {})
    topics = resolve_topics(effective)
    base_topic = str(mqtt_cfg.get("base_topic", "sbc")).strip("/")
    log = RuntimeContextLog(str(audit_cfg.get("path", "runtime_context.log")))

    template = SBCDriver()
    mqtt = MqttJsonClient(mqtt_cfg, client_id="sbc-reader-service", log=log)

    state_lock = threading.Lock()
    latest_state = {"value": None}
    have_new_state = {"value": False}

    def _on_raw_state(payload, topic):
        state = (payload or {}).get("state")
        if not isinstance(state, dict):
            return
        with state_lock:
            latest_state["value"] = state
            have_new_state["value"] = True

    mqtt.subscribe(topics["io_raw_state"], _on_raw_state)
    mqtt.start()

    poll_ms = int(services_cfg.get("reader_poll_ms", effective.get("poll_interval_ms", 4)))
    if poll_ms < 1:
        poll_ms = 1

    stop_event = threading.Event()
    prev_buttons = None
    prev_gear = None
    prev_tuner = None

    def _stop_handler(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)

    log.write("sbc-reader-service", "started", {"poll_ms": poll_ms})
    try:
        while not stop_event.is_set():
            state = None
            with state_lock:
                if have_new_state["value"]:
                    state = latest_state["value"]
                    have_new_state["value"] = False
            if state is None:
                time.sleep(poll_ms / 1000.0)
                continue

            buttons = list(state.get("buttons", []))
            mqtt.publish(
                topics["event_raw_state"],
                {
                    "type": "raw_state",
                    "buttons": buttons,
                    "analogs": {
                        "aim_x": state.get("aim_x"),
                        "aim_y": state.get("aim_y"),
                        "rotation": state.get("rotation"),
                        "sight_x": state.get("sight_x"),
                        "sight_y": state.get("sight_y"),
                        "left_pedal": state.get("left_pedal"),
                        "middle_pedal": state.get("middle_pedal"),
                        "right_pedal": state.get("right_pedal"),
                    },
                    "tuner": state.get("tuner"),
                    "gear": state.get("gear"),
                    "timestamp_ms": int(time.time() * 1000),
                },
            )

            if prev_buttons is None:
                prev_buttons = [bool(v) for v in buttons]
            current_buttons = [bool(v) for v in buttons]
            for index, pressed in enumerate(current_buttons):
                old = prev_buttons[index] if index < len(prev_buttons) else False
                if old == pressed:
                    continue
                control_name = template.button_names[index] if index < len(template.button_names) else f"Button{index}"
                mqtt.publish(
                    topics["event_button"],
                    {
                        "type": "button",
                        "control": control_name,
                        "index": index,
                        "pressed": pressed,
                        "logical_state": pressed,
                        "source": "physical",
                        "timestamp_ms": int(time.time() * 1000),
                    },
                )
            prev_buttons = current_buttons

            gear = state.get("gear")
            if gear != prev_gear:
                mqtt.publish(
                    f"{base_topic}/events/gear_change",
                    {
                        "type": "gear_change",
                        "gear": gear,
                        "source": "physical",
                        "timestamp_ms": int(time.time() * 1000),
                    },
                )
                prev_gear = gear

            tuner = state.get("tuner")
            if tuner != prev_tuner:
                mqtt.publish(
                    f"{base_topic}/events/tuner_change",
                    {
                        "type": "tuner_change",
                        "tuner": tuner,
                        "source": "physical",
                        "timestamp_ms": int(time.time() * 1000),
                    },
                )
                prev_tuner = tuner

            time.sleep(poll_ms / 1000.0)
    finally:
        mqtt.stop()
        log.write("sbc-reader-service", "stopped", {})


if __name__ == "__main__":
    main()
