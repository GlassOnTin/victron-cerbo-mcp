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
                              │       [Pi 4 "grid-meter"]     │   │  ─AC-out: freezers, lighting,     │
                              │       (grid-meter.local       │   │           DC MPPT 150/35           │
                              │        wlan0, DHCP-reserved   │   │                                    │
                              │        to 192.168.0.99)       │   │                                    │
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
| Battery | 3× ECO-Worthy 48V 100Ah (≈300 Ah) | (in garage) | LiFePO4, **parallel** (since 2026-07-20), VE.Can; aggregates as `battery_512`, 3 modules. BMS on CAN (`battery.socketcan_vecan1`) |
| MPPT (DC) | SmartSolar 150/35 | (in garage) | DC-coupled, on VE.Direct |
| Grid meter | Eastron SDM120CT-M | house CU | 9600 8N1, addr 1, CT on L tail |
| Pi 4 (`grid-meter`, was `3dprinter` before 2026-05-09) | Raspberry Pi 4 | `grid-meter.local` (WiFi); DHCP-reserved to 192.168.0.99 in FritzBox | runs `grid-meter-bridge.service` + USB-RS485 to SDM120 |
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
# expect (from 2026-07-21): Hub4Mode=2, MaxChargePower=-1, MaxFeedInPower=-1, MinSoC=20;
#         DESS off. See "Grid feed-in & battery-export policy". (Was: MaxChargePower=0,
#         MaxFeedInPower=0, MinSoC=50 on the 2026-05-07 baseline.)

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

> **Partly superseded 2026-07-21** — MinSoC 50→20, MaxChargePower 0→−1,
> MaxFeedInPower 0→−1, and DESS was trialled then disabled. The table below is
> the original 2026-05-07 baseline; see **"Grid feed-in & battery-export
> policy"** for the current values and why they changed.

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
| Sustain V | 48.00 V (3.00 V/cell × 16S; was 50.00 V before 2026-05-09) |
| Absorption V (overridden by BMS DVCC to 58.4 V) | 56.80 V |
| Float V | 54.00 V |
| Virtual switch | **Off** (was "dedicated ignore AC input" pre-ESS) |
| PowerAssist | unchecked (ESS replaces it) |
| Lithium batteries | checked |

## Grid feed-in & battery-export policy (updated 2026-07-21)

**Rule: never export the *battery* to the grid. Store all self-generated
energy; only feed in the overflow once the battery is at 100 % SoC, then top up
to full from the grid at day's end for overnight backup.**

Current settings (these supersede the 2026-05-07 table where they differ):

| Setting (`/Settings/…`) | Value | Why |
|---|---|---|
| `DynamicEss/Mode` | **0 (Off)** | DESS exported the battery to grid — see below |
| `CGwacs/Hub4Mode` | 2 (Optimised self-consumption) | never discharges battery past the grid setpoint, so it *cannot* dump battery to grid |
| `CGwacs/MaxChargePower` | **−1 (no limit)** | store **AC-coupled roof-PV surplus**, not just the DC MPPT. Was 0, which capped AC-side charging so roof surplus spilled to grid instead of the battery |
| `CGwacs/MaxFeedInPower` | −1 (no limit) | allow the *overflow* to export once the battery is full ("only feed in at 100 %") |
| `CGwacs/BatteryLife/MinimumSocLimit` | 20 % | reserve floor (was 50) |
| `CGwacs/BatteryLife/Schedule/Charge/0` | **20:00**, 30 min, →100 %, every day | end-of-day grid top-up for full overnight backup. Set **late** (was 15:00) so solar fills the battery for free first; the schedule then only tops up what solar didn't finish. Start is **seconds since midnight** (72000 = 20:00) |

### DESS (Dynamic ESS) dumped the battery to the grid — 2026-07-21

Enabling DESS ("Auto / VRM") makes it the ESS controller, and it will
**deliberately discharge the battery to the grid** during favourable price
windows — that is its whole purpose. Plain ESS self-consumption never does this
(it stops at the grid setpoint), so **DESS is the only thing in this system that
exports the battery.** If the battery must never reach the grid, don't run DESS.

Gotcha that cost us an hour: **turning DESS off in the VRM portal does NOT
disable the Cerbo's local mode.** The authoritative off switch is the Cerbo's
own `/Settings/DynamicEss/Mode` (Settings → DynamicESS → Mode → Off). Verify
both the setting and that it actually stopped controlling:

```bash
ssh root@192.168.0.208 'dbus -y com.victronenergy.settings /Settings/DynamicEss/Mode GetValue'  # 0 = off
# MCP: metric system_dynamicess_active must read "Off" (not just the mode field)
```

