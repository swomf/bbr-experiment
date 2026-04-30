#!/usr/bin/env python3
"""Build a CSV comparing BBRv2 and BBRv3 iperf3 throughput results.

The script scans matching experiment subdirectories under the BBRv2 and BBRv3
trees, reads each `iperf_sender.json`, and writes one CSV row per shared
configuration.

The winner is the version with the higher sender throughput. If sender
throughputs are equal, receiver throughput is used as the tie-breaker.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_RE = re.compile(
    r"^rtt(?P<rtt>\d+)_bw(?P<bw>\d+)_loss(?P<loss>\d+)_buf(?P<buf>\d+)_bbr$"
)


@dataclass(frozen=True)
class ThroughputSummary:
    sender_mbps: float
    receiver_mbps: float


def parse_config_name(name: str) -> dict[str, int]:
    match = CONFIG_RE.match(name)
    if not match:
        raise ValueError(f"unrecognized experiment directory name: {name}")
    return {key: int(value) for key, value in match.groupdict().items()}


def load_json(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        return json.load(handle)


def summary_to_mbps(summary: dict[str, Any] | None) -> float:
    if not summary:
        return 0.0
    bits_per_second = summary.get("bits_per_second")
    if bits_per_second is None:
        return 0.0
    return float(bits_per_second) / 1e6


def extract_throughputs(json_path: Path) -> ThroughputSummary:
    data = load_json(json_path)
    end = data.get("end", {})

    sender_summary = end.get("sum_sent") or end.get("sum") or {}
    receiver_summary = end.get("sum_received") or end.get("receiver") or end.get(
        "sum"
    ) or {}

    return ThroughputSummary(
        sender_mbps=summary_to_mbps(sender_summary),
        receiver_mbps=summary_to_mbps(receiver_summary),
    )


def symmetric_percent_difference(left: float, right: float) -> float:
    average = (left + right) / 2.0
    if average == 0:
        return 0.0
    return abs(right - left) / average * 100.0


def relative_percent_difference(left: float, right: float) -> float:
    if left == 0:
        return 0.0
    return (right - left) / left * 100.0


def winner_from_throughputs(v2: ThroughputSummary, v3: ThroughputSummary) -> str:
    if v2.receiver_mbps > v3.receiver_mbps:
        return "bbrv2"
    if v3.receiver_mbps > v2.receiver_mbps:
        return "bbrv3"
    return "tie"


def collect_results(version_dir: Path) -> dict[tuple[int, int, int, int], tuple[Path, ThroughputSummary]]:
    results: dict[tuple[int, int, int, int], tuple[Path, ThroughputSummary]] = {}

    for json_path in version_dir.glob("*/iperf_sender.json"):
        config = parse_config_name(json_path.parent.name)
        key = (config["rtt"], config["bw"], config["loss"], config["buf"])
        results[key] = (json_path, extract_throughputs(json_path))

    return results


def format_float(value: float) -> str:
    return f"{value:.6f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare BBRv2 and BBRv3 sender/receiver throughput and write a CSV"
    )
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--bbrv2-dir",
        type=Path,
        default=repo_root / "out" / "01-180-bbrv2",
        help="directory containing the BBRv2 experiment subdirectories",
    )
    parser.add_argument(
        "--bbrv3-dir",
        type=Path,
        default=repo_root / "out" / "01-180-bbrv3",
        help="directory containing the BBRv3 experiment subdirectories",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "out" / "bbrv2_vs_bbrv3_throughput.csv",
        help="CSV output path",
    )
    args = parser.parse_args()

    if not args.bbrv2_dir.is_dir():
        print(f"missing BBRv2 directory: {args.bbrv2_dir}", file=sys.stderr)
        return 1
    if not args.bbrv3_dir.is_dir():
        print(f"missing BBRv3 directory: {args.bbrv3_dir}", file=sys.stderr)
        return 1

    bbrv2_results = collect_results(args.bbrv2_dir)
    bbrv3_results = collect_results(args.bbrv3_dir)

    shared_keys = sorted(set(bbrv2_results) & set(bbrv3_results))
    missing_v2 = sorted(set(bbrv3_results) - set(bbrv2_results))
    missing_v3 = sorted(set(bbrv2_results) - set(bbrv3_results))

    if missing_v2:
        print(
            f"warning: {len(missing_v2)} BBRv3 configurations have no BBRv2 match",
            file=sys.stderr,
        )
    if missing_v3:
        print(
            f"warning: {len(missing_v3)} BBRv2 configurations have no BBRv3 match",
            file=sys.stderr,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "rtt_ms",
        "bw_mbit",
        "loss_pct",
        "buf_bytes",
        "bbrv2_sender_mbps",
        "bbrv2_receiver_mbps",
        "bbrv3_sender_mbps",
        "bbrv3_receiver_mbps",
        "sender_diff_mbps",
        "sender_diff_pct",
        "receiver_diff_mbps",
        "receiver_diff_pct",
        "winner",
    ]

    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for rtt, bw, loss, buf in shared_keys:
            _, v2 = bbrv2_results[(rtt, bw, loss, buf)]
            _, v3 = bbrv3_results[(rtt, bw, loss, buf)]

            sender_diff = v3.sender_mbps - v2.sender_mbps
            receiver_diff = v3.receiver_mbps - v2.receiver_mbps

            writer.writerow(
                {
                    "rtt_ms": rtt,
                    "bw_mbit": bw,
                    "loss_pct": loss,
                    "buf_bytes": buf,
                    "bbrv2_sender_mbps": format_float(v2.sender_mbps),
                    "bbrv2_receiver_mbps": format_float(v2.receiver_mbps),
                    "bbrv3_sender_mbps": format_float(v3.sender_mbps),
                    "bbrv3_receiver_mbps": format_float(v3.receiver_mbps),
                    "sender_diff_mbps": format_float(sender_diff),
                    "sender_diff_pct": format_float(
                        relative_percent_difference(v2.sender_mbps, v3.sender_mbps)
                    ),
                    "receiver_diff_mbps": format_float(receiver_diff),
                    "receiver_diff_pct": format_float(
                        relative_percent_difference(v2.receiver_mbps, v3.receiver_mbps)
                    ),
                    "winner": winner_from_throughputs(v2, v3),
                }
            )

    print(f"wrote {len(shared_keys)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())