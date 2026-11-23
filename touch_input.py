"""Read direct touchscreen taps in display coordinates."""

import sys


class TouchInput:
    """Capture a configured or automatically discovered evdev touchscreen."""

    def __init__(self, device_path, screen_width, screen_height):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.device = None
        self.enabled = False
        self._point = [None, None]
        self._touching = False
        self._slot = 0

        try:
            from evdev import InputDevice, ecodes, list_devices
        except ImportError:
            return

        for path in [device_path] if device_path else list_devices():
            device = None
            direct = False
            try:
                device = InputDevice(path)
                caps = device.capabilities(absinfo=True)
                axes = dict(caps.get(ecodes.EV_ABS, []))
                touch_button = ecodes.BTN_TOUCH in caps.get(ecodes.EV_KEY, [])
                props = device.input_props() if hasattr(device, "input_props") else []
                direct = 1 in props or (touch_button and 0 not in props)  # INPUT_PROP_DIRECT / POINTER
                single = touch_button and {ecodes.ABS_X, ecodes.ABS_Y} <= axes.keys()
                multi = {ecodes.ABS_MT_POSITION_X, ecodes.ABS_MT_POSITION_Y,
                         ecodes.ABS_MT_TRACKING_ID} <= axes.keys()
                if (device_path or direct) and (single or multi):
                    device.grab()
                    self.device = device
                    self.enabled = True
                    self._codes = ecodes
                    self._axes = axes
                    self._xy = (ecodes.ABS_X, ecodes.ABS_Y) if single else (
                        ecodes.ABS_MT_POSITION_X, ecodes.ABS_MT_POSITION_Y
                    )
                    self._single = single
                    return
            except OSError as exc:
                if device_path or device is not None and direct:
                    print(f"Direct touch unavailable on {path}: {exc}", file=sys.stderr)
            if device is not None:
                device.close()

    def close(self):
        """Close the evdev descriptor and release its grab."""
        if self.device is not None:
            self.device.close()
            self.device = None
        self.enabled = False

    @staticmethod
    def _scale(value, info, size):
        span = info.max - info.min
        if span <= 0:
            return None
        return max(0, min(size - 1, (value - info.min) * (size - 1) // span))

    def poll(self):
        """Return one tap on release and leave later events for the next poll."""
        if not self.enabled:
            return None
        codes = self._codes
        try:
            for _ in range(64):
                event = self.device.read_one()
                if event is None:
                    break
                if event.type == codes.EV_ABS and not self._single:
                    if event.code == codes.ABS_MT_SLOT:
                        self._slot = event.value
                    if self._slot != 0:
                        continue
                down = None
                if self._single and event.type == codes.EV_KEY and event.code == codes.BTN_TOUCH:
                    down = bool(event.value)
                elif event.type == codes.EV_ABS:
                    if not self._single and event.code == codes.ABS_MT_TRACKING_ID:
                        down = event.value >= 0
                    elif event.code in self._xy:
                        axis = self._xy.index(event.code)
                        size = (self.screen_width, self.screen_height)[axis]
                        self._point[axis] = self._scale(event.value, self._axes[event.code], size)
                if down is not None:
                    was_down = self._touching
                    self._touching = down
                    if was_down and not down and None not in self._point:
                        return tuple(self._point)
        except BlockingIOError:
            pass
        except OSError:
            self.close()
        return None
