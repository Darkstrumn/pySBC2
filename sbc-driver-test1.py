#!/usr/bin/python3
import sys
import time

from calibration import calibrate_axes
from config_loader import load_config, build_default_led_modes
from macro_engine import MacroEngine
from sbc_driver import SBCDriver
from ui_factory import init_ui
from touch_input import TouchInput
from gear_effects import GearEffectController
from network_server import NetworkEventServer


def parse_args(argv):
    mode = "read"
    ui_mode = "console"
    args = argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--ui="):
            ui_mode = arg.split("=", 1)[1].strip().lower()
        elif arg == "--ui" and i + 1 < len(args):
            ui_mode = args[i + 1].strip().lower()
            i += 1
        elif not arg.startswith("-"):
            mode = arg.lower()
        i += 1
    return mode, ui_mode


def apply_config(sbc, effective):
    sbc.FLASH_PERIOD_S = float(effective["flash_period_s"])
    sbc.TIME_BETWEEN_POLLS_MS = int(effective["poll_interval_ms"])
    sbc.set_gear_lights(effective["update_gear_lights"], effective["gear_light_intensity"])
    sbc.GEAR_REVERSE_FLASH = bool(effective["gear_reverse_flash"])
    if isinstance(effective.get("analog"), dict):
        sbc.set_analog_config(effective["analog"])
    led_mode = str(effective["led_mode"]).lower()
    led_modes = build_default_led_modes(sbc.led_name_to_id)
    if isinstance(effective.get("led_modes"), dict):
        for key, value in effective["led_modes"].items():
            key_norm = str(key).strip().lower()
            for name in sbc.led_name_to_id.keys():
                if name.lower() == key_norm:
                    led_modes[name] = str(value).strip()
                    break
    sbc.set_led_modes(led_modes)
    return led_mode


def build_effective_config(config):
    active_profile = str(config.get("active_profile", "default"))
    profile_data = {}
    if isinstance(config.get("profiles"), dict):
        profile_data = config["profiles"].get(active_profile, {})
    effective = dict(config)
    if isinstance(profile_data, dict):
        effective.update(profile_data)
    return effective


def main():
    mode, ui_mode = parse_args(sys.argv)
    config = load_config("sbc_config.json")
    effective = build_effective_config(config)

    sbc = SBCDriver()
    led_mode = apply_config(sbc, effective)
    sbc.open()

    def reload_callback(vars_only=False, clear_vars=False):
        nonlocal led_mode
        if clear_vars:
            macro_engine.clear_persisted_vars()
            return
        if vars_only:
            macro_engine.reload_vars()
            return
        cfg = load_config("sbc_config.json")
        eff = build_effective_config(cfg)
        led_mode = apply_config(sbc, eff)
        macro_engine.reload_config(eff)
        if ui is not None:
            ui.config_root = cfg
            ui.config_view = eff

    ui = init_ui(ui_mode, sbc, effective, config, "sbc_config.json", reload_callback=reload_callback)
    sbc.ui = ui
    net_config = effective.get("net_server", {})
    event_server = None
    if isinstance(net_config, dict) and net_config.get("enabled"):
        event_server = NetworkEventServer(
            host=str(net_config.get("host", "0.0.0.0")),
            port=int(net_config.get("port", 8765)),
        )
        event_server.start()
        event_server.publish(
            {
                "type": "meta",
                "button_names": sbc.button_names,
                "analog_names": [
                    "aim_x",
                    "aim_y",
                    "rotation",
                    "sight_x",
                    "sight_y",
                    "left_pedal",
                    "middle_pedal",
                    "right_pedal",
                ],
                "tuner_name": "tuner",
                "gear_name": "gear",
            }
        )
    macro_engine = MacroEngine(effective, sbc, ui=ui, event_sink=event_server)
    gear_effects = GearEffectController(sbc, macro_engine, effective)
    touch = None
    if effective.get("touch_device"):
        touch = TouchInput(
            effective.get("touch_device"),
            int(effective.get("touch_width", 800)),
            int(effective.get("touch_height", 480)),
        )
    errors = macro_engine.validate_macros()
    if errors:
        message = f"Macro errors: {errors[0]}"
        if ui is not None:
            ui.set_status(message)
        else:
            print(message)

    if mode == "led":
        sbc.demo_led_sequence()
        if event_server is not None:
            event_server.stop()
        return

    if mode == "calibrate":
        calibrate_axes(sbc, config, "sbc_config.json")
        if event_server is not None:
            event_server.stop()
        return

    if mode == "read":
        sbc.startup_sequence()
        macro_engine.run_macro(effective.get("powerup_macro", ""))
        send_interval = 0.0
        last_send = 0.0
        if isinstance(net_config, dict) and event_server is not None:
            send_interval = max(0.0, float(net_config.get("send_interval_ms", 0)) / 1000.0)
        while True:
            buf = sbc.read_raw()
            state = sbc.parse_state(buf)
            sbc.handle_button_leds(led_mode)
            sbc.update_logical_states(led_mode)
            macro_engine.handle_layer_cycle()
            macro_engine.handle_buttons(state, led_mode)
            macro_engine.handle_analogs(state)
            macro_engine.handle_gears(state)
            if event_server is not None and send_interval >= 0:
                now = time.monotonic()
                if send_interval == 0 or now - last_send >= send_interval:
                    event_server.publish(
                        {
                            "type": "raw_state",
                            "buttons": [1 if pressed else 0 for pressed in state["buttons"]],
                            "analogs": {
                                "aim_x": state["aim_x"],
                                "aim_y": state["aim_y"],
                                "rotation": state["rotation"],
                                "sight_x": state["sight_x"],
                                "sight_y": state["sight_y"],
                                "left_pedal": state["left_pedal"],
                                "middle_pedal": state["middle_pedal"],
                                "right_pedal": state["right_pedal"],
                            },
                            "tuner": state["tuner"],
                            "gear": state["gear"],
                        }
                    )
                    last_send = now
            if ui is not None:
                ui.set_layer(macro_engine.layer)
                if touch is not None:
                    point = touch.poll()
                    if point:
                        ui.handle_touch(*point)
            if sbc.update_gear_lights:
                gear_effects.update(state["gear"])
            macro_engine.tick()
            if ui is not None:
                ui.render(state)
            if sbc.should_terminate():
                sbc.graceful_shutdown()
                if ui is not None:
                    ui.teardown()
                if touch is not None:
                    touch.close()
                if event_server is not None:
                    event_server.stop()
                return
            time.sleep(sbc.TIME_BETWEEN_POLLS_MS / 1000.0)


if __name__ == "__main__":
    main()
