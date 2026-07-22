#!/usr/bin/env bash
#
# Restore the KNOWN-GOOD ESS / DESS / feed-in configuration to the Cerbo.
#
# Captured 2026-07-22 and verified working by tools/sunny_check.py:
#   * store all self-generated energy (MaxChargePower = -1 soaks AC roof-PV
#     surplus into the battery, not just the DC MPPT)
#   * only feed the OVERFLOW to grid once the battery is at 100% SoC
#   * NEVER discharge the battery to the grid (DESS off + plain self-consumption)
#   * top the battery up to 100% from grid at 20:00 for overnight backup
#
# This only covers the Cerbo dbus settings. The MultiPlus-internal config
# (grid code, ESS assistant, sustain/absorption/float, capacity) lives in
# VEConfigure — see docs/RUNBOOK.md "ESS config lost" for that.
#
# Usage:
#   tools/restore-ess-config.sh              # apply to 192.168.0.208
#   CERBO=192.168.0.99 tools/restore-ess-config.sh
#
# Requires the root SSH key on the Cerbo (see RUNBOOK "Cerbo SSH lost").
#
# Re-capture a fresh snapshot after intentional changes with:
#   ssh root@<cerbo> 'for p in CGwacs/Hub4Mode CGwacs/MaxChargePower ...; do \
#     echo "$p=$(dbus -y com.victronenergy.settings /Settings/$p GetValue)"; done'
#
set -euo pipefail
CERBO="${CERBO:-192.168.0.208}"

echo "Restoring known-good ESS config to ${CERBO} (snapshot 2026-07-22)..."
echo "  setting                                          before -> after"

# `SetValue -- <n>` so negative sentinels (-1 = no limit, -7 = day disabled)
# aren't parsed as CLI options by the Cerbo's dbus wrapper.
ssh -o ConnectTimeout=10 "root@${CERBO}" 'sh -s' <<'REMOTE'
s=com.victronenergy.settings
set_val() {
  before=$(dbus -y $s /Settings/"$1" GetValue 2>/dev/null)
  dbus -y $s /Settings/"$1" SetValue -- "$2" >/dev/null 2>&1
  after=$(dbus -y $s /Settings/"$1" GetValue 2>/dev/null)
  printf '  %-48s %s -> %s\n' "$1" "$before" "$after"
}

# --- ESS core (Hub-4 self-consumption; never exports the battery) ---
set_val CGwacs/Hub4Mode                          2      # Optimised, phase comp disabled
set_val CGwacs/AcPowerSetPoint                   50     # +50 W import bias
set_val CGwacs/PreventFeedback                   1
set_val CGwacs/OvervoltageFeedIn                 0      # DC PV overvoltage feed-in off

# --- store all self-gen; feed in only the overflow at 100% ---
set_val CGwacs/MaxChargePower                    -1     # no limit: store AC-PV surplus too
set_val CGwacs/MaxFeedInPower                    -1     # no limit: overflow may export at 100%
set_val CGwacs/MaxDischargePower                 -1     # no limit

# --- reserve floor ---
set_val CGwacs/BatteryLife/MinimumSocLimit       20

# --- 20:00 end-of-day top-up to 100% for overnight backup (slot 0) ---
set_val CGwacs/BatteryLife/Schedule/Charge/0/Start     72000   # seconds since midnight = 20:00
set_val CGwacs/BatteryLife/Schedule/Charge/0/Duration  1800    # 30 min
set_val CGwacs/BatteryLife/Schedule/Charge/0/Soc       100
set_val CGwacs/BatteryLife/Schedule/Charge/0/Day       7       # every day
set_val CGwacs/BatteryLife/Schedule/Charge/1/Day       -7      # slots 1-4 disabled
set_val CGwacs/BatteryLife/Schedule/Charge/2/Day       -7
set_val CGwacs/BatteryLife/Schedule/Charge/3/Day       -7
set_val CGwacs/BatteryLife/Schedule/Charge/4/Day       -7

# --- Dynamic ESS OFF (it deliberately exports the battery; keep it off) ---
set_val DynamicEss/Mode                          0

# --- DVCC (battery BMS governs the actual limits) ---
set_val SystemSetup/MaxChargeCurrent             -1     # no system limit
set_val SystemSetup/MaxChargeVoltage             0      # 0 = BMS/DVCC decides
REMOTE

echo "Done. Verify: 'uv run python tools/sunny_check.py' (midday) or the RUNBOOK healthy-check."
