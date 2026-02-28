## SBC Controller Runtime

Steel Battalion Controller runtime for Raspberry Pi "controller core" operation, with MQTT-based process services, macro automation, vessel modeling, and an AI copilot service.

Full technical guide:
- `docs/SYSTEM_GUIDE.md`

## What Is Included

- Macro system (`macro_engine.py`): control mappings, layered macros, scripted steps, variables, LED/audio/TTS actions.
- Process-isolated runtime services (`services/*.py`) with MQTT-only coordination.
- AI copilot service (`services/sbc_ai_copilot_service.py`) with heuristic mode and optional TensorFlow/TFLite inference.
- Node-RED import flows (`node_red/*.json`) for command, event, and AI orchestration.

## Fresh Install (Raspberry Pi)

Use the installer script from project root:

```bash
chmod +x scripts/install_rpi.sh
./scripts/install_rpi.sh --with-node-red --with-tflite
```

Installer script:
- `scripts/install_rpi.sh`

Options:
- `--with-node-red`
- `--with-tensorflow`
- `--with-tflite`
- `--no-audio`

## Required Software

Core:
- Python 3 with venv support
- MQTT broker (Mosquitto recommended)
- Python modules:
  - `pyusb`
  - `paho-mqtt`
  - `evdev`

Optional:
- Node-RED (for orchestration/dashboard/automation)
- `pygame` and `pyttsx3` (macro audio/TTS features)
- `tensorflow` or `tflite-runtime` + `numpy` (AI model inference)

## Runtime Modes

Legacy single-process runtime:
- `python sbc-driver-test1.py read`
- `python sbc-driver-test1.py led`
- `python sbc-driver-test1.py calibrate`

Recommended process-isolated runtime:
- `python services/sbc_io_service.py`
- `python services/sbc_reader_service.py`
- `python services/sbc_writer_service.py`
- `python services/sbc_macro_service.py`
- `python services/sbc_model_service.py`
- `python services/sbc_ai_copilot_service.py`

Windows helper launcher:
- `powershell -ExecutionPolicy Bypass -File services/start_process_services.ps1`

## Node-RED Flows

Import these files in Node-RED:
- `node_red/flows_sbc_commands.json`
- `node_red/flows_sbc_event_bridge.json`
- `node_red/flows_sbc_ai_copilot.json`

## Key MQTT Topics (default base `sbc`)

Commands:
- `sbc/cmd/button`
- `sbc/cmd/macro`
- `sbc/cmd/led`
- `sbc/cmd/event`
- `sbc/cmd/ai_mode`

Events:
- `sbc/events/raw_state`
- `sbc/events/button`
- `sbc/events/vessel_snapshot`
- `sbc/events/ai_intent`
- `sbc/events/ai_diagnostic`

IO bridge:
- `sbc/io/raw_state`
- `sbc/io/led_frame`

## Configuration

Primary config:
- `sbc_config.json`

Important sections:
- `services`
- `mqtt`
- `ai_copilot`
- `vessel_model`
- `control_macros`, `macros`, `analog_zones`, `gear_zones`
- `audit`

For full behavior details and examples:
- `docs/SYSTEM_GUIDE.md`
