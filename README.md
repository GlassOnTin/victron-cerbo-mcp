# victron-cerbo-mcp

MCP server exposing a Victron Cerbo GX (and connected MultiPlus / MPPT / battery) over the local MQTT broker. Reads via curated summary tools plus a `metric_get` escape hatch; writes are bounded and behind `--read-only`-by-default.

## Why this exists

`gimi-q/victron-vrm-mcp` is cloud-only and read-only. `lubosstrejcek/victron-tcp` covers local reads but not writes. This server adds write tools (ESS setpoint, MultiPlus mode, relays, etc.) on top of `tomer-w/victron_mqtt`.

## Status

v0.1 — verified end-to-end against a live Cerbo GX (Venus OS Large v3.80~14, MPPT 150/35, MultiPlus-II 48/3000/35-32, ECO-Worthy UP16S 100 Ah).

| Surface | State |
|---|---|
| MQTT TLS connect (port 8883, password-only auth) | working |
| Read tools (`system_overview`, `list_devices`, `list_metrics`, `metric_get`) | working, 174 metrics across 6 devices |
| Write tools (9 tools: grid setpoint, ESS mode, min SoC, MultiPlus mode, current limits, relays, MPPT enable) | implemented with bounds + confirm + read-only gate |
| Tests | 16 passing (11 unit + 5 live) |
| Live write smoke (relay toggle round-trip) | not yet executed by author — flip `VICTRON_READ_ONLY=false` and try at your own risk |

## Setup

Cerbo prerequisites:

1. *Settings → Services → MQTT on LAN (SSL)* enabled (port 8883).
2. *Settings → General → Remote Console* password set (the same password protects MQTT).
3. *Settings → Services → Modbus TCP* optional but useful for portal-id lookup.

Local install:

```bash
cd victron-cerbo-mcp
uv sync
```

Run the server (stdio):

```bash
VICTRON_HOST=venus.local \
VICTRON_PORT=8883 \
CERBO_MQTT_PASSWORD='...' \
VICTRON_READ_ONLY=true \
uv run victron-cerbo-mcp
```

## Configuration (env)

| Variable | Default | Notes |
|---|---|---|
| `VICTRON_HOST` | `venus.local` | Cerbo IP/hostname |
| `VICTRON_PORT` | `8883` | TLS broker; 1883 for plain |
| `VICTRON_USE_SSL` | `true` if port 8883 | Forces TLS on/off |
| `VICTRON_USERNAME` | unset | Cerbo ignores this; leave unset |
| `VICTRON_PASSWORD` / `CERBO_MQTT_PASSWORD` | — | Required |
| `VICTRON_PORTAL_ID` | auto | 12-hex; usually auto-discovered |
| `VICTRON_READ_ONLY` | `true` | Set to `false` to enable write tools |

## Claude Code MCP registration

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "victron-cerbo": {
      "command": "uv",
      "args": ["run", "--directory", "/home/ian/Code/victron-cerbo-mcp", "victron-cerbo-mcp"],
      "env": {
        "VICTRON_HOST": "venus.local",
        "CERBO_MQTT_PASSWORD": "${CERBO_MQTT_PASSWORD}",
        "VICTRON_READ_ONLY": "true"
      }
    }
  }
}
```

## What is and is not verified

Verified empirically against a Cerbo GX (Large image) on `venus.local`:

- TLS auth: password-only, username ignored.
- 2094 unique topics across `battery/512`, `solarcharger/279`, `vebus/276`, `system/0`, `settings/0`, `digitalinputs/0`, `adc/0`, `ble/0`, plus empty `fronius/0` and `shelly/0` slots.
- Battery exposes aggregate min/max cell voltage but NOT per-cell array (BMS limitation).

Not yet verified:

- Write tools — every `set_*` raises `NotImplementedError` until its unique_id is confirmed against the running Hub.
- `system_overview`'s suffix-matching against the live `victron_mqtt` taxonomy: some fields may return `None` until the suffixes match what the lib uses.

## Tests

```bash
uv run pytest
```

Live integration tests (hits the real Cerbo) are gated on `VICTRON_LIVE=1`.

## Companion firmware: `firmware/pico-grid-meter/`

A Raspberry Pi Pico 2 W reads an Eastron SDM120CT-M over RS485 and publishes
the result to the Cerbo's MQTT broker, where the community
[`mr-manuel/venus-os_dbus-mqtt-grid`](https://github.com/mr-manuel/venus-os_dbus-mqtt-grid)
driver picks it up as `com.victronenergy.grid`. With ESS Assistant loaded
into the MultiPlus, this lets the system charge the battery from the AC-in
side whenever the household solar inverter exports surplus.

### Wiring (low-voltage side)

```
        Pico 2 W                     MAX485 module                   SDM120CT-M
        ┌────────┐                   ┌──────────┐                    ┌──────────┐
   3V3 ─┤ 3V3    │                   │ VCC ←────┤ from Pico 3V3      │          │
   GND ─┤ GND ───┼───────────────────┤ GND      │                    │          │
   GP0 ─┤ TX  ───┼───────────────────┤ DI       │                    │          │
   GP1 ─┤ RX  ───┼───────────────────┤ RO       │                    │          │
   GP2 ─┤ DE/RE ─┼───────────────────┤ DE+RE    │   (twisted pair)   │          │
        │        │                   │ A    ────┼────────────────────┤ A (T+)   │  ← term 8
        │        │                   │ B    ────┼────────────────────┤ B (T-)   │  ← term 9
        └────────┘                   └──────────┘                    └──────────┘
                                          │ │
                                       120Ω termination across A/B
                                       at the far end (the SDM120 end)
```

Notes:

- DE and RE are tied together so one GPIO drives both (transmit-when-high).
- 120 Ω termination resistor across A/B at the end of the bus far from the
  Pico (the SDM120). On a single-meter run under ~5 m it usually works
  without termination but the resistor costs nothing.
- Add 680 Ω bias pull-up (A→VCC) and pull-down (B→GND) on the Pico end if
  you see flaky reads — most MAX485 breakouts include these already.

### Wiring (mains side — electrician)

- Eastron CT (ESCT-TA16) clamps around the **Live** meter tail, between
  the smart meter and the house consumer unit. Arrow on the CT must point
  **toward** the consumer unit (away from the grid).
- CT secondary leads (white = S1, black = S2) terminate at the SDM120's
  CT input terminals. **Never disconnect a CT while load current is
  flowing through it** — the open secondary develops dangerous voltage.
- SDM120 needs L+N for its own supply; provide via a 6 A MCB if there
  isn't already a metering circuit.
- Whole assembly should live in the same enclosure as the meter — not
  in the garage.

### Flashing

Tested against [MicroPython 1.24+](https://micropython.org/download/RPI_PICO2_W/)
for Pico 2 W:

```bash
# 1) Hold BOOTSEL while plugging in; copy the .uf2 to RPI-RP2.
# 2) Then push the firmware files:
mpremote connect auto fs cp firmware/pico-grid-meter/*.py :
mpremote connect auto fs cp firmware/pico-grid-meter/config.py :
mpremote connect auto reset
# Watch the boot output:
mpremote connect auto repl
```

`config.py` is gitignored — copy `config.example.py`, fill in WiFi and
MQTT credentials, and only that copy goes onto the Pico.

### What's verified vs. not

- Code compiles and the structure mirrors the SDM120 datasheet pinout —
  but the firmware has not yet been run against real hardware.
- Modbus register addresses are taken from the Eastron SDM120CT-M
  protocol document. The default address (1) and baud (2400) match
  factory defaults; verify via the meter's setup button.
