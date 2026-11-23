"""Simple evdev touch adapter that emits screen-space tap coordinates."""


class TouchInput:
    """
    Touch reader abstraction.

    Behavior:
    - Reads absolute touch events from an input device.
    - Scales raw device coordinates to configured screen dimensions.
    - Returns a point only on touch release, suitable for UI click semantics.
    """

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
            self._abs_info = dict(self.device.capabilities(absinfo=True).get(3, []))
            if not ({0, 1} <= self._abs_info.keys() or {53, 54} <= self._abs_info.keys()):
                self.close()
                return
            self.device.grab()
            self.enabled = True
        except OSError:
            self.close()

    def close(self):
        """Close the evdev descriptor and release its grab."""
        if self.device is None:
            return
        self.device.close()
        self.device = None
        self.enabled = False

    def _scale(self, value, abs_info, target_max):
        """Map raw absolute axis values into [0, target_max)."""
        if abs_info is None:
            return None
        span = abs_info.max - abs_info.min
        if span <= 0:
            return None
        return max(0, min(target_max - 1, int((value - abs_info.min) * (target_max - 1) / span)))

    def poll(self):
        """Return `(x, y)` on touch release, else `None`."""
        if not self.enabled or self.device is None:
            return None
        point = None
        try:
            for event in self.device.read():
                if event.type == 3:  # EV_ABS
                    if event.code in (0, 53):  # ABS_X or ABS_MT_POSITION_X
                        abs_info = self._abs_info.get(event.code)
                        self._last_x = self._scale(event.value, abs_info, self.screen_width)
                    elif event.code in (1, 54):  # ABS_Y or ABS_MT_POSITION_Y
                        abs_info = self._abs_info.get(event.code)
                        self._last_y = self._scale(event.value, abs_info, self.screen_height)
                elif event.type == 1 and event.code == 330:  # BTN_TOUCH
                    if self._touching and not event.value and None not in (self._last_x, self._last_y):
                        point = (self._last_x, self._last_y)
                    self._touching = bool(event.value)
        except BlockingIOError:
            pass
        except OSError:
            self.close()
        return point
