import time
import ast
import json
import subprocess
from pathlib import Path


class MacroEngine:
    def __init__(self, config, sbc, ui=None, event_sink=None):
        self.sbc = sbc
        self.ui = ui
        self.event_sink = event_sink
        self.control_macros = config.get("control_macros", {})
        self.macros = config.get("macros", {})
        self.analog_zones = config.get("analog_zones", {})
        self.gear_zones = config.get("gear_zones", [])
        self.layer_cycle_button = config.get("layer_cycle_button", "LeftJoySightChange")
        self.output_mode = str(config.get("macro_output", "log")).lower()
        self.active_keys = set()
        self.axis_active = {}
        self.gear_active = None
        self.layer = 0
        self.vars = {}
        self.led_effects = {}
        self.persist_enabled = bool(config.get("persist_vars", False))
        self.persist_names = set(config.get("persist_var_names", []))
        self.persist_path = Path(config.get("persist_var_path", "macro_vars.json"))
        self.sound_enabled = bool(config.get("sound_enabled", True))
        self.sound_base_path = Path(config.get("sound_base_path", "sounds"))
        self.tts_enabled = bool(config.get("tts_enabled", True))
        self.tts_voice = config.get("tts_voice")
        self.event_log_path = Path(config.get("event_log_path", "sbc_events.log"))
        self.event_log_max_bytes = int(config.get("event_log_max_bytes", 131072))
        self.ui_device = None
        self.ecodes = None
        self._sound_backend = None
        self._tts_backend = None

        if self.output_mode in ("auto", "uinput"):
            try:
                from evdev import UInput, ecodes
            except Exception:
                if self.output_mode == "uinput":
                    raise
            else:
                self.ecodes = ecodes
                all_keys = self._collect_keys()
                if all_keys:
                    self.ui_device = UInput({ecodes.EV_KEY: all_keys}, name="sbc-macro")
                self.output_mode = "uinput"

        if self.ui_device is None:
            self.output_mode = "log"
        self._load_persisted_vars()
        self._init_sound()
        self._init_tts()

    def _collect_keys(self):
        keys = set()
        for macro in self.macros.values():
            for key in macro.get("keys", []):
                code = getattr(self.ecodes, key, None)
                if code is not None:
                    keys.add(code)
        return list(keys)

    def _emit(self, key_name, pressed):
        if self.output_mode == "uinput" and self.ui_device and self.ecodes:
            code = getattr(self.ecodes, key_name, None)
            if code is None:
                return
            self.ui_device.write(self.ecodes.EV_KEY, code, 1 if pressed else 0)
            self.ui_device.syn()
            self._publish_event({"type": "macro_key", "key": key_name, "state": "down" if pressed else "up"})
            return
        state = "DOWN" if pressed else "UP"
        if self.ui is not None:
            self.ui.set_status(f"MACRO {state}: {key_name}")
        else:
            print(f"MACRO {state}: {key_name}")
        self._publish_event({"type": "macro_key", "key": key_name, "state": "down" if pressed else "up"})

    def _press_keys(self, keys):
        for key in keys:
            if key not in self.active_keys:
                self._emit(key, True)
                self.active_keys.add(key)

    def _release_keys(self, keys):
        for key in keys:
            if key in self.active_keys:
                self._emit(key, False)
                self.active_keys.remove(key)

    def _resolve_macro(self, action_name):
        if action_name in self.macros:
            return self.macros[action_name]
        if action_name.startswith("KEY_"):
            return {"keys": [action_name], "press_ms": 20, "release_ms": 20}
        return None

    def _run_tap(self, macro, press_ms=None, release_ms=None):
        keys = macro.get("keys", [])
        if not keys:
            return
        press_delay = int(press_ms if press_ms is not None else macro.get("press_ms", 20))
        release_delay = int(release_ms if release_ms is not None else macro.get("release_ms", 20))
        self._press_keys(keys)
        time.sleep(press_delay / 1000.0)
        self._release_keys(keys)
        time.sleep(release_delay / 1000.0)

    def _run_hold_press(self, macro):
        keys = macro.get("keys", [])
        if keys:
            self._press_keys(keys)

    def _run_hold_release(self, macro):
        keys = macro.get("keys", [])
        if keys:
            self._release_keys(keys)

    def _behavior_from_led(self, led_name, default_led_mode):
        led_mode_raw = self.sbc.led_modes.get(led_name, default_led_mode)
        led_mode, _ = self.sbc._parse_led_mode(led_mode_raw)
        return "hold" if led_mode in ("flash", "momentary") else "tap"

    def handle_buttons(self, state, default_led_mode):
        for control_name, mapping in self.control_macros.items():
            if isinstance(mapping, str):
                action_name = mapping
                behavior = "from_led"
                press_ms = None
                release_ms = None
            elif isinstance(mapping, dict):
                action_name = mapping.get("action")
                behavior = mapping.get("behavior", "from_led")
                press_ms = mapping.get("press_ms")
                release_ms = mapping.get("release_ms")
            elif isinstance(mapping, list):
                index = self.layer % len(mapping) if mapping else 0
                action_name = mapping[index] if mapping else None
                behavior = "from_led"
                press_ms = None
                release_ms = None
            else:
                continue

            if not action_name:
                continue

            index = self.sbc.button_name_to_index.get(control_name)
            if index is None:
                continue

            pressed = self.sbc.get_button_state(index)
            changed = self.sbc.button_changed(index)

            led_name = self.sbc.button_to_led_name.get(index, control_name)
            if behavior == "from_led":
                behavior = self._behavior_from_led(led_name, default_led_mode)

            macro = self._resolve_macro(action_name)
            if macro is None:
                continue

            if isinstance(macro, list):
                if behavior == "tap":
                    if changed and pressed:
                        self._run_steps(macro, context="tap")
                elif behavior == "hold":
                    if changed and pressed:
                        self._run_steps(macro, context="down")
                    elif changed and not pressed:
                        self._run_steps(macro, context="up")
            else:
                if behavior == "tap":
                    if changed and pressed:
                        self._run_tap(macro, press_ms, release_ms)
                elif behavior == "hold":
                    if changed and pressed:
                        self._run_hold_press(macro)
                    elif changed and not pressed:
                        self._run_hold_release(macro)

    def handle_analogs(self, state):
        for axis_name, zones in self.analog_zones.items():
            value = state.get(axis_name)
            if value is None:
                continue

            current_action = None
            current_behavior = "hold"
            for zone in zones:
                min_val = zone.get("min")
                max_val = zone.get("max")
                if min_val is None or max_val is None:
                    continue
                if min_val <= value <= max_val:
                    current_action = zone.get("action")
                    current_behavior = zone.get("behavior", "hold")
                    break

            prev_action, prev_behavior = self.axis_active.get(axis_name, (None, "hold"))
            if current_action == prev_action:
                continue

            if prev_action:
                prev_macro = self._resolve_macro(prev_action)
                if prev_macro and prev_behavior == "hold":
                    self._run_hold_release(prev_macro)
                self._publish_event(
                    {
                        "type": "analog_zone",
                        "axis": axis_name,
                        "value": value,
                        "action": prev_action,
                        "behavior": prev_behavior,
                        "state": "exit",
                    }
                )

            if current_action:
                macro = self._resolve_macro(current_action)
                if macro:
                    if current_behavior == "tap":
                        self._run_tap(macro)
                    else:
                        self._run_hold_press(macro)
                self._publish_event(
                    {
                        "type": "analog_zone",
                        "axis": axis_name,
                        "value": value,
                        "action": current_action,
                        "behavior": current_behavior,
                        "state": "enter",
                    }
                )

            self.axis_active[axis_name] = (current_action, current_behavior)

    def handle_gears(self, state):
        gear_value = state.get("gear")
        if gear_value is None:
            return

        current_action = None
        current_behavior = "hold"
        for zone in self.gear_zones:
            values = zone.get("values")
            value = zone.get("value")
            if values is not None:
                if gear_value in values:
                    current_action = zone.get("action")
                    current_behavior = zone.get("behavior", "hold")
                    break
            elif value is not None:
                if gear_value == value:
                    current_action = zone.get("action")
                    current_behavior = zone.get("behavior", "hold")
                    break

        prev_action, prev_behavior = self.gear_active or (None, "hold")
        if current_action == prev_action:
            return

            if prev_action:
                prev_macro = self._resolve_macro(prev_action)
                if prev_macro and prev_behavior == "hold":
                    self._run_hold_release(prev_macro)
                self._publish_event(
                    {
                        "type": "gear_zone",
                        "gear": gear_value,
                        "action": prev_action,
                        "behavior": prev_behavior,
                        "state": "exit",
                    }
                )

            if current_action:
                macro = self._resolve_macro(current_action)
                if macro:
                    if current_behavior == "tap":
                        self._run_tap(macro)
                    else:
                        self._run_hold_press(macro)
                self._publish_event(
                    {
                        "type": "gear_zone",
                        "gear": gear_value,
                        "action": current_action,
                        "behavior": current_behavior,
                        "state": "enter",
                    }
                )

        self.gear_active = (current_action, current_behavior)

    def handle_layer_cycle(self):
        idx = self.sbc.button_name_to_index.get(self.layer_cycle_button)
        if idx is None:
            return
        if self.sbc.button_changed(idx) and self.sbc.get_button_state(idx):
            self.layer = (self.layer + 1) % max(1, self._max_layers())

    def _max_layers(self):
        max_len = 1
        for value in self.control_macros.values():
            if isinstance(value, list):
                max_len = max(max_len, len(value))
        return max_len

    def tick(self):
        now = time.monotonic()
        to_remove = []
        for led_name, effect in self.led_effects.items():
            duration = effect.get("duration_ms")
            if duration is not None and now - effect["start"] >= duration / 1000.0:
                to_remove.append(led_name)
                continue
            if effect["type"] == "blink":
                period = effect.get("period_ms", 500) / 1000.0
                on_ms = effect.get("on_ms", 250) / 1000.0
                phase = (now - effect["start"]) % period
                intensity = effect["intensity"] if phase <= on_ms else 0
            else:
                period = effect.get("period_ms", 2000) / 1000.0
                phase = (now - effect["start"]) % period
                cycle = (phase / period)
                tri = 1 - abs(2 * cycle - 1)
                intensity = int(effect["min"] + (effect["max"] - effect["min"]) * tri)
            self.sbc.set_led(self.sbc.led_name_to_id[led_name], intensity, send=False)
        if self.led_effects:
            self.sbc.write_leds()
        for name in to_remove:
            self.led_effects.pop(name, None)

    def _run_steps(self, steps, context="tap"):
        for step in steps:
            if "if" in step:
                expr = step.get("if", "")
                then = step.get("then", [])
                otherwise = step.get("else", [])
                if self._eval_expr(expr):
                    self._run_steps(then, context=context)
                else:
                    self._run_steps(otherwise, context=context)
                continue
            if "sleep_ms" in step:
                time.sleep(int(step["sleep_ms"]) / 1000.0)
                continue
            if "set_layer" in step:
                self.layer = int(step["set_layer"])
                continue
            if "cycle_layer" in step:
                self.layer = (self.layer + 1) % max(1, self._max_layers())
                continue
            if "set_var" in step:
                payload = step["set_var"]
                if isinstance(payload, dict):
                    self.vars[payload.get("name")] = payload.get("value")
                    self._save_persisted_vars()
                continue
            if "press" in step:
                payload = step["press"]
                key = payload.get("key")
                hold_ms = int(payload.get("hold_ms", 20))
                if key:
                    self._emit(key, True)
                    time.sleep(hold_ms / 1000.0)
                    self._emit(key, False)
                continue
            if "down" in step:
                key = step["down"]
                self._emit(key, True)
                continue
            if "up" in step:
                key = step["up"]
                self._emit(key, False)
                continue
            if "led_set" in step:
                payload = step["led_set"]
                led = payload.get("led")
                intensity = int(payload.get("intensity", 0))
                if led in self.sbc.led_name_to_id:
                    self.sbc.set_led(self.sbc.led_name_to_id[led], intensity, send=True)
                continue
            if "led_blink" in step:
                payload = step["led_blink"]
                led = payload.get("led")
                if led in self.sbc.led_name_to_id:
                    self.led_effects[led] = {
                        "type": "blink",
                        "start": time.monotonic(),
                        "duration_ms": payload.get("duration_ms"),
                        "period_ms": payload.get("period_ms", 500),
                        "on_ms": payload.get("on_ms", 250),
                        "intensity": int(payload.get("intensity", 15)),
                    }
                continue
            if "led_breathe" in step:
                payload = step["led_breathe"]
                led = payload.get("led")
                if led in self.sbc.led_name_to_id:
                    self.led_effects[led] = {
                        "type": "breathe",
                        "start": time.monotonic(),
                        "duration_ms": payload.get("duration_ms"),
                        "period_ms": payload.get("period_ms", 2000),
                        "min": int(payload.get("min", 0)),
                        "max": int(payload.get("max", 15)),
                    }
                continue
            if "sound_play" in step:
                payload = step["sound_play"]
                file_name = payload.get("file")
                if file_name:
                    self._sound_play(file_name)
                continue
            if "tts_say" in step:
                payload = step["tts_say"]
                text = payload.get("text")
                if text:
                    self._tts_say(self._format_text(text))
                continue

    def _eval_expr(self, expr):
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError:
            return False
        if not self._validate_expr_tree(tree.body):
            return False
        return self._eval_node(tree.body)

    def _eval_node(self, node):
        if isinstance(node, ast.BoolOp):
            vals = [self._eval_node(v) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(vals)
            if isinstance(node.op, ast.Or):
                return any(vals)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self._eval_node(node.operand)
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = self._eval_node(comp)
                if left is None or right is None:
                    return False
                if isinstance(op, ast.Eq) and not (left == right):
                    return False
                if isinstance(op, ast.NotEq) and not (left != right):
                    return False
                if isinstance(op, ast.Gt) and not (left > right):
                    return False
                if isinstance(op, ast.GtE) and not (left >= right):
                    return False
                if isinstance(op, ast.Lt) and not (left < right):
                    return False
                if isinstance(op, ast.LtE) and not (left <= right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Name):
            if node.id == "gear":
                return self.sbc.last_values.get("gear")
            if node.id == "tuner":
                return self.sbc.last_values.get("tuner")
            if node.id == "layer":
                return self.layer
            return self.vars.get(node.id)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            func = node.func.id
            args = [self._eval_node(a) for a in node.args]
            if func == "pressed" and args:
                return self.sbc.get_button_state(self.sbc.button_name_to_index.get(args[0], -1))
            if func == "toggle_on" and args:
                return self.sbc.get_button_state(self.sbc.button_name_to_index.get(args[0], -1))
            if func == "logical_on" and args:
                return self.sbc.get_logical_state(args[0])
            if func == "led_on" and args:
                led_id = self.sbc.led_name_to_id.get(args[0])
                return self.sbc.led_state.get(led_id, 0) > 0 if led_id is not None else False
            if func == "var" and args:
                return self.vars.get(args[0])
            if func == "analog" and args:
                return self.sbc.last_values.get(args[0])
            if func == "value" and args:
                return self.sbc.last_values.get(args[0])
            if func == "time_ms":
                return int(time.monotonic() * 1000)
            if func == "is_set" and args:
                return args[0] in self.vars and self.vars.get(args[0]) is not None
            if func == "is_none" and args:
                return self.vars.get(args[0]) is None
            if func == "num" and args:
                try:
                    return float(args[0])
                except (TypeError, ValueError):
                    return None
        return False

    def validate_macros(self):
        errors = []
        for name, macro in self.macros.items():
            if isinstance(macro, list):
                errors.extend(self._validate_steps(name, macro))
            elif isinstance(macro, dict):
                if "keys" not in macro:
                    errors.append(f"{name}: key macro missing 'keys'")
            else:
                errors.append(f"{name}: macro must be list or dict")
        return errors

    def reload_config(self, config):
        self.control_macros = config.get("control_macros", {})
        self.macros = config.get("macros", {})
        self.analog_zones = config.get("analog_zones", {})
        self.gear_zones = config.get("gear_zones", [])
        self.layer_cycle_button = config.get("layer_cycle_button", "LeftJoySightChange")
        self.layer = 0
        self.persist_enabled = bool(config.get("persist_vars", False))
        self.persist_names = set(config.get("persist_var_names", []))
        self.persist_path = Path(config.get("persist_var_path", "macro_vars.json"))
        self.sound_enabled = bool(config.get("sound_enabled", True))
        self.sound_base_path = Path(config.get("sound_base_path", "sounds"))
        self.tts_enabled = bool(config.get("tts_enabled", True))
        self.tts_voice = config.get("tts_voice")
        self.event_log_path = Path(config.get("event_log_path", "sbc_events.log"))
        self.event_log_max_bytes = int(config.get("event_log_max_bytes", 131072))
        self._load_persisted_vars()
        self._init_sound()
        self._init_tts()

    def reload_vars(self):
        self._load_persisted_vars()

    def clear_persisted_vars(self):
        if not self.persist_enabled or not self.persist_names:
            return
        for name in self.persist_names:
            self.vars.pop(name, None)
        try:
            if self.persist_path.exists():
                self.persist_path.unlink()
        except OSError:
            pass

    def _validate_steps(self, macro_name, steps):
        errors = []
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"{macro_name}[{idx}]: step must be object")
                continue
            allowed = {
                "if",
                "then",
                "else",
                "sleep_ms",
                "set_layer",
                "cycle_layer",
                "set_var",
                "press",
                "down",
                "up",
                "led_set",
                "led_blink",
                "led_breathe",
                "sound_play",
                "tts_say",
            }
            unknown = set(step.keys()) - allowed
            if unknown:
                errors.append(f"{macro_name}[{idx}]: unknown keys {sorted(unknown)}")
            if "if" in step:
                expr = step.get("if", "")
                if not self._validate_expr(expr):
                    errors.append(f"{macro_name}[{idx}]: invalid expr '{expr}'")
                then = step.get("then", [])
                otherwise = step.get("else", [])
                errors.extend(self._validate_steps(macro_name, then))
                errors.extend(self._validate_steps(macro_name, otherwise))
            if "press" in step and not isinstance(step["press"], dict):
                errors.append(f"{macro_name}[{idx}]: press must be object")
            if "led_set" in step and not isinstance(step["led_set"], dict):
                errors.append(f"{macro_name}[{idx}]: led_set must be object")
            if "led_blink" in step and not isinstance(step["led_blink"], dict):
                errors.append(f"{macro_name}[{idx}]: led_blink must be object")
            if "led_breathe" in step and not isinstance(step["led_breathe"], dict):
                errors.append(f"{macro_name}[{idx}]: led_breathe must be object")
            if "sound_play" in step and not isinstance(step["sound_play"], dict):
                errors.append(f"{macro_name}[{idx}]: sound_play must be object")
            if "tts_say" in step and not isinstance(step["tts_say"], dict):
                errors.append(f"{macro_name}[{idx}]: tts_say must be object")
        return errors

    def _validate_expr(self, expr):
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError:
            return False
        return self._validate_expr_tree(tree.body)

    def _validate_expr_tree(self, node):
        allowed_calls = {
            "pressed",
            "toggle_on",
            "logical_on",
            "led_on",
            "var",
            "analog",
            "value",
            "time_ms",
            "is_set",
            "is_none",
            "num",
        }
        if isinstance(node, ast.BoolOp):
            return all(self._validate_expr_tree(v) for v in node.values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self._validate_expr_tree(node.operand)
        if isinstance(node, ast.Compare):
            return self._validate_expr_tree(node.left) and all(self._validate_expr_tree(c) for c in node.comparators)
        if isinstance(node, ast.Name):
            return node.id in {"gear", "tuner", "layer"} or True
        if isinstance(node, ast.Constant):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in allowed_calls:
                return False
            return all(self._validate_expr_tree(a) for a in node.args)
        return False

    def _load_persisted_vars(self):
        if not self.persist_enabled or not self.persist_names:
            return
        if not self.persist_path.exists():
            return
        try:
            data = json.loads(self.persist_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for name in self.persist_names:
            if name in data:
                self.vars[name] = data[name]

    def _save_persisted_vars(self):
        if not self.persist_enabled or not self.persist_names:
            return
        payload = {name: self.vars.get(name) for name in self.persist_names}
        try:
            self.persist_path.write_text(json.dumps(payload, indent=2))
        except OSError:
            pass

    def run_macro(self, name):
        if not name:
            return
        macro = self._resolve_macro(name)
        if macro is None:
            return
        if isinstance(macro, list):
            self._run_steps(macro, context="tap")
        else:
            self._run_tap(macro)

    def _publish_event(self, payload):
        if self.event_sink is not None:
            try:
                self.event_sink.publish(payload)
            except Exception:
                pass

    def _format_text(self, text):
        if "{var:" not in text:
            return text
        out = text
        for key, value in self.vars.items():
            token = "{var:" + str(key) + "}"
            out = out.replace(token, "" if value is None else str(value))
        return out

    def _init_sound(self):
        if not self.sound_enabled:
            self._sound_backend = None
            return
        try:
            import pygame
        except Exception:
            self._sound_backend = None
            return
        try:
            pygame.mixer.init()
            self._sound_backend = pygame.mixer
        except Exception:
            self._sound_backend = None

    def _sound_play(self, file_name):
        if self._sound_backend is None:
            if self.ui is not None:
                self.ui.set_status("Sound backend unavailable")
            self._visual_fallback("Sound backend unavailable")
            self._log_event(f"sound_backend_unavailable:{file_name}")
            return
        path = Path(file_name)
        if not path.is_absolute():
            path = self.sound_base_path / file_name
        try:
            self._sound_backend.Sound(str(path)).play()
        except Exception:
            if self.ui is not None:
                self.ui.set_status(f"Sound error: {path}")
            self._visual_fallback(f"Sound error: {path}")
            self._log_event(f"sound_error:{path}")

    def _init_tts(self):
        if not self.tts_enabled:
            self._tts_backend = None
            return
        try:
            import pyttsx3
        except Exception:
            pyttsx3 = None
        if pyttsx3 is not None:
            try:
                engine = pyttsx3.init()
                if self.tts_voice:
                    engine.setProperty("voice", self.tts_voice)
                self._tts_backend = ("pyttsx3", engine)
                return
            except Exception:
                pass
        self._tts_backend = ("espeak", None)

    def _tts_say(self, text):
        if not self.tts_enabled:
            return
        if self._tts_backend is None:
            if self.ui is not None:
                self.ui.set_status("TTS backend unavailable")
            self._visual_fallback("TTS backend unavailable")
            self._log_event("tts_backend_unavailable")
            return
        backend, engine = self._tts_backend
        if backend == "pyttsx3":
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception:
                if self.ui is not None:
                    self.ui.set_status("TTS error")
                self._visual_fallback("TTS error")
                self._log_event("tts_error")
        else:
            cmd = ["espeak", text]
            if self.tts_voice:
                cmd = ["espeak", "-v", self.tts_voice, text]
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                if self.ui is not None:
                    self.ui.set_status("TTS error")
                self._visual_fallback("TTS error")
                self._log_event("tts_error")

    def _visual_fallback(self, message):
        if "Eject" in self.sbc.led_name_to_id:
            self.led_effects["Eject"] = {
                "type": "blink",
                "start": time.monotonic(),
                "duration_ms": 1500,
                "period_ms": 300,
                "on_ms": 150,
                "intensity": 15,
            }

    def _log_event(self, text):
        try:
            entry = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n"
            existing = b""
            if self.event_log_path.exists():
                existing = self.event_log_path.read_bytes()
            data = (existing + entry.encode("utf-8"))[-self.event_log_max_bytes :]
            self.event_log_path.write_bytes(data)
        except OSError:
            pass
