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
