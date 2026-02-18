import json
import threading
import time
from pathlib import Path

from config_loader import load_config


def build_effective_config(config):
    """Merge root config with active profile overrides."""
    active_profile = str(config.get("active_profile", "default"))
    profile_data = {}
    if isinstance(config.get("profiles"), dict):
        profile_data = config["profiles"].get(active_profile, {})
    effective = dict(config)
    if isinstance(profile_data, dict):
        effective.update(profile_data)
    return effective


def load_effective_config(path="sbc_config.json"):
    return build_effective_config(load_config(path))


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return bool(default)
    return bool(value)


def resolve_topics(effective):
    """Resolve all process-service topics from mqtt config."""
    mqtt_cfg = effective.get("mqtt", {}) if isinstance(effective, dict) else {}
    base_topic = str(mqtt_cfg.get("base_topic", "sbc")).strip("/")
    command_topics = mqtt_cfg.get("command_topics", {}) if isinstance(mqtt_cfg.get("command_topics"), dict) else {}

    def _topic(suffix, fallback):
        raw = str(suffix if suffix is not None else fallback).strip("/")
        if not raw:
            return base_topic
        return f"{base_topic}/{raw}"

    return {
        "cmd_button": _topic(command_topics.get("button"), "cmd/button"),
        "cmd_macro": _topic(command_topics.get("macro"), "cmd/macro"),
        "cmd_led": _topic(command_topics.get("led"), "cmd/led"),
        "cmd_event": _topic(command_topics.get("event"), "cmd/event"),
        "cmd_led_frame": _topic(command_topics.get("led_frame"), "cmd/led_frame"),
        "io_raw_state": _topic(mqtt_cfg.get("io_raw_topic"), "io/raw_state"),
        "io_led_frame": _topic(mqtt_cfg.get("io_led_frame_topic"), "io/led_frame"),
        "event_raw_state": _topic(mqtt_cfg.get("event_raw_topic"), "events/raw_state"),
        "event_button": _topic(mqtt_cfg.get("event_button_topic"), "events/button"),
        "event_vessel_snapshot": _topic(mqtt_cfg.get("event_vessel_topic"), "events/vessel_snapshot"),
    }


