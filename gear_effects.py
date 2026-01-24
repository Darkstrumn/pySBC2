import time


class GearEffectController:
    def __init__(self, sbc, macro_engine, config):
        self.sbc = sbc
        self.macro_engine = macro_engine
        self.config = config
        self._active_effect = None

    def update(self, gear_value):
        if self.sbc.GEAR_REVERSE_FLASH and gear_value == -2:
            self.sbc.update_gear_leds(None, self.sbc.gear_light_intensity)
            period = int(self.config.get("gear_r_blink_period_ms", 500))
            on_ms = int(self.config.get("gear_r_blink_on_ms", 250))
            self._apply_blink("GearR", period_ms=period, on_ms=on_ms)
            return
        if gear_value == 5:
            self.sbc.update_gear_leds(None, self.sbc.gear_light_intensity)
            period = int(self.config.get("gear5_breathe_period_ms", 2000))
            min_val = int(self.config.get("gear5_breathe_min", 0))
            max_val = int(self.config.get("gear5_breathe_max", 15))
            self._apply_breathe("Gear5", period_ms=period, min_val=min_val, max_val=max_val)
            return

        self._clear_effects()
        self.sbc.update_gear_leds(gear_value, self.sbc.gear_light_intensity)

    def _apply_blink(self, led_name, period_ms=500, on_ms=250):
        self._set_effect(
            led_name,
            {
                "type": "blink",
                "start": time.monotonic(),
                "duration_ms": None,
                "period_ms": period_ms,
                "on_ms": on_ms,
                "intensity": 15,
            },
        )

    def _apply_breathe(self, led_name, period_ms=2000, min_val=0, max_val=15):
        self._set_effect(
            led_name,
            {
                "type": "breathe",
                "start": time.monotonic(),
                "duration_ms": None,
                "period_ms": period_ms,
                "min": min_val,
                "max": max_val,
            },
        )

    def _set_effect(self, led_name, effect):
        if self._active_effect != led_name:
            self._clear_effects()
            self.sbc.update_gear_leds(None, self.sbc.gear_light_intensity)
            self.macro_engine.led_effects[led_name] = effect
            self._active_effect = led_name

    def _clear_effects(self):
        for name in ("GearR", "Gear5"):
            if name in self.macro_engine.led_effects:
                self.macro_engine.led_effects.pop(name, None)
        self._active_effect = None
