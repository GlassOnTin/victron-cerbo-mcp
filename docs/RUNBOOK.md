# Victron ESS Runbook

Recovery + reference for the SDM120-grid-meter / Pi 4 bridge / Cerbo
dbus-mqtt-grid / ESS Assistant chain commissioned 2026-05-07.

## Architecture

```
                        HOUSE SIDE                                       GARAGE SIDE
  ─────────────────────────────────────────────────────────  │  ───────────────────────────────────────────────
                                                              │
   [Roof solar inverter] ──┐                                  │
                           │                                  │
   [Smart meter] ──tails── [House CU] ──────┬──── spur ───────┼─── [Garage CU] ──── [Multi AC-in]
                              │             │                 │       (16 A RCD)        │
                              │             │ CT clamp        │                         │
                              │             │ around L tail   │                         │
                              │             ▼                 │                         │
                              │      [Eastron SDM120CT-M]     │   ┌─────────────────────┴──────────────┐
                              │             │                 │   │                                    │
                              │           Modbus RTU          │   │  [MultiPlus-II 48/3000/35-32]      │
                              │             │                 │   │  S/N HQ23244KZMY                   │
                              │      [USB-RS485 (CP2102)]     │   │  ─VE.Bus port 1: MK3-USB-C ────────┼── garage Pi 5 USB
                              │             │                 │   │  ─VE.Bus port 2: Cerbo VE.Bus     │   (192.168.0.234)
                              │       [Pi 4 "3dprinter"]      │   │  ─AC-out: freezers, lighting,     │
                              │       (192.168.0.149 wlan0)   │   │           DC MPPT 150/35           │
                              │             │                 │   │  ─DC: ECO-Worthy 48V 100Ah LFP    │
                              │       MQTT/TLS over WiFi      │   │           BMS on CAN              │
                              │             │                 │   └────────────┬───────────────────────┘
                              │             ▼                 │                │ VE.Bus
                              │      [Cerbo GX broker]        │                │
                              │      192.168.0.208            │                │
                              │      (dbus-flashmq)           │   ┌────────────┴───────────────────────┐
                              │             │                 │   │  [Cerbo GX]                        │
                              │       MQTT loopback           │   │  192.168.0.208                     │
                              │             ▼                 │   │  Venus OS Large 3.80~14            │
                              │      [dbus-mqtt-grid]         │   │  hostname: einstein                │
                              │      /service/dbus-mqtt-grid  │   └─────────────────────────────────────┘
                              │             │                 │
                              │             ▼ dbus            │
                              │      com.victronenergy.       │
                              │      grid.mqtt_grid_100       │
                              │             │                 │
                              │             ▼                 │
                              │      [ESS Hub-4 controller]   │
                              │      grid setpoint loop       │
                              │             │                 │
                              │             ▼ VE.Bus          │
                              │      [MultiPlus] charges/     │
                              │      discharges to track 0 W  │
                              │      at the meter point       │
                              │                               │
  ─────────────────────────────────────────────────────────────
```

## Device inventory

| Role | Device | IP/loc | Notes |
|------|--------|--------|-------|
| Workstation | this Linux box | LAN | runs MCP, virt-manager, USB/IP client |
| Cerbo GX | `einstein` | 192.168.0.208 | Venus OS Large 3.80~14, root SSH key in /data |
| MultiPlus II | 48/3000/35-32 | (in garage) | S/N HQ23244KZMY, ESS Assistant active |
| Battery | ECO-Worthy 48V 100Ah | (in garage) | LiFePO4, BMS on CAN bus (`battery.socketcan_vecan1`) |
| MPPT (DC) | SmartSolar 150/35 | (in garage) | DC-coupled, on VE.Direct |
| Grid meter | Eastron SDM120CT-M | house CU | 9600 8N1, addr 1, CT on L tail |
| Pi 4 ("3dprinter") | Raspberry Pi 4 | 192.168.0.149 (WiFi) | runs `grid-meter-bridge.service` + USB-RS485 to SDM120 |
| Pi 5 (garage) | Raspberry Pi 5 | 192.168.0.234 | exports MK3-USB-C via USB/IP |
| MK3-USB-C | Victron VE.Bus interface | (Pi 5 + Multi) | FTDI 0403:6015, S/N HQ2531TYYZU |
| Win11 VM | libvirt domain `win11` | host KVM | VEConfigure 3 + FTDI driver (CDM21216) |

## Healthy-state quick check

Single command set that should all return live values when everything's working:

