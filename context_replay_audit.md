# Context Replay Audit

## Session: v1.0 Microservice Architecture Pivot

Date: 2026-02-17

### Intent
- Replace the monolithic SBC runtime loop with a microservice-like architecture.
- Keep physical controller behavior intact while decoupling responsibilities.
- Integrate Node-RED through MQTT publish/subscribe pathways.
- Add durable context logging so interrupted sessions can be resumed reliably.

### Implemented Direction
- Added polling-service runtime decomposition:
  - `ReaderService`
  - `WriterService`
  - `ModelService`
  - `MacroDispatchService`
  - `TelemetryService`
  - `UIService`
  - `ShutdownService`
- Added in-process event primitives:
  - `LocalEventBus`
  - `EventSinkFanout`
  - `CommandRouter`
- Added optional MQTT bridge (`mqtt_bridge.py`) for Node-RED command/event integration.
- Added runtime audit sink (`RuntimeAuditSink`) to persist append-only NDJSON context logs.
- Updated runtime entrypoint (`sbc-driver-test1.py`) to use service runtime in `read` mode.
- Expanded config defaults (`config_loader.py`) with:
  - `services`
  - `mqtt`
  - `audit`

### Operational Outcome
- Reader service publishes controller state into the runtime.
- Writer service owns LED output updates and supports external LED commands:
  - `off`, `steady`, `blink`, `breathe`, `pattern`, `clear`
- Model and macro logic continue to operate with current config/macro semantics.
- Node-RED can inject commands via MQTT topics and consume runtime events.
- Audit trail persists runtime context to `runtime_context.log` by default.

### Resume Notes
- Start from `sbc-driver-test1.py` `read` mode path for runtime orchestration.
- Adjust polling in `sbc_config.json` under `services`.
- Configure Node-RED broker settings under `mqtt`.
- Audit path and size controls are under `audit`.

## Session: Process-Isolated Services + Node-RED Flows

Date: 2026-02-17

### Intent
- Move from cooperative in-process services to true process-isolated executables.
- Keep all runtime coordination on MQTT topics only.
- Provide importable Node-RED flow files for button/macro/led command paths.

### Implemented Direction
- Added shared process runtime helpers in `process_services_common.py`.
- Added isolated service executables:
  - `services/sbc_io_service.py`
  - `services/sbc_reader_service.py`
  - `services/sbc_writer_service.py`
  - `services/sbc_macro_service.py`
  - `services/sbc_model_service.py`
- Added Node-RED import files:
  - `node_red/flows_sbc_commands.json`
  - `node_red/flows_sbc_event_bridge.json`
- Extended MQTT defaults for process topic routing:
  - `io_raw_topic`, `io_led_frame_topic`
  - `event_raw_topic`, `event_button_topic`, `event_vessel_topic`
  - `command_topics.led_frame`

### Operational Outcome
- Only `sbc_io_service.py` touches USB hardware.
- Reader, writer, macro, and model services are separate executables and exchange state/commands over MQTT.
- Writer owns animation behavior and emits LED frames to IO service.
- Macro/model automation can publish button/macro/event commands without direct process coupling.
- Node-RED can now import ready-made flow JSON files to publish/observe required command/event topics.

## Session: AI Copilot Service Scaffold

Date: 2026-02-17

### Intent
- Add a Heavy Gear-inspired "copilot in a box" service using TensorFlow-ready hooks.
- Keep all coordination MQTT-only and process-isolated.
- Provide Node-RED flow for AI mode control and guarded command routing.

### Implemented Direction
- Added `services/sbc_ai_copilot_service.py` with:
  - `advisory`, `assist`, `auto` runtime modes
  - heuristic intent/diagnostic fallback
  - optional TensorFlow/TFLite model inference path
  - confidence and cooldown-gated command publication
- Added MQTT topic defaults:
  - command: `cmd/ai_mode`
  - events: `events/ai_intent`, `events/ai_diagnostic`
- Added config section:
  - `ai_copilot` for thresholds, model settings, intent maps, and cue maps.
- Added Node-RED import flow:
  - `node_red/flows_sbc_ai_copilot.json`
- Updated service launch scripts/docs to include AI copilot process.

## Session: System Documentation + RPi Installer

Date: 2026-02-17

### Intent
- Add full documentation for macro system, AI copilot, and overall system operation.
- Summarize operating/install steps in main README.
- Provide fresh-install bootstrap script for Raspberry Pi controller core deployments.

### Implemented Direction
- Added full guide document:
  - `docs/SYSTEM_GUIDE.md`
- Reworked `README.md` into concise operator summary with:
  - required software/modules
  - runtime modes
  - Node-RED flow import references
  - key MQTT topics
  - pointer to full guide
- Added install bootstrap script:
  - `scripts/install_rpi.sh`
  - installs system deps, venv, Python modules, optional Node-RED, optional TensorFlow/TFLite
- Marked installer script executable in git index.
