import json
import time
from pathlib import Path


def calibration_start_animation(sbc):
    for _ in range(2):
        sbc.set_all_leds(sbc.MAX_LIGHT_INTENSITY, send=True)
        time.sleep(0.15)
        sbc.set_all_leds(sbc.MIN_LIGHT_INTENSITY, send=True)
        time.sleep(0.15)


def calibration_end_animation(sbc):
    for _ in range(3):
        sbc.set_all_leds(sbc.MAX_LIGHT_INTENSITY, send=True)
        time.sleep(0.1)
        sbc.set_all_leds(sbc.MIN_LIGHT_INTENSITY, send=True)
        time.sleep(0.1)


def calibrate_axes(sbc, config, config_path):
    active_profile = str(config.get("active_profile", "default"))
    profiles = config.setdefault("profiles", {})
    profile = profiles.setdefault(active_profile, {})
    analog_cfg = profile.setdefault("analog", {})

    axis_list = [
        "aim_x",
        "aim_y",
        "rotation",
        "sight_x",
        "sight_y",
        "left_pedal",
        "middle_pedal",
        "right_pedal",
    ]

    calibration_start_animation(sbc)
    print("Calibration mode. Follow prompts for each axis.")
    for axis_name in axis_list:
        axis_settings = analog_cfg.setdefault(axis_name, {})
        mode = str(axis_settings.get("deadzone_mode", "center")).lower()
        samples_count = int(axis_settings.get("calibration_samples", 20))
        margin_abs = int(axis_settings.get("deadzone_margin_abs", 5))
        margin_mult = float(axis_settings.get("deadzone_margin_mult", 1.2))
        if samples_count < 5:
            samples_count = 5

        input(f"Set {axis_name} to neutral/rest and press Enter...")
        samples = []
        for _ in range(samples_count):
            buf = sbc.read_raw()
            raw_state = sbc.parse_raw_state(buf)
            samples.append(int(raw_state[axis_name]))
            time.sleep(0.02)

        avg = int(sum(samples) / len(samples))
        if mode == "low":
            axis_settings["center"] = 0
            max_val = max(samples)
            axis_settings["deadzone"] = int(max_val * margin_mult + margin_abs)
        else:
            axis_settings["center"] = avg
            max_dev = max(abs(v - avg) for v in samples)
            axis_settings["deadzone"] = int(max_dev * margin_mult + margin_abs)

        if "smoothing_samples" not in axis_settings:
            axis_settings["smoothing_samples"] = 2

        print(f"{axis_name}: center={axis_settings['center']} deadzone={axis_settings['deadzone']}")

    calibration_end_animation(sbc)
    Path(config_path).write_text(json.dumps(config, indent=2))
    print("Calibration complete. Settings saved.")