```bash
# 1. Grid meter publishing (should change every 2 s)
ssh root@192.168.0.208 'tail -3 /var/log/dbus-mqtt-grid/current'
# expect: NOT "Waiting 5 seconds for receiving first data..."

# 2. ESS settings sane
ssh root@192.168.0.208 '
  for s in Hub4Mode AcPowerSetPoint MaxChargePower MaxFeedInPower \
           PreventFeedback BatteryLife/MinimumSocLimit; do
    echo "$s = $(dbus -y com.victronenergy.settings /Settings/CGwacs/$s GetValue)"
  done
'
# expect: Hub4Mode=2, MaxChargePower=0, MaxFeedInPower=0, PreventFeedback=1, MinSoC=50

# 3. Multi state
ssh root@192.168.0.208 '
  echo "State    = $(dbus -y com.victronenergy.vebus.ttyS4 /State GetValue)"
  echo "ActiveIn = $(dbus -y com.victronenergy.vebus.ttyS4 /Ac/ActiveIn/Connected GetValue)"
  echo "SoC      = $(dbus -y com.victronenergy.system /Dc/Battery/Soc GetValue)"
  echo "GridP    = $(dbus -y com.victronenergy.system /Ac/Grid/L1/Power GetValue)"
'
# State: 3=Bulk 4=Absorb 5=Float 9=Inverting

# 4. MCP grid_status (from this workstation)
cd /home/ian/Code/victron-cerbo-mcp && \
  VICTRON_LIVE=1 VICTRON_HOST=192.168.0.208 \
  CERBO_MQTT_PASSWORD="$(python3 -c "import json; print(json.load(open('/home/ian/.claude.json'))['mcpServers']['victron-cerbo']['env']['CERBO_MQTT_PASSWORD'])")" \
  uv run pytest tests/test_e2e_live.py -k grid_status -v
```

## ESS configuration (locked-in, 2026-05-07)

| Setting | Value | Rationale |
|---|---|---|
| `Hub4Mode` | 2 (Optimised, no BatteryLife) | Standard self-consumption |
| `AcPowerSetPoint` | 50 W | Slight positive bias = no inadvertent export |
| `MaxChargePower` | 0 W | No grid-charging (only surplus solar) |
| `MaxFeedInPower` | 0 W | No feed-in to grid |
| `PreventFeedback` | 1 | Enforces no battery → grid |
| `MinimumSocLimit` | 50% | Reserve protection — battery becomes UPS for freezers |
| Grid code | UK G98/1 March 2019, G99/1 May 2018 | Required by ESS, password-locked after first send |
| AC-in current limit | 16 A | Matches garage MCB (20 A in house, 16 A spur) |

Multi internal (set by ESS Assistant):

| Setting | Value |
|---|---|
| Battery type | LiFePo4 with other type BMS |
| Capacity | 100 Ah |
| Sustain V | 50.00 V |
| Absorption V (overridden by BMS DVCC to 58.4 V) | 56.80 V |
| Float V | 54.00 V |
| Virtual switch | **Off** (was "dedicated ignore AC input" pre-ESS) |
| PowerAssist | unchecked (ESS replaces it) |
| Lithium batteries | checked |

## Recovery procedures

### Pi 4 grid bridge stopped publishing

```bash
ssh ian@192.168.0.149 'sudo systemctl restart grid-meter-bridge.service'
ssh ian@192.168.0.149 'sudo journalctl -u grid-meter-bridge -n 20 --no-pager'
```

If the Pi 4 isn't at 192.168.0.149 any more, locate it via:

```bash
nslookup 3dprinter.fritz.box 192.168.0.1
```

Common cause: hourly `killall python` cron killed it. We removed the offending crontab entry on 2026-05-07; if it ever returns, check root's crontab on the Pi 4:

```bash
ssh ian@192.168.0.149 'sudo crontab -l'
# the dangerous line was:
#   0 * * * * /usr/bin/killall python && /usr/sbin/service picamera2-webstream restart
```

### dbus-mqtt-grid driver on Cerbo restarting

If Cerbo's driver log shows `Waiting since 60 seconds...` or `Driver stopped`,
the driver isn't getting MQTT data from the Pi 4. Fix the Pi 4 first
(above), then:

```bash
ssh root@192.168.0.208 'svc -t /service/dbus-mqtt-grid'   # restart
ssh root@192.168.0.208 'tail -20 /var/log/dbus-mqtt-grid/current'
```

### USB/IP chain to Win11 VM broken

When you next need VEConfigure (e.g. to change settings):

```bash
~/bin/mk3-attach.sh                # rebuilds Pi 5 → workstation → VM
remote-viewer spice://127.0.0.1:5902 &   # opens the VM
```

