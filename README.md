## SBC Controller Runtime (v1.0)

Python runtime for the Steel Battalion Controller, designed for Raspberry Pi as the on-device controller core.

Prerequisite for MQTT/process services:

- `pip install paho-mqtt`

### Architecture

The `read` runtime path is now decomposed into polling services:

- `ReaderService`: polls controller USB state.
- `WriterService`: owns LED output, gear effects, and LED animations (`off`, `steady`, `blink`, `breathe`, `pattern`).
- `ModelService`: applies vessel/application semantic modeling.
- `MacroDispatchService`: executes button/analog/gear macros and queued synthetic events.
- `TelemetryService`: publishes sampled raw state.
- `UIService`: updates console/pygame UI and touch input.
- `ShutdownService`: enforces the shutdown gesture.

### Event and Transport

- In-process event routing uses a local bus and input matrix.
- Outbound events can fan out to:
  - TCP NDJSON server (`net_server`)
  - MQTT bridge (`mqtt`) for Node-RED
  - runtime audit log sink (`audit`)

### Node-RED / MQTT Contract

Base topic default: `sbc`

Inbound command topics:
- `sbc/cmd/button` payload: `{ "control": "Start", "pressed": true }`
- `sbc/cmd/macro` payload: `{ "macro": "powerup" }`
- `sbc/cmd/led` payload example:
  - `{ "led": "Start", "mode": "steady", "intensity": 15 }`
  - `{ "led": "Start", "mode": "blink", "period_ms": 400, "on_ms": 200 }`
  - `{ "led": "Start", "mode": "breathe", "period_ms": 1800, "min": 0, "max": 15 }`
  - `{ "led": "Start", "mode": "pattern", "steps": [{ "intensity": 15, "duration_ms": 120 }, { "intensity": 0, "duration_ms": 120 }], "repeat": true }`
  - `{ "led": "Start", "mode": "clear" }`
- `sbc/cmd/event` payload: `{ "name": "custom_event", "payload": {...} }`

Outbound event topics:
- `sbc/events/<event_type>` where `event_type` is from runtime payloads (`raw_state`, `macro_key`, `vessel_snapshot`, etc).

### Runtime Context Audit

Runtime context is append-logged for replay/resume:
- config key: `audit.path` (default `runtime_context.log`)
- log format: NDJSON (one JSON object per line)
- configurable cap: `audit.max_bytes`

### Modes

- `python sbc-driver-test1.py read` (default): service runtime
- `python sbc-driver-test1.py led`: LED demo sequence
- `python sbc-driver-test1.py calibrate`: analog calibration helper

### Process-Isolated Services (MQTT-only)

For true process isolation, run each executable separately:

- `python services/sbc_io_service.py`
- `python services/sbc_reader_service.py`
- `python services/sbc_writer_service.py`
- `python services/sbc_macro_service.py`
- `python services/sbc_model_service.py`

Process topic pipeline:

- `sbc/io/raw_state` from `sbc_io_service.py`
- `sbc/events/raw_state` and `sbc/events/button` from `sbc_reader_service.py`
- `sbc/cmd/led` and `sbc/cmd/led_frame` consumed by `sbc_writer_service.py`
- `sbc/io/led_frame` produced by `sbc_writer_service.py` and consumed by `sbc_io_service.py`
- `sbc/cmd/macro` and `sbc/cmd/button` consumed by `sbc_macro_service.py`
- `sbc/events/vessel_snapshot` from `sbc_model_service.py`

All process services coordinate only through MQTT; no shared in-memory runtime is required.

### Node-RED Import Flows

Import files in the Node-RED editor (`Menu -> Import`):

- `node_red/flows_sbc_commands.json`
- `node_red/flows_sbc_event_bridge.json`
