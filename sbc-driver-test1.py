#!/usr/bin/python3
"""
Runtime entrypoint for SBC controller operation (v1.0 service architecture).

High-level flow:
1. Load config/profile and initialize hardware/UI/network transports.
2. Run startup sequence, then optional powerup macro.
3. Run polling services for reader/writer/model/macro/telemetry/ui/shutdown.
4. Shutdown gracefully and keep runtime context audit logs for replay.
"""

import sys

from calibration import calibrate_axes
from config_loader import build_default_led_modes, load_config
from input_matrix import InputMatrix
from macro_engine import MacroEngine
from mqtt_bridge import MqttBridge
from network_server import NetworkEventServer
from sbc_driver import SBCDriver
from service_runtime import (
    CommandRouter,
    EventSinkFanout,
    LocalEventBus,
    RuntimeAuditSink,
    ServiceRuntime,
    build_services,
)
from touch_input import TouchInput
from ui_factory import init_ui
from vessel_models import build_vessel_model


def parse_args(argv):
    """Parse CLI mode (`read|led|calibrate`) and requested UI backend."""
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
    """Apply effective profile settings to driver instance and return base LED mode."""
    sbc.FLASH_PERIOD_S = float(effective["flash_period_s"])
    sbc.TIME_BETWEEN_POLLS_MS = int(effective["poll_interval_ms"])
    sbc.set_gear_lights(effective["update_gear_lights"], effective["gear_light_intensity"])
    sbc.GEAR_REVERSE_FLASH = bool(effective["gear_reverse_flash"])
    if isinstance(effective.get("analog"), dict):
        sbc.set_analog_config(effective["analog"])
        sbc.calibration_configured = True
    else:
        sbc.calibration_configured = False
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
    """Merge root config with currently active profile overrides."""
    active_profile = str(config.get("active_profile", "default"))
    profile_data = {}
    if isinstance(config.get("profiles"), dict):
        profile_data = config["profiles"].get(active_profile, {})
    effective = dict(config)
    if isinstance(profile_data, dict):
        effective.update(profile_data)
    return effective


def main():
    """Initialize runtime subsystems and execute selected operation mode."""
    mode, ui_mode = parse_args(sys.argv)
    config = load_config("sbc_config.json")
    effective = build_effective_config(config)

    sbc = SBCDriver()
    led_mode = apply_config(sbc, effective)
    sbc.open()

    macro_engine = None
    vessel_model = None
    ui = None
    touch = None
    event_server = None
    mqtt_bridge = None
    event_sink = None

    bus = LocalEventBus()
    audit_cfg = effective.get("audit", {})
    audit_sink = RuntimeAuditSink(
        path=str(audit_cfg.get("path", "runtime_context.log")),
        enabled=bool(audit_cfg.get("enabled", True)),
        max_bytes=int(audit_cfg.get("max_bytes", 2097152)),
        include_raw_state=bool(audit_cfg.get("include_raw_state", False)),
    )
    event_sink = EventSinkFanout([audit_sink])

    def reload_callback(vars_only=False, clear_vars=False):
        nonlocal led_mode, config, effective
        if clear_vars:
            if macro_engine is not None:
                macro_engine.clear_persisted_vars()
            return
        if vars_only:
            if macro_engine is not None:
                macro_engine.reload_vars()
            return
        config = load_config("sbc_config.json")
        effective = build_effective_config(config)
        led_mode = apply_config(sbc, effective)
        if macro_engine is not None:
            macro_engine.reload_config(effective)
        if vessel_model is not None:
            vessel_model.reload_config(effective)
        if ui is not None:
            ui.config_root = config
            ui.config_view = effective

    try:
        ui = init_ui(ui_mode, sbc, effective, config, "sbc_config.json", reload_callback=reload_callback)
        sbc.ui = ui

        net_config = effective.get("net_server", {})
        if isinstance(net_config, dict) and net_config.get("enabled"):
            event_server = NetworkEventServer(
                host=str(net_config.get("host", "0.0.0.0")),
                port=int(net_config.get("port", 8765)),
            )
            event_server.start()
            event_sink.add(event_server)

        mqtt_bridge = MqttBridge(effective.get("mqtt", {}), bus=bus, audit_sink=audit_sink)
        if mqtt_bridge.enabled:
            mqtt_bridge.start()
            event_sink.add(mqtt_bridge)

        input_matrix = InputMatrix(
            event_sink=event_sink,
            max_events=int(effective.get("input_queue_size", 256)),
        )
        macro_engine = MacroEngine(effective, sbc, ui=ui, event_sink=event_sink, input_matrix=input_matrix)
        vessel_model = build_vessel_model(effective, input_matrix=input_matrix, event_sink=event_sink)
        CommandRouter(bus, input_matrix, event_sink=event_sink)

        if effective.get("touch_device"):
            touch = TouchInput(
                effective.get("touch_device"),
                int(effective.get("touch_width", 800)),
                int(effective.get("touch_height", 480)),
            )
        sbc.touch_enabled = bool(touch and touch.enabled)

        errors = macro_engine.validate_macros()
        if errors:
            message = f"Macro errors: {errors[0]}"
            if ui is not None:
                ui.set_status(message)
            else:
                print(message)

        event_sink.publish(
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
                "runtime_mode": "services_v1",
            }
        )

        if mode == "led":
            sbc.demo_led_sequence()
            return

        if mode == "calibrate":
            calibrate_axes(sbc, config, "sbc_config.json")
            return

        if mode == "read":
            sbc.startup_sequence()
            vessel_model.on_boot_complete()
            macro_engine.run_macro(effective.get("powerup_macro", ""))

            runtime = ServiceRuntime([], audit_sink=audit_sink)
            runtime.services = build_services(
                sbc=sbc,
                macro_engine=macro_engine,
                vessel_model=vessel_model,
                input_matrix=input_matrix,
                effective=effective,
                led_mode=led_mode,
                ui=ui,
                touch=touch,
                event_sink=event_sink,
                bus=bus,
                runtime=runtime,
            )
            audit_sink.log("runtime_started", {"mode": "read", "runtime": "services_v1"}, service="runtime")
            runtime.run()
            audit_sink.log("runtime_stopped", {"reason": "shutdown_request"}, service="runtime")
            sbc.graceful_shutdown()
            return
    finally:
        if ui is not None:
            ui.teardown()
        if touch is not None:
            touch.close()
        if event_server is not None:
            event_server.stop()
        if mqtt_bridge is not None:
            mqtt_bridge.stop()


if __name__ == "__main__":
    main()
