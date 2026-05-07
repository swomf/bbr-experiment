#!/usr/bin/env python3
"""Generate the Cartesian product of experiment parameters."""

import csv
import itertools

RTT_MS = [10, 50, 100]
BW_MBIT = [100]
BUF_BDP_RATIOS = [0.1, 1.0, 10.0]
LOSS_PCT = [0, 2]
# (cc_a, cc_b): cc_b="" means single-stream; cubic is always listed first in pairs
COMPARISONS = [
    # ("cubic", ""),
    # ("bbrv2", ""),  # run afterwards
    ("bbrv3", ""),
    # ("cubic", "cubic"),
    # ("cubic", "bbrv2"),  # run afterwards
    ("cubic", "bbrv3"),
]
# NOTE: bbrv2, bbrv3 are replaced with just "bbr" when the actual iperf call is used

rows = [
    (rtt, bw, buf, loss, cc_a, cc_b)
    for rtt, bw, buf, loss, (cc_a, cc_b) in itertools.product(
        RTT_MS, BW_MBIT, BUF_BDP_RATIOS, LOSS_PCT, COMPARISONS
    )
]

with open("experiments.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["rtt_ms", "bw_mbit", "buf_bdp_ratio", "loss_pct", "cc_a", "cc_b"])
    w.writerows(rows)

print(f"Generated {len(rows)} experiments --> experiments.csv")