### Verifying "no battery to grid"

With **PV = 0** (night), the battery should discharge only to cover local loads
while the grid meter reads a small **positive** (≈ +50 W import, the setpoint).
If the grid reads **negative (export) while the battery is discharging**, that's
a battery dump — check DESS is off. `MaxFeedInPower = −1` still lets *solar*
surplus export at 100 % SoC; that is intended here (set it to 0 for zero export
of any kind).

### NOT yet verified (needs sun)

- That AC-coupled roof-PV surplus now charges the battery **before** any export
  (the point of the `MaxChargePower −1` change). Check on a sunny day with the
  battery < 100 %.
- That no grid-charge fires before the 20:00 schedule.
- `PreventFeedback` current value was not read this session — confirm it doesn't
  block the intended overflow-solar export.

### Commands used (dbus over SSH, 2026-07-21)

```bash
ssh root@192.168.0.208 '
  dbus -y com.victronenergy.settings /Settings/DynamicEss/Mode SetValue 0
  dbus -y com.victronenergy.settings /Settings/CGwacs/MaxChargePower SetValue -- -1
  dbus -y com.victronenergy.settings /Settings/CGwacs/BatteryLife/Schedule/Charge/0/Start SetValue 72000
'
```

> The Cerbo `dbus` CLI parses a bare `-1` as an option — pass negatives as
> `SetValue -- -1`. Schedule Start/Duration are **seconds since midnight**.

## Anti-islanding / grid-loss behaviour

**Two separate layers — don't conflate them.**

### Layer 1: anti-islanding (safety, hardware)

Done by the **MultiPlus**, not the Cerbo. The Cerbo can't be in this loop —
anti-islanding has to react in tens of milliseconds and survive the Cerbo
crashing or being unplugged. UK grid codes require this at the inverter.

How it actually works when the grid drops to 0 V (or out-of-spec):

1. The Multi continuously monitors AC-In voltage / frequency / RoCoF
   against the grid-code thresholds (UK G98/1 March 2019: ~207–253 V,
   ~47–52 Hz, plus rate-of-change-of-frequency limits).
2. On out-of-spec, the Multi **opens its internal transfer relay within
   ~20 ms**. AC-In is now physically isolated from AC-Out.
3. The inverter switches on and powers AC-Out from the battery.
4. The relay stays open until AC-In is back AND stable for the reconnect
   time (~60 s for G98).

Net effect: zero possibility of energising a dead grid line, regardless
of what the Cerbo, ESS controller, or even the user is doing. AC-Out
keeps running (UPS function) down to `MinimumSocLimit = 50 %`, then
sustain at 48 V.

### Layer 2: feed-in policy (Cerbo / ESS settings)

These are **policy, not safety** — they belt-and-braces the "don't push
power upstream" intent under normal grid-up conditions. Pull the Cerbo
out and they go away, but Layer 1 still works.

| Setting | Value | Effect |
|---|---|---|
| `PreventFeedback` | 1 | Cerbo won't command the Multi to feed in |
| `MaxFeedInPower` | 0 W | Even if commanded, no power |
| `MaxChargePower` | 0 W | No grid-charging either |
| `AcPowerSetPoint` | +50 W | Slight import bias so noise/lag don't pulse-export |

These don't help during a partial grid event the Multi accepts as valid
(e.g. a brown-out at 200 V that's still in-spec, or frequency shifts the
Multi rides through). For those you're trusting the grid-code firmware
in the Multi alone.

### Verifying it's actually wired up

```bash
# Grid code on the Multi — set by VEConfigure, password-locked after first send
ssh root@192.168.0.208 'dbus -y com.victronenergy.vebus.ttyS4 /Settings/Devices/0/GridCodeStandard GetValue 2>&1'

# Live AC-In state (1 = grid connected through transfer relay; 0 = isolated)
ssh root@192.168.0.208 'dbus -y com.victronenergy.vebus.ttyS4 /Ac/ActiveIn/Connected GetValue'

# AC-In voltage / frequency the Multi sees right now
ssh root@192.168.0.208 'dbus -y com.victronenergy.vebus.ttyS4 /Ac/ActiveIn/L1/V GetValue'
ssh root@192.168.0.208 'dbus -y com.victronenergy.vebus.ttyS4 /Ac/ActiveIn/L1/F GetValue'
```

### Tested vs not

- Verified: grid-code G98/1 + G99/1 written to the Multi (locked at first
  ESS send, 2026-05-07).
