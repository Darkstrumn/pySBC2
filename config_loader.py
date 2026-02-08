import json
from pathlib import Path

"""Config loading/merging helpers for runtime and profile selection."""


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
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
            continue
        if isinstance(value, dict) and isinstance(data[key], dict):
            for nested_key, nested_value in value.items():
                if nested_key not in data[key]:
                    data[key][nested_key] = nested_value
    return data


def build_default_led_modes(led_name_to_id):
    """Build per-control LED mode defaults for the active controller layout."""
    defaults = {}
    flash_names = {"Eject", "CockpitHatch", "Ignition", "Start"}
    for name in led_name_to_id.keys():
        defaults[name] = "flash" if name in flash_names else "toggle"
    return defaults
