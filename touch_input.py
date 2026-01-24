class TouchInput:
    def __init__(self, device_path, screen_width, screen_height):
        self.device_path = device_path
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.device = None
        self.enabled = False
        self._abs_info = {}
        self._last_x = None
        self._last_y = None
        self._touching = False

        try:
            from evdev import InputDevice
        except Exception:
            return

        try:
            self.device = InputDevice(device_path)
            self.device.grab()
            for code, info in self.device.absinfo.items():
                self._abs_info[code] = info
            self.enabled = True
        except Exception:
            self.enabled = False

    def close(self):
        if self.device is None:
            return
        try:
            self.device.ungrab()
        except Exception:
            pass

    def _scale(self, value, abs_info, target_max):
        if abs_info is None:
            return None
        span = abs_info.max - abs_info.min
        if span <= 0:
            return None
        return int((value - abs_info.min) * (target_max - 1) / span)

    def poll(self):
        if not self.enabled or self.device is None:
            return None
        try:
            for event in self.device.read():
                if event.type == 3:  # EV_ABS
                    if event.code in (0, 53):  # ABS_X or ABS_MT_POSITION_X
                        abs_info = self._abs_info.get(event.code)
                        self._last_x = self._scale(event.value, abs_info, self.screen_width)
                    elif event.code in (1, 54):  # ABS_Y or ABS_MT_POSITION_Y
                        abs_info = self._abs_info.get(event.code)
                        self._last_y = self._scale(event.value, abs_info, self.screen_height)
                elif event.type == 1 and event.code == 330:  # EV_KEY BTN_TOUCH
                    self._touching = event.value == 1
                    if not self._touching and self._last_x is not None and self._last_y is not None:
                        return (self._last_x, self._last_y)
        except Exception:
            return None
        return None