- Verified: `PreventFeedback`/`MaxFeedInPower`/`MaxChargePower` all 0/1
  per the ESS configuration table above.
- **NOT verified**: actual relay opening on grid loss. To test, pull the
  AC-In MCB at the garage CU and confirm AC-Out stays powered from
  battery (lights, freezer) without flicker. Planned but not done.

## Recovery procedures

### E-stop test / full DC disconnect recovery (3-pack stack)

As of 2026-07-20 the bank is **3× ECO-Worthy 48V 100Ah** (≈300 Ah) wired in
parallel, each pack behind its own breaker fed through a common **emergency
stop**. Each pack now talks to the Cerbo over **VE.Can (Victron protocol)** and
presents as one aggregated battery (`battery_512`, `NrOfModulesOnline = 3`).
Min SoC is now **20 %**; DESS was enabled 2026-07-20 then **disabled
2026-07-21** after it exported battery to the grid (see "Grid feed-in &
battery-export policy").

Pressing the E-stop (or any full DC disconnect) trips each pack's breaker **in
sequence** and de-energises the whole DC bus. The **Cerbo is powered from that
bus**, so it loses power too: it goes fully off the network, the broker dies,
and the MCP returns `bridge is offline … supervisor is recovering`. **This is
expected, not a fault** — nothing on the DC side comes back until the bus is
manually re-energised.

Recovery:

1. **Release the E-stop** (twist/pull to unlatch).
2. **Re-close each pack's battery breaker** — they tripped in sequence; close
   them to re-energise the bus.
3. The Cerbo re-powers and boots (~1–2 min), returning at 192.168.0.208
   (DHCP-reserved, MAC `80:9d:65:7b:5a:18`).
4. The MCP **self-heals** — the bridge supervisor rebuilds the hub automatically
   once the Cerbo answers again; **no manual `/mcp` reconnect needed** (post
   2026-07-20 bridge; older builds get stuck all-null and do need a reconnect).

Tell "still booting" apart from "still unpowered":

```bash
ping -c2 192.168.0.208 && \
  (timeout 3 bash -c 'cat </dev/null >/dev/tcp/192.168.0.208/8883' && echo '8883 open')
```

- No reply / no route for **more than ~2 min** = still **unpowered**: the E-stop
  is still latched or a breaker is still open. A healthy Cerbo is back on the
  network within 1–2 min of power. (Seen 2026-07-20: bank left dark ~25 min
  because the physical reset hadn't been done yet — nothing recovers until it is.)

All-clear checklist (verified 2026-07-20 via MCP `list_metrics`, device `battery_512`):

| Signal | Expect |
|---|---|
| `battery_nr_modules_online` | **3** (all packs back) |
| `battery_nr_modules_offline` | 0 |
| `battery_nr_modules_blocking_charge` / `_discharge` | 0 / 0 |
| `battery_cell_imbalance` | No alarm |
| `battery_internal_failure` | No alarm |
| system `active_alarms` | empty |
| SOC / bank voltage | sane (e.g. 100 % / ~56.5 V) |

On-Cerbo equivalent (find the battery service first, name may vary):

```bash
ssh root@192.168.0.208 'dbus -y | grep battery'   # e.g. com.victronenergy.battery.socketcan_vecan1
ssh root@192.168.0.208 'dbus -y com.victronenergy.battery.<svc> /System/NrOfModulesOnline GetValue'  # expect 3
```

**Aggregate cell delta after paralleling — don't misread it.** With 3
independently-BMS'd packs on one bus, the reported min/max cell voltage spans
*different packs* (max cell in one pack, min in another), so a wide aggregate
spread (~170 mV seen 2026-07-20, min in pack 02 / max in pack 01) is **normal
and not a per-pack imbalance**. Each pack balances itself; the pack-to-pack
figure will NOT shrink to a single pack's ~15 mV. The real signal is the BMS
`CellImbalance` alarm, not the raw min/max delta.

### Pi 4 grid bridge stopped publishing

```bash
ssh ian@grid-meter.local 'sudo systemctl restart grid-meter-bridge.service'
ssh ian@grid-meter.local 'sudo journalctl -u grid-meter-bridge -n 20 --no-pager'
```

If `grid-meter.local` doesn't resolve (mDNS broken / avahi off), locate it via the FritzBox:

```bash
nslookup grid-meter.fritz.box 192.168.0.1   # was 3dprinter.fritz.box pre-2026-05-09
# DHCP reservation: dc:a6:32:ba:34:1a → 192.168.0.99
```

Common cause: hourly `killall python` cron killed it. We removed the offending crontab entry on 2026-05-07; if it ever returns, check root's crontab on the Pi 4:

```bash
ssh ian@grid-meter.local 'sudo crontab -l'
# the dangerous line was:
#   0 * * * * /usr/bin/killall python && /usr/sbin/service picamera2-webstream restart
```

### Bridge auth fails with `rc=Not authorized` (after Cerbo password change)

The bridge connects to the Cerbo broker on 192.168.0.208:8883/TLS with
username `pi-bridge` and **the Cerbo Remote Console password** as the
MQTT password. There is no separate "MQTT account" — the Cerbo broker
just accepts any non-empty username + the Remote Console password.

So whenever the Cerbo Remote Console password is rotated (e.g. when you
enable root SSH for the first time and Venus forces a new password),
`MQTT_PASSWORD` in the bridge's env file becomes stale and ESS reports
**"#49 Grid meter not found"**. Symptom in the bridge journal:

```
INFO grid-meter-bridge mqtt connected: rc=Not authorized
WARNING grid-meter-bridge mqtt disconnected: rc=Unspecified error
WARNING grid-meter-bridge publish enqueue failed   (repeating)
```

…and on the Cerbo:

```
INFO:root:Waiting since 60 seconds for receiving first data...
ERROR:root:Driver stopped. Timeout of 60 seconds exceeded...
```

Fix in **three** places after a password change:

1. Pi 4 bridge (then restart):

   ```bash
   ssh ian@grid-meter.local 'sudo sed -i "s|^MQTT_PASSWORD=.*|MQTT_PASSWORD=<NEW>|" /home/ian/grid-meter-bridge/bridge.env'
   ssh ian@grid-meter.local 'sudo systemctl restart grid-meter-bridge'
   ssh ian@grid-meter.local 'sudo journalctl -u grid-meter-bridge -n 5 --no-pager'  # expect rc=Success
   ```

2. Workstation MCP config:

   ```bash
   # ~/.claude.json → mcpServers.victron-cerbo.env.CERBO_MQTT_PASSWORD
   ```

3. The Cerbo itself (Settings → General → Remote Console password) — already done if this is what triggered the rotation.

After step 1, verify the chain came back:

```bash
ssh root@192.168.0.208 'dbus -y | grep grid'
# expect: com.victronenergy.grid.mqtt_grid_100
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

VEConfigure 3 in the Win11 VM, with USB/IP attached.

> **CRITICAL — battery-back the upload chain before you click Send.**
> "Send settings" / "Send assistant setup" power-cycles the Multi for
> 20–60 s. The garage Pi 5 (`192.168.0.234`) **and** the garage router
> are both on AC-Out — they go dark mid-send, the usbip session breaks,
> and the Multi can be left half-flashed. Before clicking Send:
>
> - Plug the Pi 5 into a USB power bank (verified survives the outage).
> - Switch the usbip session onto the Pi 5's wlan0 IP (via UpperPiano2),
>   not eth0 via the garage router. Re-bind on Pi 5
>   (`usbip bind -b 3-1`), re-attach on host
>   (`sudo usbip attach -r <wlan-ip> -b 3-1`), then
>   `virsh detach-device / attach-device` the FTDI hostdev so Windows
>   re-recognises COM3 as OK.
> - Don't disturb anything in the chain (ssh, virt-viewer, USB) until
>   the Multi reports "Send completed".
>
> If something goes wrong mid-flash, recover via VEConfigure's
> **Repair assistant installation** button (sidebar of the Assistants
> tab), or re-send a known-good `.RVMS` file you saved before starting.

1. Run `~/bin/mk3-attach.sh`
2. Open VEConfigure 3 in the VM (via virt-viewer)
3. Port selection → Com port → COM3
4. Grid tab → set **UK: G98/1 March 2019, G99/1 May 2018**
5. Assistants tab → Add → Solar / Self-consumption → ESS
6. Start assistant, walk through with these answers:
   - Battery: **LiFePo4 with other type BMS**
   - Capacity: **100 Ah**
   - Change battery type: **as suggested**
   - Sustain V: **48.0 V** (3.00 V/cell × 16S; well above EcoWorthy BMS LV cut-off ~40–44 V)
   - Cut-off curve: 47.0 / 46.0 / 44.0 / 42.0 V at 0.005C / 0.25C / 0.7C / 2C (Victron defaults)
   - Restart offset: **1.20 V**
   - PV inverters on AC out: **No**
7. Send settings → modified → OK (with battery-backup checks above)
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
