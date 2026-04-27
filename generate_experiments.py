#!/usr/bin/env python3
"""Generate the Cartesian product of experiment parameters."""

import csv
import itertools

RTT_MS = [10, 100]
BW_MBIT = [25, 50, 100, 300, 500, 1000]
BUF_BYTES = [100_000, 2_000_000, 10_000_000, 50_000_000, 100_000_000]
LOSS_PCT = [0, 1, 2]
CC = ["bbr"]

rows = list(itertools.product(RTT_MS, BW_MBIT, BUF_BYTES, LOSS_PCT, CC))

with open("experiments.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["rtt_ms", "bw_mbit", "buf_bytes", "loss_pct", "cc"])
    w.writerows(rows)

print(f"Generated {len(rows)} experiments --> experiments.csv")
