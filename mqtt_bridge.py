import json

"""
MQTT transport bridge for Node-RED integration.

Outbound:
- publish runtime events to `<base_topic>/events/<event_type>`

Inbound command topics:
- `<base_topic>/cmd/button` JSON { "control": "...", "pressed": true|false }
- `<base_topic>/cmd/macro`  JSON { "macro": "..." }
- `<base_topic>/cmd/led`    JSON { "led": "...", "mode": "...", ... }
- `<base_topic>/cmd/event`  JSON { "name": "...", "payload": {...} }
"""


class MqttBridge:
    """Optional MQTT event sink + command source for Node-RED."""

    def __init__(self, config=None, bus=None, audit_sink=None):
        cfg = config if isinstance(config, dict) else {}
        self.enabled = bool(cfg.get("enabled", False))
        self.host = str(cfg.get("host", "127.0.0.1"))
        self.port = int(cfg.get("port", 1883))
        self.keepalive = int(cfg.get("keepalive", 60))
        self.base_topic = str(cfg.get("base_topic", "sbc")).strip("/")
        self.username = str(cfg.get("username", "") or "")
        self.password = str(cfg.get("password", "") or "")
        self.publish_qos = int(cfg.get("publish_qos", 0))
        self.retain = bool(cfg.get("retain", False))
        self.audit_sink = audit_sink
        self.bus = bus
        self.connected = False
        self._client = None

        command_topics = cfg.get("command_topics", {})
        self.topic_button = self._topic(command_topics.get("button", "cmd/button"))
        self.topic_macro = self._topic(command_topics.get("macro", "cmd/macro"))
        self.topic_led = self._topic(command_topics.get("led", "cmd/led"))
        self.topic_event = self._topic(command_topics.get("event", "cmd/event"))

    def _topic(self, suffix):
        if suffix is None:
            suffix = ""
        suffix = str(suffix).strip("/")
        if not suffix:
            return self.base_topic
        return f"{self.base_topic}/{suffix}"

    def start(self):
        """Connect and subscribe to command topics if MQTT is enabled."""
        if not self.enabled:
            return False
        try:
            import paho.mqtt.client as mqtt
        except Exception:
            self._log("mqtt_unavailable", {"host": self.host, "port": self.port})
            return False

        try:
            client = mqtt.Client()
            if self.username:
                client.username_pw_set(self.username, self.password)
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            client.connect_async(self.host, self.port, self.keepalive)
            client.loop_start()
            self._client = client
            self._log("mqtt_starting", {"host": self.host, "port": self.port})
            return True
        except Exception:
            self._client = None
            self.connected = False
            self._log("mqtt_connect_failed", {"host": self.host, "port": self.port})
            return False

    def stop(self):
        """Stop MQTT network loop and disconnect cleanly."""
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        self.connected = False
        self._client = None
        self._log("mqtt_stopped", {})

    def publish(self, payload):
        """Publish runtime events for Node-RED consumption."""
        if self._client is None or not self.connected:
            return
        payload = dict(payload or {})
        event_type = str(payload.get("type", "event")).strip().lower() or "event"
        topic = self._topic(f"events/{event_type}")
        try:
            data = json.dumps(payload, separators=(",", ":"))
            self._client.publish(topic, data, qos=self.publish_qos, retain=self.retain)
        except Exception:
            self._log("mqtt_publish_failed", {"topic": topic, "event_type": event_type})

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self.connected = int(rc) == 0
        if not self.connected:
            self._log("mqtt_connect_error", {"code": int(rc)})
            return
        for topic in (self.topic_button, self.topic_macro, self.topic_led, self.topic_event):
            try:
                client.subscribe(topic, qos=self.publish_qos)
            except Exception:
                self._log("mqtt_subscribe_failed", {"topic": topic})
        self._log(
            "mqtt_connected",
            {
                "host": self.host,
                "port": self.port,
                "topics": [self.topic_button, self.topic_macro, self.topic_led, self.topic_event],
            },
        )

    def _on_disconnect(self, client, userdata, rc, properties=None):
        self.connected = False
        self._log("mqtt_disconnected", {"code": int(rc)})

    def _on_message(self, client, userdata, msg):
        if self.bus is None:
            return
        try:
            payload_text = msg.payload.decode("utf-8") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload)
            payload = json.loads(payload_text) if payload_text else {}
        except Exception:
            self._log("mqtt_bad_payload", {"topic": msg.topic})
            return

        topic = str(msg.topic)
        if topic == self.topic_button:
            self.bus.publish("command.button", payload)
            return
        if topic == self.topic_macro:
            self.bus.publish("command.macro", payload)
            return
        if topic == self.topic_led:
            self.bus.publish("command.led", payload)
            return
        if topic == self.topic_event:
            self.bus.publish("command.event", payload)

    def _log(self, event_type, payload):
        if self.audit_sink is None:
            return
        try:
            self.audit_sink.log(event_type, payload, service="mqtt")
        except Exception:
            pass
