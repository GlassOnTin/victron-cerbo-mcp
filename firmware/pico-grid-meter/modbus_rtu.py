"""Minimal Modbus RTU master for MicroPython.

Just enough to read 32-bit IEEE-754 floats out of an SDM120's input registers.
Half-duplex over RS485 with a DE/RE GPIO toggle for the MAX485.
"""

import struct
import time

from machine import Pin, UART


_CRC_TABLE = None


def _crc_table():
    global _CRC_TABLE
    if _CRC_TABLE is not None:
        return _CRC_TABLE
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
        table.append(crc)
    _CRC_TABLE = table
    return table


def crc16(data: bytes) -> bytes:
    table = _crc_table()
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ table[(crc ^ b) & 0xFF]
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


class ModbusRTU:
    """Half-duplex RS485 master.

    Supports function code 0x04 (read input registers) — the only one needed
    for SDM120 measurements. Add more if you ever want to write meter config.
    """

    def __init__(
        self,
        uart_id: int,
        tx_pin: int,
        rx_pin: int,
        de_pin,            # int = GPIO controlling DE+RE; None = auto-direction module
        baud: int = 2400,
        parity=None,
        stop: int = 1,
        timeout_ms: int = 500,
    ):
        self._de = Pin(de_pin, Pin.OUT, value=0) if de_pin is not None else None
        self._uart = UART(
            uart_id,
            baudrate=baud,
            bits=8,
            parity=parity,
            stop=stop,
            tx=Pin(tx_pin),
            rx=Pin(rx_pin),
            timeout=timeout_ms,
            timeout_char=20,
        )
        self._timeout_ms = timeout_ms
        # 3.5 char-time silence between frames at 2400 8N1 = ~16 ms
        self._frame_gap_ms = max(2, int(35000 / baud) + 1)
        self._byte_us = int(11_000_000 / baud)

    def _drain(self):
        # Drop any stale bytes from the RX buffer.
        n = self._uart.any()
        if n:
            self._uart.read(n)

    def _send(self, frame: bytes):
        self._drain()
        if self._de is not None:
            self._de.value(1)
        self._uart.write(frame)
        # Wait for TX to drain. MicroPython's UART has no portable txdone()
        # on RP2, so calculate worst-case time-on-wire.
        time.sleep_us(self._byte_us * len(frame) + 200)
        if self._de is not None:
            self._de.value(0)

    def _recv(self, expected_len: int) -> bytes:
        deadline = time.ticks_add(time.ticks_ms(), self._timeout_ms)
        buf = b""
        while len(buf) < expected_len and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            chunk = self._uart.read(expected_len - len(buf))
            if chunk:
                buf += chunk
            else:
                time.sleep_ms(2)
        return buf

    def read_input_registers(self, addr: int, reg: int, count: int) -> bytes:
        """Function 0x04. Returns the raw register byte string (count*2 bytes)."""
        req = bytes([addr, 0x04, (reg >> 8) & 0xFF, reg & 0xFF, 0, count])
        req += crc16(req)
        self._send(req)

        # Response: [addr, 0x04, byte_count, ...data..., crc_lo, crc_hi]
        expected = 5 + count * 2
        resp = self._recv(expected)
        time.sleep_ms(self._frame_gap_ms)

        if len(resp) < 5:
            raise OSError("modbus: short response (%d bytes)" % len(resp))
        if resp[0] != addr:
            raise OSError("modbus: address mismatch (got %d)" % resp[0])
        if resp[1] & 0x80:
            raise OSError("modbus: exception code %d" % resp[2])
        if resp[1] != 0x04:
            raise OSError("modbus: function mismatch (got %d)" % resp[1])
        if resp[2] != count * 2:
            raise OSError("modbus: byte-count mismatch (got %d)" % resp[2])
        if crc16(resp[:-2]) != resp[-2:]:
            raise OSError("modbus: CRC mismatch")
        return resp[3 : 3 + count * 2]

    def read_float(self, addr: int, reg: int) -> float:
        """SDM120 stores each measurement as one big-endian IEEE-754 float
        spanning two consecutive input registers."""
        data = self.read_input_registers(addr, reg, 2)
        return struct.unpack(">f", data)[0]
