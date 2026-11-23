"""Per-axis jitter rejection without averaging or waiting for future samples."""


class AdaptiveJitter:
    """Learn a bounded jitter band from small reversals and hold inside it."""

    def __init__(self, minimum_band=3, maximum_band=18):
        self.minimum_band = max(0, int(minimum_band))
        self.maximum_band = max(self.minimum_band, int(maximum_band))
        self.band = self.minimum_band
        self.output = None
        self.previous = None
        self.previous_delta = 0
        self.reversals = 0
        self.since_learning = 0

    def update(self, value, minimum=None, maximum=None):
        if self.previous is None:
            self.previous = self.output = value
            return value

        delta = value - self.previous
        self.previous = value
        self.since_learning += 1
        if delta:
            previous_delta = self.previous_delta
            if delta * previous_delta < 0 and max(abs(delta), abs(previous_delta)) <= self.maximum_band:
                self.reversals += 1
                if self.reversals >= 3:
                    self.band = max(self.band, min(abs(delta), abs(previous_delta)))
                    self.since_learning = 0
            else:
                self.reversals = 0
            self.previous_delta = delta
        if self.since_learning >= 128:
            self.band = max(self.minimum_band, self.band - 1)
            self.since_learning = 0
            self.reversals = 0
            self.previous_delta = 0

        # Preserve exact neutral and end stops. Small steps accumulate against
        # the last reported position, so a slow ramp can still break out.
        if value in (0, minimum, maximum) or abs(value - self.output) > self.band:
            self.output = value
        return self.output
