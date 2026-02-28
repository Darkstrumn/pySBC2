import json
from pathlib import Path

"""Config loading/merging helpers for runtime and profile selection."""


def _merge_defaults(data, defaults):
    """Recursively merge missing defaults into loaded config tree."""
    if not isinstance(data, dict) or not isinstance(defaults, dict):
        return data
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
            continue
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            _merge_defaults(data[key], value)
    return data


def load_config(path):
    """
    Load config JSON and apply root-level defaults.

    Notes:
    - If file is missing/invalid, defaults are returned.
    - One-level nested dict defaults are merged (e.g. `net_server`, `vessel_model`).
    - Profile-specific overlays are applied elsewhere (`build_effective_config`).
    """
    defaults = {
        "led_mode": "toggle",
        "led_modes": {},
        "flash_period_s": 0.3,
        "poll_interval_ms": 4,
        "update_gear_lights": True,
        "gear_light_intensity": 8,
        "gear_reverse_flash": True,
        "gear_r_blink_period_ms": 500,
        "gear_r_blink_on_ms": 250,
        "gear5_breathe_period_ms": 2000,
        "gear5_breathe_min": 0,
        "gear5_breathe_max": 15,
        "persist_vars": False,
        "persist_var_names": [],
        "persist_var_path": "macro_vars.json",
        "sound_enabled": True,
        "sound_base_path": "sounds",
        "tts_enabled": True,
        "tts_voice": "",
        "powerup_macro": "powerup",
        "event_log_path": "sbc_events.log",
        "event_log_max_bytes": 131072,
        "input_queue_size": 256,
        "net_server": {
            "enabled": False,
            "host": "0.0.0.0",
            "port": 8765,
            "send_interval_ms": 20,
        },
        "services": {
            "reader_poll_ms": 4,
            "writer_poll_ms": 4,
            "model_poll_ms": 4,
            "macro_poll_ms": 4,
            "ai_poll_ms": 50,
            "telemetry_poll_ms": 20,
            "model_snapshot_ms": 250,
            "ui_poll_ms": 20,
            "shutdown_poll_ms": 20,
        },
        "mqtt": {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 1883,
            "keepalive": 60,
            "base_topic": "sbc",
            "username": "",
            "password": "",
            "publish_qos": 0,
            "retain": False,
            "io_raw_topic": "io/raw_state",
            "io_led_frame_topic": "io/led_frame",
            "event_raw_topic": "events/raw_state",
            "event_button_topic": "events/button",
            "event_vessel_topic": "events/vessel_snapshot",
            "event_ai_intent_topic": "events/ai_intent",
            "event_ai_diagnostic_topic": "events/ai_diagnostic",
            "command_topics": {
                "button": "cmd/button",
                "macro": "cmd/macro",
                "led": "cmd/led",
                "event": "cmd/event",
                "led_frame": "cmd/led_frame",
                "ai_mode": "cmd/ai_mode",
            },
        },
        "ai_copilot": {
            "enabled": True,
            "mode": "advisory",
            "emit_interval_ms": 200,
            "command_cooldown_ms": 700,
            "confidence_threshold": 0.65,
            "auto_macro_threshold": 0.8,
            "diagnostic_threshold": 0.75,
            "window_size": 12,
            "model_type": "heuristic",
            "model_path": "models/copilot_model.keras",
            "labels": [],
            "intent_macro_map": {
                "supercruise_transition": "ELITE_HYPERSPACE",
                "hard_brake": "ELITE_THROTTLE_0",
                "target_lock": "ELITE_TARGET_AHEAD",
            },
            "intent_led_map": {
                "supercruise_transition": "Start",
                "hard_brake": "Eject",
                "target_lock": "MainWeaponControl",
                "evasive_maneuver": "Comm3",
            },
        },
        "audit": {
            "enabled": True,
            "path": "runtime_context.log",
            "max_bytes": 2097152,
            "include_raw_state": False,
        },
        "vessel_model": {
            "type": "mech",
            "auto_queue_start": False,
            "auto_queue_powerup_macro": False,
            "control_map": {
                "hatch": "CockpitHatch",
                "crew_ready": "MultiMonOpenClose",
                "ignition": "Ignition",
                "start": "Start",
                "filter": "ToggleFilterControl",
                "life_support": "ToggleOxygenSupply",
                "coolant": "ToggleFuelFlowRate",
                "buffer_material": "ToggleBufferMaterial",
                "shielding": "ToggleVTLocation",
                "activate": "Start",
                "deactivate": "Eject",
            },
        },
        "touch_device": "",
        "touch_width": 800,
        "touch_height": 480,
        "active_profile": "default",
        "profiles": {},
    }
    cfg_path = Path(path)
    if not cfg_path.exists():
        return defaults
    try:
        data = json.loads(cfg_path.read_text())
    except (OSError, json.JSONDecodeError):
        return defaults
    return _merge_defaults(data, defaults)


def build_default_led_modes(led_name_to_id):
    """Build per-control LED mode defaults for the active controller layout."""
    defaults = {}
    flash_names = {"Eject", "CockpitHatch", "Ignition", "Start"}
    for name in led_name_to_id.keys():
        defaults[name] = "flash" if name in flash_names else "toggle"
    return defaults
