"""Nonblocking hold-to-confirm LED states for physical buttons."""


class HoldConfirmation:
    BLINK_S = 0.16
    FADE_S = 0.35

    def __init__(self, hold_ms):
        self.hold_s = hold_ms / 1000
        self.phase = "idle"
        self.started = 0.0
        self.confirmed = False

    def begin_confirmation(self, now):
        if self.phase == "pending":
            self.phase = "confirmed"
            self.started = now

    def update(self, now, pressed, rising, flash_s, maximum):
        if self.phase == "idle" and rising:
            self.phase, self.started = "holding", now
        elapsed = now - self.started
        if self.phase == "holding":
            if not pressed:
                self.phase, self.started = "aborted", now
                elapsed = 0.0
            elif elapsed >= self.hold_s:
                self.phase = "pending"
                self.confirmed = True
        if self.phase in ("holding", "pending"):
            return maximum if int(elapsed / max(0.01, flash_s)) % 2 == 0 else 0
        if self.phase == "aborted" and elapsed < self.FADE_S:
            return round(maximum * (1 - elapsed / self.FADE_S))
        if self.phase == "confirmed":
            cycle = int(elapsed / self.BLINK_S)
            if cycle < 3:
                return maximum if elapsed % self.BLINK_S < self.BLINK_S / 2 else 0
            if cycle < 5:
                return maximum
        if self.phase in ("aborted", "confirmed"):
            self.phase = "idle"
        return 0