class RuntimeContextLog:
    """Small append-only text log for process services."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, service, message, payload=None):
        record = {
            "timestamp_ms": int(time.time() * 1000),
            "service": str(service),
            "message": str(message),
            "payload": payload,
        }
        line = json.dumps(record, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            except OSError:
                pass


class MqttJsonClient:
    """Threaded MQTT client with JSON decode/dispatch helpers."""

    def __init__(self, mqtt_cfg, client_id, log=None):
        self.mqtt_cfg = dict(mqtt_cfg or {})
        self.client_id = str(client_id)
        self.log = log
        self.host = str(self.mqtt_cfg.get("host", "127.0.0.1"))
        self.port = _safe_int(self.mqtt_cfg.get("port", 1883), 1883)
        self.keepalive = _safe_int(self.mqtt_cfg.get("keepalive", 60), 60)
        self.username = str(self.mqtt_cfg.get("username", "") or "")
        self.password = str(self.mqtt_cfg.get("password", "") or "")
        self.publish_qos = _safe_int(self.mqtt_cfg.get("publish_qos", 0), 0)
        self.retain_default = _safe_bool(self.mqtt_cfg.get("retain", False), False)
        self.connected = False
        self._client = None
        self._lock = threading.Lock()
        self._subscriptions = []
        self._topic_matcher = None

    def start(self):
        try:
            import paho.mqtt.client as mqtt
        except Exception:
            self._log("mqtt_unavailable", {"host": self.host, "port": self.port})
            return False
        try:
            self._topic_matcher = getattr(mqtt, "topic_matches_sub", None)
            client = mqtt.Client(client_id=self.client_id)
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

    def subscribe(self, topic_filter, handler):
        topic_filter = str(topic_filter)
        with self._lock:
            self._subscriptions.append((topic_filter, handler))
        if self._client is not None and self.connected:
            try:
                self._client.subscribe(topic_filter, qos=self.publish_qos)
            except Exception:
                self._log("mqtt_subscribe_failed", {"topic": topic_filter})

    def publish(self, topic, payload, qos=None, retain=None):
        if self._client is None:
            return
        try:
            data = json.dumps(payload, separators=(",", ":"))
        except Exception:
            data = "{}"
        use_qos = self.publish_qos if qos is None else _safe_int(qos, self.publish_qos)
        use_retain = self.retain_default if retain is None else _safe_bool(retain, self.retain_default)
        try:
            self._client.publish(str(topic), data, qos=use_qos, retain=use_retain)
        except Exception:
            self._log("mqtt_publish_failed", {"topic": str(topic)})

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self.connected = int(rc) == 0
        if not self.connected:
            self._log("mqtt_connect_error", {"code": int(rc)})
            return
        with self._lock:
            subscriptions = list(self._subscriptions)
        for topic_filter, _ in subscriptions:
            try:
                client.subscribe(topic_filter, qos=self.publish_qos)
            except Exception:
                self._log("mqtt_subscribe_failed", {"topic": topic_filter})
        self._log("mqtt_connected", {"host": self.host, "port": self.port, "subscriptions": [t for t, _ in subscriptions]})

    def _on_disconnect(self, client, userdata, rc, properties=None):
        self.connected = False
        self._log("mqtt_disconnected", {"code": int(rc)})

    def _on_message(self, client, userdata, msg):
        try:
            payload_text = msg.payload.decode("utf-8") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload)
            payload = json.loads(payload_text) if payload_text else {}
        except Exception:
            self._log("mqtt_bad_payload", {"topic": str(msg.topic)})
            return
        with self._lock:
            subscriptions = list(self._subscriptions)
        for topic_filter, handler in subscriptions:
            if not self._match(topic_filter, msg.topic):
                continue
            try:
                handler(payload, str(msg.topic))
            except Exception:
                self._log("mqtt_handler_error", {"topic": str(msg.topic), "filter": topic_filter})

    def _match(self, topic_filter, topic):
        if self._topic_matcher is not None:
            try:
                return bool(self._topic_matcher(topic_filter, topic))
            except Exception:
                return str(topic_filter) == str(topic)
        return str(topic_filter) == str(topic)

    def _log(self, message, payload):
        if self.log is None:
            return
        self.log.write(self.client_id, message, payload)


class MqttEventSink:
    """Event sink adapter that publishes payloads to `events/<type>` topics."""

    def __init__(self, mqtt_client, base_topic):
        self.mqtt = mqtt_client
        self.base_topic = str(base_topic).strip("/")

    def publish(self, payload):
        payload = dict(payload or {})
        event_type = str(payload.get("type", "event")).strip().lower() or "event"
        topic = f"{self.base_topic}/events/{event_type}"
        self.mqtt.publish(topic, payload)


class MqttInputMatrix:
    """InputMatrix-like adapter that emits queued requests as MQTT commands."""

    def __init__(self, mqtt_client, topics):
        self.mqtt = mqtt_client
        self.topics = dict(topics or {})

    def queue_button(self, control_name, pressed, source="automation", payload=None):
        if not control_name:
            return
        msg = {
            "control": str(control_name),
            "pressed": bool(pressed),
            "source": str(source),
            "payload": payload or {},
        }
        self.mqtt.publish(self.topics["cmd_button"], msg)

    def queue_macro(self, macro_name, source="automation", payload=None):
        if not macro_name:
            return
        msg = {
            "macro": str(macro_name),
            "source": str(source),
            "payload": payload or {},
        }
        self.mqtt.publish(self.topics["cmd_macro"], msg)

    def queue_event(self, event_name, source="automation", payload=None):
        if not event_name:
            return
        msg = {
            "name": str(event_name),
            "source": str(source),
            "payload": payload or {},
        }
        self.mqtt.publish(self.topics["cmd_event"], msg)
