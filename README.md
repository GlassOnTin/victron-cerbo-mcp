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
