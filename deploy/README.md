# Deploying the Cerbo MCP as a Claude.ai Custom Connector

Two systemd services on the Pi 4 (`grid-meter.local` / 192.168.0.99), behind a
single Cloudflare Tunnel that routes two subdomains to the local listeners:

```
cerbo.<domain>     → http://localhost:8766  (full-access, desktop browser)
cerbo-ro.<domain>  → http://localhost:8765  (read-only,  mobile)
```

Both are GitHub-OAuth-protected with a single-user allowlist.

## 1. Prepare two GitHub OAuth Apps

In <https://github.com/settings/developers>:

| App name                       | Homepage URL                | Callback URL                                  |
|--------------------------------|-----------------------------|-----------------------------------------------|
| Cerbo Connector (full)         | `https://cerbo.<domain>`    | `https://cerbo.<domain>/auth/callback`        |
| Cerbo Connector (read-only)    | `https://cerbo-ro.<domain>` | `https://cerbo-ro.<domain>/auth/callback`     |

Note the **Client ID** and a freshly-generated **Client secret** for each.

## 2. Install the MCP on the Pi

```bash
ssh ian@grid-meter.local
git clone https://github.com/GlassOnTin/victron-cerbo-mcp ~/cerbo-mcp
cd ~/cerbo-mcp
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv isn't already present
uv sync --extra http
.venv/bin/victron-cerbo-mcp --help                 # smoke (won't connect without env)
```

## 3. Populate the env files

```bash
sudo install -m 0600 -o root deploy/cerbo-mcp.env.example   /etc/cerbo-mcp.env
sudo install -m 0600 -o root deploy/cerbo-mcp-ro.env.example /etc/cerbo-mcp-ro.env
sudoedit /etc/cerbo-mcp.env       # fill in the four __PLACEHOLDER__ values
sudoedit /etc/cerbo-mcp-ro.env    # fill in the four __PLACEHOLDER__ values
```

The `CERBO_MQTT_PASSWORD` is the same Cerbo Remote Console password used by the
grid-meter bridge (`/home/ian/grid-meter-bridge/bridge.env`). Reuse it.

## 4. Install and enable the systemd units

```bash
sudo cp deploy/cerbo-mcp.service deploy/cerbo-mcp-ro.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cerbo-mcp.service cerbo-mcp-ro.service
sudo systemctl status cerbo-mcp.service cerbo-mcp-ro.service
journalctl -fu cerbo-mcp.service                  # expect: "connected, devices=7"
```

## 5. Cloudflare Tunnel

In the Cloudflare dashboard (Zero Trust → Networks → Tunnels):

1. Create a tunnel called `cerbo-pi`. Copy the install token.
2. On the Pi:
   ```bash
   sudo cloudflared service install <TOKEN>
   ```
3. Add **public hostnames** for the tunnel:
   - `cerbo.<domain>` → `http://localhost:8766`
   - `cerbo-ro.<domain>` → `http://localhost:8765`
4. (Optional, recommended) Add a WAF rate-limit rule capping `/token` and
   `/authorize` requests at 30/min per IP on both hostnames.

The `deploy/cloudflared-config.yml` in this repo is a reference layout if you'd
rather manage the tunnel from a config file — but the dashboard-driven flow
above is the simplest and what the official docs recommend.

## 6. Register both Connectors in Claude.ai

In <https://claude.ai/settings/connectors> → **Add custom connector**:

1. URL: `https://cerbo.<domain>` — name "Cerbo (full)". OAuth flow will redirect
   to GitHub; sign in with the allowlisted account; expect "Authorized".
2. URL: `https://cerbo-ro.<domain>` — name "Cerbo (read-only)". Same OAuth flow,
   second GitHub app.

In a new Claude conversation, the connector tool list should show:
- **Cerbo (read-only)**: 5 read tools, no `set_*` writers.
- **Cerbo (full)**: 5 read tools + 13 writers.

## 7. Smoke checks

From the desktop Connector:
```
list_devices    → 7 entries (same as the workstation stdio MCP)
system_overview → live battery / solar / AC / ESS snapshot
set_evcharger_mode(mode="auto", confirm=true)  → readback "Auto"
```

From the mobile Connector:
```
list_devices → 7 entries
set_evcharger_mode → tool not available (correct: hidden by VICTRON_READ_ONLY_MODE)
```

## Reconnect resilience

Reboot the Cerbo while both services are running. Expected behaviour:

- `journalctl -fu cerbo-mcp.service` shows `bridge disconnected, reconnecting`
  followed by exponential backoff and a successful re-connect once the Cerbo's
  MQTT broker is back. No service restart needed.
- Tool calls during the outage return a `bridge is offline (...) supervisor is
  reconnecting` error rather than hanging.

## Troubleshooting

- `Authentication failed: Not authorized` in the journal: the
  `CERBO_MQTT_PASSWORD` in the env file does not match the Cerbo's Remote
  Console password. Set it in Cerbo Settings → General → Remote Console
  password, then update the env file and `systemctl restart cerbo-mcp.service`.

- Claude.ai OAuth callback fails with `redirect_uri_mismatch`: the callback in
  the GitHub OAuth App settings must exactly match the connector hostname's
  `/auth/callback` path (including `https://`, no trailing slash).

- Connector shows zero tools: most likely `VICTRON_READ_ONLY_MODE=true` was set
  on the wrong env file. The full-access connector should have it `false`.
