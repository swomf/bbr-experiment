#!/bin/bash
#
# emulate a bottleneck router for BBR/CUBIC experiments w/ tc
#
# Usage:
#   sudo ./shape.sh <RTT_ms> <bandwidth_mbit> <loss_percent> <buffer_bytes>
#
# Examples:
#   sudo ./shape.sh 100 100 2 2000000      # 100ms RTT, 100Mbps, 2% loss, 2MB buffer
#   sudo ./shape.sh 10 25 0 100000         # 10ms RTT, 25Mbps, no loss, 100KB buffer
#   sudo ./shape.sh 100 500 1 10000000     # 100ms RTT, 500Mbps, 1% loss, 10MB buffer
#
# Loss is applied on the forward path only (data path), not on ACKs.
# Both directions are rate-limited and buffered symmetrically (see northwestern paper)
# For interface names -- edit ifaces.conf

set -e

source "$(dirname "$0")/ifaces.conf"

if [ "$#" -ne 4 ]; then
  cat <<EOF
Usage: $0 <RTT_ms> <bandwidth_mbit> <loss_percent> <buffer_bytes>

Arguments:
  RTT_ms          Total round-trip time in ms (split evenly across directions)
                  Paper values: 10, 100
  bandwidth_mbit  Bottleneck bandwidth in Mbps
                  Paper values: 25, 50, 100, 300, 500, 1000
  loss_percent    Forward-path loss percentage (0 for no loss)
                  Paper values: 0, 1, 2
  buffer_bytes    Bottleneck buffer size in bytes
                  Paper values: 100000, 2000000, 10000000, 50000000, 100000000

Examples:
  $0 100 100 2 2000000     # 100ms, 100Mbps, 2% loss, 2MB buffer
  $0 10 25 0 100000        # 10ms, 25Mbps, no loss, 100KB buffer
EOF
  exit 1
fi

RTT_MS=$1
BW_MBIT=$2
LOSS_PCT=$3
BUFFER_BYTES=$4

# === SAFETY CHECKS ===

if [ "$EUID" -ne 0 ]; then
  echo "ERROR: must be run as root (use sudo)" >&2
  exit 1
fi

if ! ip link show "$IFACE_FWD" >/dev/null 2>&1; then
  echo "ERROR: interface $IFACE_FWD does not exist" >&2
  echo "Edit IFACE_FWD at the top of this script." >&2
  echo "Available interfaces:" >&2
  ip -br link show >&2
  exit 1
fi

if ! ip link show "$IFACE_REV" >/dev/null 2>&1; then
  echo "ERROR: interface $IFACE_REV does not exist" >&2
  echo "Edit IFACE_REV at the top of this script." >&2
  exit 1
fi

# === DERIVED VALUES ===

# Half-RTT one-way delay applied to each direction
HALF_RTT=$(awk "BEGIN {printf \"%.2f\", $RTT_MS / 2}")

# Convert byte-buffer to packet-limit assuming 1500-byte MTU
# Round up to ensure we don't undersize the buffer
PKT_LIMIT=$(awk "BEGIN {printf \"%d\", int(($BUFFER_BYTES + 1499) / 1500)}")

# Pick burst size: scale with rate so low-rate runs (10-25 Mbps) don't suffer
# from too-small a burst, and high-rate runs don't get bursty artifacts.
# Rule of thumb: burst ~= 1ms of data at the configured rate, min 2 KB, max 64 KB.
BURST_BYTES=$(awk "BEGIN {
    b = ($BW_MBIT * 1000000 / 8) / 1000;  # bytes per 1ms at rate
    if (b < 2000) b = 2000;
    if (b > 65536) b = 65536;
    printf \"%d\", b;
}")

# === BANNER ===

cat <<EOF
========== Traffic shaping configuration ==========
  Total RTT:    ${RTT_MS} ms (${HALF_RTT} ms each direction)
  Bandwidth:    ${BW_MBIT} Mbps (both directions)
  Loss:         ${LOSS_PCT}% (forward path only)
  Buffer:       ${BUFFER_BYTES} bytes (~${PKT_LIMIT} packets at 1500B MTU)
  Burst:        ${BURST_BYTES} bytes (≈1ms at rate)
  Forward iface: ${IFACE_FWD} (egress to receiver)
  Reverse iface: ${IFACE_REV} (egress to sender)
===================================================
EOF

# === RESET ANY EXISTING SHAPING ===

tc qdisc del dev "$IFACE_FWD" root 2>/dev/null || true
tc qdisc del dev "$IFACE_REV" root 2>/dev/null || true

# === FORWARD PATH (sender -> receiver) ===
# Two-layer stack: htb (rate) -> netem (delay + loss + tail-drop buffer via limit)

# Forward path
tc qdisc add dev "$IFACE_FWD" root handle 1: htb default 10
tc class add dev "$IFACE_FWD" parent 1: classid 1:10 \
  htb rate "${BW_MBIT}mbit" ceil "${BW_MBIT}mbit" burst "${BURST_BYTES}b"
tc qdisc add dev "$IFACE_FWD" parent 1:10 handle 10: \
  netem delay "${HALF_RTT}ms" loss "${LOSS_PCT}%" limit "$PKT_LIMIT"

# Reverse path
tc qdisc add dev "$IFACE_REV" root handle 1: htb default 10
tc class add dev "$IFACE_REV" parent 1: classid 1:10 \
  htb rate "${BW_MBIT}mbit" ceil "${BW_MBIT}mbit" burst "${BURST_BYTES}b"
tc qdisc add dev "$IFACE_REV" parent 1:10 handle 10: \
  netem delay "${HALF_RTT}ms" limit "$PKT_LIMIT"

# === VERIFICATION ===

echo ""
echo "===== Forward path: $IFACE_FWD ====="
tc -s qdisc show dev "$IFACE_FWD"
echo ""
echo "===== Reverse path: $IFACE_REV ====="
tc -s qdisc show dev "$IFACE_REV"
echo ""

echo "Shaping applied successfully."
echo ""
echo "Verify expected RTT from sender:"
echo "    ping -c 5 172.16.2.2     # should show RTT ≈ ${RTT_MS} ms"
echo ""
echo "To clear shaping later:"
echo "    sudo tc qdisc del dev $IFACE_FWD root"
echo "    sudo tc qdisc del dev $IFACE_REV root"

# ensure tc is applied
sleep 1
