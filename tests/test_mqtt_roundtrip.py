"""Integration check with an isolated MQTT broker and the actual Node-RED flow."""

import asyncio
import json
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

from amqtt.broker import Broker
import paho.mqtt.client as mqtt

from input_matrix import InputMatrix
from mqtt_bridge import MqttBridge
from service_runtime import CommandRouter, EventSinkFanout, LocalEventBus, MacroDispatchService, ReaderService


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.025)
    raise AssertionError("Timed out waiting for the MQTT round trip")


class ControllerStub:
    button_names = ["Comm1"]
    logical_state = {"Comm1": True}

    def read_raw(self):
        return b"sample"

    def parse_state(self, data):
        return {"buttons": [True]}

    def button_changed(self, index):
        return True

    def get_button_state(self, index):
        return True

    def get_logical_state(self, control):
        return self.logical_state[control]


class MacroRecorder:
    def __init__(self):
        self.actions = []

    def handle_analogs(self, state):
        pass

    def handle_gears(self, state):
        pass

    def run_macro(self, name):
        self.actions.append(name)


class MqttRoundTrip(unittest.IsolatedAsyncioTestCase):
    async def test_controller_node_red_and_host(self):
        executable = os.environ.get("NODE_RED") or shutil.which("node-red")
        self.assertTrue(executable, "Install Node-RED or set NODE_RED to its executable")
        port = free_port()
        broker = Broker({"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
                         "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}}})
        await broker.start()
        try:
            await asyncio.to_thread(self.check_round_trip, executable, port)
        finally:
            await broker.shutdown()

    def check_round_trip(self, executable, port):
        bus = LocalEventBus()
        bridge = MqttBridge({"enabled": True, "port": port, "publish_qos": 1, "retain": True}, bus)
        matrix = InputMatrix()
        recorder = MacroRecorder()
        CommandRouter(bus, matrix)
        dispatcher = MacroDispatchService(recorder, matrix, "toggle", lambda: {"buttons": [True]}, 1)
        received = Queue()
        host = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        host.on_connect = lambda client, *_: client.subscribe([("sbc/host/control/#", 1), ("sbc/events/#", 1)])
        host.on_message = lambda _, __, msg: received.put(msg)
        source = Path(__file__).resolve().parents[1] / "node_red" / "flows_sbc_event_bridge.json"
        flow = json.loads(source.read_text())
        for node in flow:
            if node["type"] == "mqtt-broker":
                node["port"] = str(port)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            flow_path = folder / "flows.json"
            flow_path.write_text(json.dumps(flow))
            with (folder / "node-red.log").open("w+") as log:
                process = subprocess.Popen(
                    [executable, "--userDir", directory, "--port", str(free_port()), str(flow_path)],
                    stdout=log, stderr=subprocess.STDOUT,
                )
                fanout = EventSinkFanout([bridge])
                try:
                    meta = {"type": "meta", "button_names": ["Comm1"]}
                    bridge.publish(meta)  # Startup metadata can arrive before MQTT connects.
                    self.assertTrue(bridge.start())
                    host.connect("127.0.0.1", port)
                    host.loop_start()
                    self.await_message(received, "sbc/host/control/meta", meta)
                    fanout.start()
                    reader = ReaderService(ControllerStub(), 1, event_sink=fanout)
                    reader.tick(time.monotonic())
                    self.await_message(received, "sbc/host/control/button",
                                       {"control": "Comm1", "pressed": True, "logical_state": True})
                    key = {"type": "macro_key", "key": "KEY_A", "state": "down"}
                    fanout.publish(key)
                    self.await_message(received, "sbc/host/control/macro_key", key)
                    feedback = {"command": "macro", "payload": {"macro": "smoke_test"}}
                    host.publish("sbc/host/feedback", json.dumps(feedback), qos=1).wait_for_publish(3)
                    wait_for(lambda: len(matrix) > 0)
                    dispatcher.tick(time.monotonic())
                    self.assertEqual(recorder.actions, ["smoke_test"])
                except AssertionError as exc:
                    log.seek(0)
                    raise AssertionError(f"{exc}\n{log.read()}") from exc
                finally:
                    fanout.stop()
                    host.disconnect()
                    host.loop_stop()
                    bridge.stop()
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()

    def await_message(self, received, topic, fields):
        def match():
            try:
                msg = received.get_nowait()
            except Empty:
                return False
            payload = json.loads(msg.payload)
            return msg.topic == topic and all(payload.get(key) == value for key, value in fields.items())

        wait_for(match)
