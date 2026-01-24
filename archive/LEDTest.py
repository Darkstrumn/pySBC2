#!/usr/bin/python3
import time
import usb.core
import usb.util


VID = 0x0A7B
PID = 0xD000
INTERFACE = 0
SETTING = 0
ENDPOINT_WRITER = 1

# LED mapping and packing based on SBC/src/SBC.h and SBC/src/SBCController.cpp.
LED_ID_MIN = 4
LED_ID_MAX = 41
LED_ID_UNUSED = {34}

LED_BUTTON_IDS = [i for i in range(4, 34) if i not in LED_ID_UNUSED]
LED_GEAR_IDS = [35, 36, 37, 38, 39, 40, 41]
LED_ALL_IDS = LED_BUTTON_IDS + LED_GEAR_IDS

RAW_LED_DATA_LENGTH = 22
INTENSITY_MIN = 0x00
INTENSITY_MAX = 0x0F


def clamp_intensity(value: int) -> int:
    if value < INTENSITY_MIN:
        return INTENSITY_MIN
    if value > INTENSITY_MAX:
        return INTENSITY_MAX
    return value


class LedMVP:
    def __init__(self):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise RuntimeError("Steel Battalion Controller not found.")

        if self.dev.is_kernel_driver_active(INTERFACE):
            self.dev.detach_kernel_driver(INTERFACE)
            usb.util.claim_interface(self.dev, INTERFACE)

        self.dev.set_configuration()
        cfg = self.dev.get_active_configuration()
        self.ep_out = cfg[(INTERFACE, SETTING)][ENDPOINT_WRITER]
        self.raw_led_data = bytearray(RAW_LED_DATA_LENGTH)

    def write(self):
        self.ep_out.write(self.raw_led_data)

    def set_led(self, led_id, intensity, send=True):
        if led_id in LED_ID_UNUSED or led_id < LED_ID_MIN or led_id > LED_ID_MAX:
            return

        capped = clamp_intensity(intensity)
        hex_pos = led_id % 2
        byte_pos = (led_id - hex_pos) // 2

        self.raw_led_data[byte_pos] &= 0x0F if hex_pos == 1 else 0xF0
        self.raw_led_data[byte_pos] += capped * (0x10 if hex_pos == 1 else 0x01)

        if send:
            self.write()

    def set_all(self, intensity, send=True):
        for led_id in LED_BUTTON_IDS:
            self.set_led(led_id, intensity, send=False)
        if send:
            self.write()

    def fade_in_order(self, led_ids, delay=0.03):
        for led_id in led_ids:
            for intensity in range(INTENSITY_MIN, INTENSITY_MAX + 1):
                self.set_led(led_id, intensity, send=True)
                time.sleep(delay)

    def fade_out_order(self, led_ids, delay=0.03):
        for led_id in led_ids:
            for intensity in range(INTENSITY_MAX, INTENSITY_MIN - 1, -1):
                self.set_led(led_id, intensity, send=True)
                time.sleep(delay)

    def pulse_all(self, pulses=3, hold=0.15):
        for _ in range(pulses):
            self.set_all(INTENSITY_MAX, send=True)
            time.sleep(hold)
            self.set_all(INTENSITY_MIN, send=True)
            time.sleep(hold)

    def run_demo(self):
        self.set_all(INTENSITY_MIN, send=True)
        self.fade_in_order(LED_BUTTON_IDS, delay=0.03)
        self.pulse_all(pulses=3, hold=0.2)
        self.fade_out_order(list(reversed(LED_BUTTON_IDS)), delay=0.03)
        self.set_all(INTENSITY_MIN, send=True)


def main():
    demo = LedMVP()
    demo.run_demo()


if __name__ == "__main__":
    main()
