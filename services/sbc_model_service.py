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

from process_services_common import (
    MqttEventSink,
    MqttInputMatrix,
    MqttJsonClient,
    RuntimeContextLog,
    load_effective_config,
    resolve_topics,
)
from vessel_models import build_vessel_model


def main():
    effective = load_effective_config("sbc_config.json")
    mqtt_cfg = effective.get("mqtt", {})
    services_cfg = effective.get("services", {})
    audit_cfg = effective.get("audit", {})
    topics = resolve_topics(effective)
    base_topic = str(mqtt_cfg.get("base_topic", "sbc")).strip("/")
    log = RuntimeContextLog(str(audit_cfg.get("path", "runtime_context.log")))

    mqtt = MqttJsonClient(mqtt_cfg, client_id="sbc-model-service", log=log)
    event_sink = MqttEventSink(mqtt, base_topic=base_topic)
    input_matrix = MqttInputMatrix(mqtt, topics)
    vessel_model = build_vessel_model(effective, input_matrix=input_matrix, event_sink=event_sink)

    button_queue = deque(maxlen=512)
    queue_lock = threading.Lock()

    def _on_button(payload, topic):
        with queue_lock:
            button_queue.append(dict(payload or {}))

    mqtt.subscribe(topics["event_button"], _on_button)
    mqtt.start()

    poll_ms = int(services_cfg.get("model_poll_ms", effective.get("poll_interval_ms", 4)))
    if poll_ms < 1:
        poll_ms = 1
    snapshot_ms = int(services_cfg.get("model_snapshot_ms", 250))
    if snapshot_ms < 1:
        snapshot_ms = 250
    next_snapshot = time.monotonic()

    stop_event = threading.Event()

    def _stop_handler(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)

    vessel_model.on_boot_complete()
    log.write("sbc-model-service", "started", {"poll_ms": poll_ms, "snapshot_ms": snapshot_ms})

    try:
        while not stop_event.is_set():
            queued = []
            with queue_lock:
                while button_queue:
                    queued.append(button_queue.popleft())

            for event in queued:
                vessel_model.on_control_change(
                    event.get("control"),
                    bool(event.get("pressed")),
                    logical_state=event.get("logical_state"),
                )
            vessel_model.tick()

            now = time.monotonic()
            if now >= next_snapshot:
                mqtt.publish(
                    topics["event_vessel_snapshot"],
                    {
                        "type": "vessel_snapshot",
                        "snapshot": vessel_model.snapshot(),
                        "timestamp_ms": int(time.time() * 1000),
                    },
                )
                next_snapshot = now + (snapshot_ms / 1000.0)

            time.sleep(poll_ms / 1000.0)
    finally:
        mqtt.stop()
        log.write("sbc-model-service", "stopped", {})


if __name__ == "__main__":
    main()
