# SBC System Guide

This guide explains:

1. How the macro system works.
2. How the AI copilot works.
3. How the full system works together.
4. How to install and run on a fresh Raspberry Pi controller core.

## 1. Macro System

The macro system is implemented by `macro_engine.py` and is command-driven from `sbc_config.json`.

### 1.1 Core concepts

- `control_macros`: maps physical controls to actions.
- `macros`: action definitions.
- `analog_zones`: axis value ranges mapped to actions.
- `gear_zones`: gear positions mapped to actions.
- `layer_cycle_button`: cycles control layers.
- `persist_vars`: stores macro variables between runs.

### 1.2 Macro definition types

Macros support two forms:

1. Key macro (dictionary):
- Example:
  - `{ "keys": ["KEY_T"], "press_ms": 40, "release_ms": 40 }`
- Behavior:
  - Press all keys.
  - Wait `press_ms`.
  - Release all keys.
  - Wait `release_ms`.

2. Scripted macro (list of steps):
- Example:
  - `[ { "if": "gear == 5", "then": [ { "run_macro": "ELITE_HYPERSPACE" } ] } ]`
- Behavior:
  - Executes step-by-step logic with branching and side effects.

### 1.3 Control behavior modes

For mapped controls, behavior can be:

- `tap`: execute once on button-down.
- `hold`: execute on down/up edges.
- `from_led`: infer behavior from LED mode.

`from_led` mapping:
- LED modes `flash` and `momentary` => `hold`
- Other LED modes => `tap`

### 1.4 Script step vocabulary

Supported scripted keys in step objects:

- `if`, `then`, `else`
- `sleep_ms`
- `set_layer`
- `cycle_layer`
- `set_var`
- `run_macro`
- `press`
- `down`
- `up`
- `led_set`
- `led_blink`
- `led_breathe`
- `sound_play`
- `tts_say`
- `queue_button`
- `queue_macro`

### 1.5 Expression functions

Expressions in `if` support:

- `pressed("ControlName")`
- `toggle_on("ControlName")`
- `logical_on("ControlName")`
- `led_on("LedName")`
- `var("name")`
- `analog("axis_name")`
- `value("field_name")`
- `time_ms()`
- `is_set("name")`
- `is_none("name")`
- `num("123.4")`

Also supports boolean logic, comparison operators, and names like `gear`, `tuner`, `layer`.

### 1.6 Variables and persistence

- Macro variables live in `self.vars`.
- Optional persistence is controlled by:
  - `persist_vars`
  - `persist_var_names`
  - `persist_var_path`

### 1.7 Output modes

- `macro_output: log` (default): logs macro key transitions.
- `macro_output: uinput` or `auto`: emits real Linux input events via `evdev` when available.

## 2. AI Copilot

The AI copilot service is `services/sbc_ai_copilot_service.py`.

It acts as a "copilot in a box":

- Reads pilot/control state.
- Produces intent and diagnostics.
- Optionally emits guidance actions.

### 2.1 Inputs and outputs

Inputs:

- `sbc/events/raw_state`
- `sbc/events/vessel_snapshot`
- `sbc/cmd/ai_mode`

Outputs:

- `sbc/events/ai_intent`
- `sbc/events/ai_diagnostic`
- Optional:
  - `sbc/cmd/led`
  - `sbc/cmd/macro`

### 2.2 Operating modes

- `advisory`:
  - Publish AI intents and diagnostics only.
- `assist`:
  - Publish intents/diagnostics and LED cue commands.
- `auto`:
  - Publish intents/diagnostics and confidence-gated macro + LED commands.

### 2.3 Inference modes

Configured by `ai_copilot.model_type`:

- `heuristic` (default): rule-based intent/diagnostic scoring.
- `tensorflow` / `keras`: load Keras model from `ai_copilot.model_path`.
- `tflite`: use TensorFlow Lite interpreter.
- `auto`: attempt TensorFlow path then TFLite path.

If model loading fails, service falls back safely to heuristic behavior.

### 2.4 Safety and gating controls

Key controls in `ai_copilot` config:

- `confidence_threshold`
- `auto_macro_threshold`
- `diagnostic_threshold`
- `command_cooldown_ms`
- `emit_interval_ms`
- `intent_macro_map`
- `intent_led_map`

These enforce command throttling and prevent low-confidence automation.

## 3. End-to-End System

### 3.1 Process-isolated services

The preferred runtime is process-isolated and MQTT-only:

1. `services/sbc_io_service.py`
- Only process with direct USB hardware access.
- Publishes `sbc/io/raw_state`.
- Consumes `sbc/io/led_frame`.

2. `services/sbc_reader_service.py`
- Converts IO state to event topics.
- Publishes `sbc/events/raw_state` and `sbc/events/button`.

3. `services/sbc_writer_service.py`
- Owns LED behavior composition (steady/blink/breathe/pattern).
- Consumes `sbc/cmd/led` and `sbc/cmd/led_frame`.
- Publishes merged LED frame to `sbc/io/led_frame`.

4. `services/sbc_macro_service.py`
- Runs macro logic from control state and command topics.
- Consumes `sbc/events/raw_state`, `sbc/cmd/button`, `sbc/cmd/macro`.
- Emits macro events and LED frame updates.

5. `services/sbc_model_service.py`
- Maintains vessel/application semantic state.
- Consumes `sbc/events/button`.
- Publishes `sbc/events/vessel_snapshot`.

6. `services/sbc_ai_copilot_service.py`
- Reads runtime context and emits advisory or automation intents.

### 3.2 Node-RED role

Node-RED acts as orchestration and integration layer:

- Manual command injection.
- Rule-based automation.
- Bridging to external systems.
- Gating AI outputs for safety.

Importable flows:

- `node_red/flows_sbc_commands.json`
- `node_red/flows_sbc_event_bridge.json`
- `node_red/flows_sbc_ai_copilot.json`

### 3.3 Runtime logging and replay context

- `audit.path` controls append-only context log location.
- Default is `runtime_context.log`.
- Use this for post-failure reconstruction and audit replay.

## 4. Fresh Install on Raspberry Pi

Use:

- `scripts/install_rpi.sh`

This script installs:

- System packages:
  - Python, venv, build tools, USB libs, MQTT broker/client utilities.
- Python environment:
  - Core modules (`pyusb`, `paho-mqtt`, etc).
- Optional extras via flags:
  - Node-RED
  - AI TensorFlow
  - AI TensorFlow Lite

### 4.1 Typical install

From project root on Raspberry Pi:

```bash
chmod +x scripts/install_rpi.sh
./scripts/install_rpi.sh --with-node-red --with-tflite
```

### 4.2 Start services

```bash
source .venv/bin/activate
python services/sbc_io_service.py
python services/sbc_reader_service.py
python services/sbc_writer_service.py
python services/sbc_macro_service.py
python services/sbc_model_service.py
python services/sbc_ai_copilot_service.py
```

Or use PowerShell launcher on Windows host workflows:

```powershell
powershell -ExecutionPolicy Bypass -File services/start_process_services.ps1
```

## 5. Recommended Next Steps

1. Tune `ai_copilot.intent_macro_map` for your exact vehicle profile.
2. Keep default mode as `advisory` until confidence metrics stabilize.
3. Add per-vehicle config profiles and AI label maps.
4. Add scenario capture logs for offline model training and regression tests.
