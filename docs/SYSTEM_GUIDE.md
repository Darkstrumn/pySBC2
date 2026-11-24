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

### Auxiliary control surfaces

In the Python read runtime, **Start** enables the Microsoft Game Voice
(`045e:003b`) and **Ignition** enables the Nostromo n52
(`050d:0815`). The runtime grabs their evdev nodes, including the n52 keypad
and wheel, so auxiliary input stays inside the controller runtime. The running
user needs permission to read and grab those input nodes. The SBC and the
auxiliary devices can start independently, and reconnects are detected during
normal operation.

The active profile's `aux_surface_switches` maps `game_voice` and
`nostromo_n52` to SBC control names. Set a mapping to JSON `null` to leave the
surface disengaged, or select a physical toggle switch to remap its gate.

Enabled input is available as `aux_input` events on the existing event sinks,
including `sbc/events/aux_input` when MQTT is enabled with its default topic
prefix. Each event includes the surface, event type (`key` or `relative`),
numeric evdev code, and value. Assign named local macros under
`aux_key_macros.<surface>.<evdev-code>` to run them on key-down. Relative
events are available to downstream mappings. The bundled default profile includes the Elite layout below.

### Elite Dangerous / Horizons N52 layout

These inputs refer to the Linux key codes reported by the keypad. Verify the
emitted codes if your n52 has been remapped. The two former switch outputs are
preserved on the keypad. Bind F16 and F17 in Elite to use the suggested actions.

| N52 input | Elite action | Host key |
| --- | --- | --- |
| 02 / Q | Cargo Scoop (former Buffer Material output) | F16 |
| 04 / E | Ship Lights (former VT Location output) | F17 |
| 05 / R | Landing Gear | L |
| 10 / F | Hardpoints | U |
| 07 / A | Target Ahead | T |
| 12 / Z | Frame Shift Drive | J |

Match the host keys to your Elite bindings. In the default `macro_output: log`
mode, macro key events are available through the existing event sinks. A host
subscriber must turn them into host key input when Elite runs on another machine.

Use `python3 sbc-driver-test1.py --ui=pygame` on the Pi display. Tap **Settings**
then **Auxiliary controls** to edit the switch assignments and key bindings.

Layout references: [Belkin n52 manual](https://cache-www.belkin.com/support/dl/f8gpc100_man.pdf), [Steel Battalion in Elite](https://www.reddit.com/r/EliteDangerous/comments/g11em9), and [ITBSBC](https://github.com/kgmonteith/ITBSBC). The Elite action choices above are project defaults.


The graphical MFD discovers direct evdev touchscreens automatically when
`touch_device` is empty. Set `touch_device` to the desired input node if the Pi
has multiple touchscreens. The runtime scales the absolute axes to the display
and activates the visible target on release. The Pi user needs permission to
read and grab the touchscreen node. SDL finger events are also supported when
SDL provides them.

By default, Ignition enables the Nostromo N52 and Start enables GameVoice.
The gates follow the committed power state through LED animations.
In **Settings → Auxiliary controls**, use **Switches**, **Nostromo N52**,
or **GameVoice**. Use
**Next** and **Previous** to browse the bindings and tap a row to cycle its
macro. The N52 includes the wheel click and both scroll directions. Each scroll
event can invoke one macro for its direction. GameVoice lists the buttons
reported by the device when you open its tab. Its **Unmapped buttons** row
controls the fallback macro, and a button explicitly set to **Unassigned**
suppresses that fallback. Tap **Save & Apply** to persist the profile edits.

### HTML MFD and hold-to-confirm buttons

Run the Pygame MFD from the Pi's physical console with the framebuffer
settings that worked in the SDL 1.2 display test. For an SDL build that
provides the `fbcon` driver, use:

```sh
SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 python3 sbc-driver-test1.py --ui=pygame
```

Edit `mfd/panel.html` and restart the app to update the screen layout. Pygame
draws the panel directly on its SDL display. The layout uses well-formed HTML
with `header` and `section id` pages, `div data-rect="x,y,w,h"` panels,
`span data-pos="x,y"` labels, and `button data-rect data-action` touch
targets. Labels can bind to runtime values through `data-value`. Dynamic
widgets and page actions are registered in Python. The renderer supports
this subset of HTML, with styles defined by the Pygame theme.

Main shows live LED brightness and marks physically held buttons and active
switches. The old dashboard is under **Settings → Diagnostics**. Settings also
opens button setup, a macro JSON editor with a touch keyboard, themes and
profiles, About, and Help. About shows the local Git tag or revision when
available, runtime versions, display driver, and touch input source. Restart
the runtime if a profile changes startup-only settings such as the output backend.

The Elite and Horizons starter profiles copy the bundled Elite mappings.
Star Citizen, EVE Online, MechWarrior, OBS, and Kerbal Space Program starters
copy the hardware settings and provide themed profiles ready for custom bindings.

Tank Detach defaults to a 1200 ms hold. It flashes while held, fades on an
early release, and on confirmation gives three fast flashes followed by two
flash periods solid and then off. The configured action starts with the
confirmation sequence. Set a named macro or `KEY_*` action in Button setup
to enable host output. A zero confirmation duration restores normal dispatch.

#### Button presets and ship power

**Button setup** offers Momentary (lit while pressed), Latched Toggle (press
to switch on or off), Momentary Flash (blinks while pressed), Mutually
Exclusive Group (one active member), Selective Interlock (the selected
control excludes all listed peers, which can coexist with one another),
and Hold to Confirm (defaults to 1200 ms with blink, abort fade, and
confirmation flashes). Enter LED names separated by commas for linked
presets. For example, Selective Interlock on F1 with F2 and F3 allows F2
and F3 together. Presets do not supply a game binding. Tank Detach is an
example of Hold to Confirm and can be assigned the command of your choice.

Startup walks through cockpit, switch, ignition, and drive checks. After
startup, hold Ignition to enter Standby and stop the drives. With all
five switches on, hold Ignition again to turn it Off. A short press from
Off or Standby restores it to On once the switch checklist passes. With
Ignition On, tap Start to engage the drives and hold Start to disengage.
A short press of either active control shows abort feedback and keeps its
power state. The MFD describes any blocked operation. Physical LEDs
settle to the current power state after feedback.

A configured Ignition or Start action fires on a committed transition.
Stopping the drives by moving Ignition to Standby also invokes the
configured Start action. The built-in states gate inputs locally and
publish vessel state. Bind or route game-specific actions separately.
