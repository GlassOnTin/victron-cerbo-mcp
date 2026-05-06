"""SDM120CT-M register map and reader.

All measurements are 32-bit IEEE-754 floats, big-endian, occupying two
consecutive input registers. Read via Modbus function 0x04.

Reference: Eastron SDM120CT Series Modbus protocol document.
"""

from modbus_rtu import ModbusRTU


# Input-register addresses (0-indexed) for SDM120CT-M.
# Each entry is one float, so reads two registers starting at this address.
REG_VOLTAGE = 0x0000          # V
REG_CURRENT = 0x0006          # A — sign reflects active power direction
REG_ACTIVE_POWER = 0x000C     # W — SIGNED: +ve = imported, -ve = exported
REG_APPARENT_POWER = 0x0012   # VA
REG_REACTIVE_POWER = 0x0018   # VAr
REG_POWER_FACTOR = 0x001E     # unitless, signed
REG_FREQUENCY = 0x0046        # Hz
REG_IMPORT_ENERGY = 0x0048    # kWh, lifetime, monotonic
REG_EXPORT_ENERGY = 0x004A    # kWh, lifetime, monotonic
REG_TOTAL_ENERGY = 0x0156     # kWh, abs sum


class SDM120:
    def __init__(self, bus: ModbusRTU, addr: int = 1):
        self._bus = bus
        self._addr = addr

    def _read(self, reg: int) -> float:
        return self._bus.read_float(self._addr, reg)

    def read_all(self) -> dict:
        """Read every metric we care about. Each call is ~10 Modbus exchanges
        at 2400 baud, so completes in ~150-250 ms."""
        v = self._read(REG_VOLTAGE)
        i = self._read(REG_CURRENT)
        p = self._read(REG_ACTIVE_POWER)
        f = self._read(REG_FREQUENCY)
        e_imp = self._read(REG_IMPORT_ENERGY)
        e_exp = self._read(REG_EXPORT_ENERGY)
        return {
            "voltage": v,
            "current": i,
            "power": p,
            "frequency": f,
            "energy_forward": e_imp,
            "energy_reverse": e_exp,
        }
