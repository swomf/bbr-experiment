#!/usr/bin/env python3
"""Generate the Cartesian product of experiment parameters."""

import csv
import itertools

RTT_MS = [100]
BW_MBIT = [500]
BUF_BYTES = [6250000 // 10, 6250000, 6250000 * 10]
LOSS_PCT = [0, 1, 2]
# the cc column is only used in single stream iperf
CC = ["bbr"]

rows = list(itertools.product(RTT_MS, BW_MBIT, BUF_BYTES, LOSS_PCT, CC))

with open("experiments.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["rtt_ms", "bw_mbit", "buf_bytes", "loss_pct", "cc"])
    w.writerows(rows)

print(f"Generated {len(rows)} experiments --> experiments.csv")