The chain breaks every time the Multi reboots (it powers the MK3-USB-C cable).
The script is idempotent — run it again any time you see "Connect cable
and switch on device" in VEConfigure.

If `mk3-attach.sh` fails because the kernel modules unloaded:

```bash
# manual sequence:
ssh ian@192.168.0.234 'sudo modprobe usbip-host usbip-core; sudo usbipd -D'
ssh ian@192.168.0.234 'sudo usbip bind -b 3-1'
sudo usbip attach -r 192.168.0.234 -b 3-1
sudo virsh attach-device win11 /tmp/usb-mk3.xml
```

### Cerbo SSH lost

Key auth from this workstation lives at `/data/home/root/.ssh/authorized_keys`
which survives firmware updates (rootfs is replaced but `/data` isn't).
If the key is gone:

```bash
# at the Cerbo Remote Console: Settings → General → Set root password
# then:
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@192.168.0.208
```

If the GUI Superuser unlock is lost, follow the procedure in
[Victron's official docs](https://www.victronenergy.com/live/ccgx:root_access).
Summary: Settings → General → Access Level → enter `ZZZ` to elevate to
"User and installer", then highlight (don't open) Access Level and hold
keyboard right-arrow ~5 s to elevate to Superuser. Keyboard navigation
required — this gesture doesn't work reliably on touchscreens or phones.

### Win11 VM lost / corrupted

Reproducible recipe in `tools/win11-vm-prep/`:

```bash
# 1. fresh disk for win11 domain
sudo qemu-img create -f qcow2 /var/lib/libvirt/images/win11.qcow2 128G

# 2. floppy with autounattend.xml
truncate -s 1474560 /var/lib/libvirt/images/autounattend.flp
mkfs.vfat -n UNATTEND /var/lib/libvirt/images/autounattend.flp
# edit autounattend.xml first to replace CHANGE_ME
mcopy -i /var/lib/libvirt/images/autounattend.flp \
      tools/win11-vm-prep/autounattend.xml ::/

# 3. boot the VM. ~5 minutes to desktop, no interaction needed.

# 4. inside Windows, run install.ps1 to fetch VEConfigure + FTDI driver:
#    iwr -useb http://<host>:18888/install.ps1 -OutFile $env:TEMP\inst.ps1
#    powershell -ExecutionPolicy Bypass -File $env:TEMP\inst.ps1
```

`win11.qcow2` had a `pre-pwreset-2026-05-07` snapshot before the install:

```bash
sudo qemu-img snapshot -l /var/lib/libvirt/images/win11.qcow2
# revert with: sudo qemu-img snapshot -a pre-pwreset-2026-05-07 ...
```

### ESS config lost (e.g. after Multi factory reset)

VEConfigure 3 in the Win11 VM, with USB/IP attached:

1. Run `~/bin/mk3-attach.sh`
2. Open VEConfigure 3 in the VM (via virt-viewer)
3. Port selection → Com port → COM3
4. Grid tab → set **UK: G98/1 March 2019, G99/1 May 2018**
5. Assistants tab → Add → Solar / Self-consumption → ESS
6. Start assistant, walk through with these answers:
   - Battery: **LiFePo4 with other type BMS**
   - Capacity: **100 Ah**
   - Change battery type: **as suggested**
   - Sustain V: **50.0 V**
   - Cut-off curve: defaults
   - Restart offset: **1.20 V**
   - PV inverters on AC out: **No**
7. Send settings → modified → OK
8. Re-apply hardening on the Cerbo:
   ```bash
   ssh root@192.168.0.208 '
     dbus -y com.victronenergy.settings /Settings/CGwacs/MaxChargePower SetValue 0
     dbus -y com.victronenergy.settings /Settings/CGwacs/MaxFeedInPower SetValue 0
     dbus -y com.victronenergy.settings /Settings/CGwacs/PreventFeedback SetValue 1
     dbus -y com.victronenergy.settings /Settings/CGwacs/BatteryLife/MinimumSocLimit SetValue 50
   '
   ```

### MCP not seeing the grid

If `grid_status` returns `found=false`:

1. Cerbo's `dbus-mqtt-grid` driver isn't registered on dbus, OR
2. `victron_mqtt` library can't enumerate it.

Check from Cerbo:

```bash
ssh root@192.168.0.208 'dbus -y | grep grid'
# expect: com.victronenergy.grid.mqtt_grid_100
```

If missing, see "dbus-mqtt-grid driver" recovery above.

## Known issues / gotchas

1. **Multi cold-starts in Bulk** and ignores ESS limits until reaching
   absorption voltage. Initial bulk after AC-in reconnect can pull
   2+ kWh from grid before ESS regains control. Workarounds:
   - Tighten `/Settings/SystemSetup/MaxChargeVoltage` to e.g. 55 V
     (DVCC will exit Bulk earlier — also better for LFP cycle life)
   - Or temporarily set `/Ac/ActiveIn/CurrentLimit` to 0 to halt the
     Multi entirely.

2. **USB/IP chain isn't persistent** across MK3 power cycles. Multi reboots
   power-cycle the MK3-USB-C (it's bus-powered from VE.Bus). Result: the
   kernel-side vhci-hcd attachment becomes stale, the Pi 5's bind drops.
   The `mk3-attach.sh` script handles re-establishment in one command.

3. **Cerbo's MQTT broker requires a non-empty username** even though the
   value is ignored. `umqtt.simple` on MicroPython tests `if self.user:`
   (truthy), so empty string silently fails auth. Use `"pico"` or any
   non-empty string. Documented in `firmware/pico-grid-meter/config.example.py`.

4. **VEConfigure 3 ignores its own absorption setting** when DVCC is on
   and the BMS reports `MaxChargeVoltage`. Yours says 58.4 V (3.65 V/cell);
   the Multi follows that, not the Assistant's 56.8 V default.

5. **Eddie VPN's iptables-legacy rules block `192.168.122.0/24`** (libvirt
   default network) outbound. The Win11 VM gets APIPA without a workaround.
   Fix: insert ACCEPT rules at the top of INPUT/FORWARD:

   ```bash
   sudo iptables-legacy -I INPUT 1 -i virbr0 -j ACCEPT
   sudo iptables-legacy -I FORWARD 1 -i virbr0 -j ACCEPT
   sudo iptables-legacy -I FORWARD 1 -o virbr0 -j ACCEPT
   ```

   These don't survive reboots — re-add or write a startup unit if needed.

6. **UK keyboard via QMP**: scancode for "backslash" produces `#` on UK
   layout, and `\` is on the LSGT (less-than) key. Encoded in
   `/tmp/qmp_keys.py` PLAIN/SHIFT maps if you ever need to re-drive
   the VM headlessly.

## What's verified vs not

- Verified: SDM120 readings → MQTT → dbus-mqtt-grid → ESS controller →
  Multi commands. Closed-loop charging from grid surplus (`MaxChargePower=0`
  prevents grid charging once Multi exits Bulk).
- Verified: VS-off, Grid code G98, ESS Assistant loaded, MinSoC 50%.
- Not verified: full-day behaviour cycle (charge from solar surplus, then
  discharge to AC-out loads, then reserve at 50%). Planned observation
  for 2026-05-08.
- Not verified: how the system behaves when the grid actually fails
  (UPS function is checked in VEConfigure but hasn't been tested by
  pulling the AC-in MCB).

## File map

| Path | Purpose |
|---|---|
| `~/bin/mk3-attach.sh` | One-shot USB/IP chain rebuild |
| `~/Code/victron-cerbo-mcp/` | This MCP + bridge code |
| `~/Code/victron-cerbo-mcp/bridge/pi-grid-meter/` | Pi 4 bridge service |
| `~/Code/victron-cerbo-mcp/firmware/pico-grid-meter/` | Pico firmware (parked, HW-519 was DOA) |
| `~/Code/victron-cerbo-mcp/tools/win11-vm-prep/` | Unattended Win11 install + VEConfigure setup |
| `/etc/systemd/system/grid-meter-bridge.service` (on Pi 4) | bridge systemd unit |
| `/data/etc/dbus-mqtt-grid/` (on Cerbo) | dbus-mqtt-grid driver |
| `/data/etc/dbus-mqtt-grid/config.ini` (on Cerbo) | broker host + topic + creds |
| `/var/lib/libvirt/images/autounattend.flp` | Floppy image with answer file |
| `/var/lib/libvirt/images/win11.qcow2` | Win11 VM disk |
| `/tmp/usb-mk3.xml` | libvirt hostdev definition for the FTDI |

## Credentials (NOT in repo)

Stored in:
- `~/.claude.json` → `mcpServers.victron-cerbo.env.CERBO_MQTT_PASSWORD` — Cerbo GUI/MQTT/SSH password
- `bridge/pi-grid-meter/bridge.env` (on Pi 4) — Cerbo MQTT password for bridge
- `firmware/pico-grid-meter/config.py` — Pico WiFi + MQTT (Pico is parked)
