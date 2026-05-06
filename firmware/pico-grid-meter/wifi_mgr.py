"""Robust WiFi connection manager for Pico W."""

import time

import network


class WiFi:
    def __init__(self, ssid: str, password: str, country: str = "GB", wdt=None):
        # Country must be set before activating WLAN to enable ch 12/13
        # (UK 2.4 GHz APs commonly use channel 13).
        try:
            network.country(country)
        except Exception as e:
            print("[wifi] country set failed:", e)
        self._ssid = ssid
        self._password = password
        self._wlan = network.WLAN(network.STA_IF)
        self._wdt = wdt

    def connect(self, timeout_s: int = 20) -> bool:
        if self._wlan.isconnected():
            return True
        self._wlan.active(True)
        self._wlan.connect(self._ssid, self._password)
        deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
        while not self._wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return False
            if self._wdt is not None:
                self._wdt.feed()
            time.sleep_ms(200)
        return True

    @property
    def is_connected(self) -> bool:
        return self._wlan.isconnected()

    @property
    def ifconfig(self):
        return self._wlan.ifconfig()
