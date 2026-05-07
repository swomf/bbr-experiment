#!/usr/bin/env python3
"""Extract receiver throughput from fairness experiment across all protocol versions.

The script scans matching experiment subdirectories under the 04-108-fairness-throughput
directory, reads each `iperf_sender.json`, and writes one CSV row per unique
(rtt, bandwidth, loss, buffer) configuration with receiver throughput for each protocol.

Each configuration (rtt, bw, loss, buf) is tested with 6 protocol versions:
- bbrv2, bbrv3, cubic, cubicvsbbrv2, cubicvsbbrv3, cubicvscubic
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROTOCOLS = ["bbrv2", "bbrv3", "cubic", "cubicvsbbrv2", "cubicvsbbrv3", "cubicvscubic"]


@dataclass(frozen=True)
class ThroughputData:
    receiver_mbps: float
    sender_mbps: float


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON file."""
    with path.open() as handle:
        return json.load(handle)


def summary_to_mbps(summary: dict[str, Any] | None) -> float:
    """Convert bits per second to megabits per second."""
    if not summary:
        return 0.0
    bits_per_second = summary.get("bits_per_second")
    if bits_per_second is None:
        return 0.0
    return float(bits_per_second) / 1e6


def extract_throughputs(json_path: Path) -> ThroughputData:
    """Extract sender and receiver throughput from iperf_sender.json."""
    data = load_json(json_path)
    end = data.get("end", {})

    sender_summary = end.get("sum_sent") or end.get("sum") or {}
    receiver_summary = end.get("sum_received") or end.get("receiver") or end.get("sum") or {}

    return ThroughputData(
        receiver_mbps=summary_to_mbps(receiver_summary),
        sender_mbps=summary_to_mbps(sender_summary),
    )


def extract_throughputs_multiflow(dir_path: Path) -> ThroughputData:
    """Extract throughput for flow A from a multi-flow experiment.

    Multi-flow experiments (e.g. cubicvsbbrv3) have two iperf files:
    - iperf_sender_a.json (flow A / left side of "vs")
    - iperf_sender_b.json (flow B / right side of "vs")

    For the CSV's *vs* columns, we report flow A throughput so
    `cubicvs...` reflects cubic's throughput.
    """
    a_path = dir_path / "iperf_sender_a.json"

    if not a_path.exists():
        return ThroughputData(receiver_mbps=0.0, sender_mbps=0.0)

    return extract_throughputs(a_path)


def collect_results(
    experiments_dir: Path,
) -> dict[tuple[int, int, int, str], dict[str, ThroughputData]]:
    """Collect throughput data for all experiments, organized by (rtt, bw, loss, buf).
    
    Returns:
        Dictionary mapping (rtt, bw, loss, buf) -> {protocol: ThroughputData}
    """
    results: dict[tuple[int, int, int, str], dict[str, ThroughputData]] = {}

    for subdir in sorted(experiments_dir.iterdir()):
        if not subdir.is_dir():
            continue
        
        # Parse directory name to extract parameters
        # Format: rtt<num>_bw<num>_loss<num>_buf<val>_<protocol>
        parts = subdir.name.split("_")
        if len(parts) < 5:
            continue
        
        try:
            # Extract base parameters from first 4 parts
            rtt = int(parts[0].replace("rtt", ""))
            bw = int(parts[1].replace("bw", ""))
            loss = int(parts[2].replace("loss", ""))
            buf = parts[3].replace("buf", "")
            # Protocol is everything after the 4th underscore
            protocol = "_".join(parts[4:])
        except (ValueError, IndexError):
            print(f"Warning: could not parse directory name: {subdir.name}", file=sys.stderr)
            continue

        key = (rtt, bw, loss, buf)
        
        if key not in results:
            results[key] = {}

        # Check if this is a multi-flow experiment (has "vs" in protocol name)
        if "vs" in protocol:
            # Multi-flow test with iperf_sender_a.json and iperf_sender_b.json
            throughput_data = extract_throughputs_multiflow(subdir)
        else:
            # Single-flow test with iperf_sender.json
            json_path = subdir / "iperf_sender.json"
            if not json_path.exists():
                print(f"Warning: iperf_sender.json not found in {subdir.name}", file=sys.stderr)
                continue
            throughput_data = extract_throughputs(json_path)

        results[key][protocol] = throughput_data

    return results


def format_float(value: float) -> str:
    """Format float to 6 decimal places."""
    return f"{value:.6f}"


def calculate_derived_metrics(protocols_data: dict[str, ThroughputData]) -> dict[str, float]:
    """Calculate derived metrics from protocol throughputs.
    
    Args:
        protocols_data: Dictionary mapping protocol name to ThroughputData
    
    Returns:
        Dictionary of derived metrics
    """
    metrics = {}
    
    # v3ImprovPcnt: (bbrv3 - bbrv2) / bbrv2
    if "bbrv2" in protocols_data and "bbrv3" in protocols_data:
        bbrv2_tput = protocols_data["bbrv2"].receiver_mbps
        bbrv3_tput = protocols_data["bbrv3"].receiver_mbps
        if bbrv2_tput > 0:
            metrics["v3ImprovPcnt"] = 100.0 * (bbrv3_tput - bbrv2_tput) / bbrv2_tput
        else:
            metrics["v3ImprovPcnt"] = None
    else:
        metrics["v3ImprovPcnt"] = None
    
    # v2Harm: (cubic - cubicvsbbrv2) / cubic
    if "cubic" in protocols_data and "cubicvsbbrv2" in protocols_data:
        cubic_tput = protocols_data["cubic"].receiver_mbps
        vs_v2_tput = protocols_data["cubicvsbbrv2"].receiver_mbps
        if cubic_tput > 0:
            metrics["v2Harm"] = (cubic_tput - vs_v2_tput) / cubic_tput
        else:
            metrics["v2Harm"] = None
    else:
        metrics["v2Harm"] = None
    
    # v3Harm: (cubic - cubicvsbbrv3) / cubic
    if "cubic" in protocols_data and "cubicvsbbrv3" in protocols_data:
        cubic_tput = protocols_data["cubic"].receiver_mbps
        vs_v3_tput = protocols_data["cubicvsbbrv3"].receiver_mbps
        if cubic_tput > 0:
            metrics["v3Harm"] = (cubic_tput - vs_v3_tput) / cubic_tput
        else:
            metrics["v3Harm"] = None
    else:
        metrics["v3Harm"] = None
    
    # cubicHarm: (cubic - cubicvscubic) / cubic
    if "cubic" in protocols_data and "cubicvscubic" in protocols_data:
        cubic_tput = protocols_data["cubic"].receiver_mbps
        vs_cubic_tput = protocols_data["cubicvscubic"].receiver_mbps
        if cubic_tput > 0:
            metrics["cubicHarm"] = (cubic_tput - vs_cubic_tput) / cubic_tput
        else:
            metrics["cubicHarm"] = None
    else:
        metrics["cubicHarm"] = None
    
    return metrics


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Extract receiver throughput from fairness experiments across all protocol versions"
    )
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--experiments-dir",
        type=Path,
        default=repo_root / "04-108-fairness-throughput",
        help="directory containing the fairness experiment subdirectories",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "out" / "fairness_throughput.csv",
        help="output CSV file path",
    )
    parser.add_argument(
        "--include-sender",
        action="store_true",
        help="also include sender throughput columns",
    )

    args = parser.parse_args()

    if not args.experiments_dir.is_dir():
        print(f"Error: experiments directory not found: {args.experiments_dir}", file=sys.stderr)
        return 1

    print(f"Scanning experiments in: {args.experiments_dir}", file=sys.stderr)
    results = collect_results(args.experiments_dir)

    if not results:
        print("Error: no experiments found", file=sys.stderr)
        return 1

    print(f"Found {len(results)} unique configurations", file=sys.stderr)

    # Prepare CSV headers
    headers = ["rtt", "bw", "loss", "buf"]
    if args.include_sender:
        for protocol in PROTOCOLS:
            headers.append(f"{protocol}_sender")
    for protocol in PROTOCOLS:
        headers.append(protocol)
    # Add derived metric columns
    headers.extend(["v3ImprovPcnt", "v2Harm", "v3Harm", "cubicHarm"])

    # Write CSV
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()

        for (rtt, bw, loss, buf), protocols_data in sorted(results.items()):
            row = {
                "rtt": rtt,
                "bw": bw,
                "loss": loss,
                "buf": buf,
            }

            # Add sender throughput if requested
            if args.include_sender:
                for protocol in PROTOCOLS:
                    if protocol in protocols_data:
                        row[f"{protocol}_sender"] = format_float(
                            protocols_data[protocol].sender_mbps
                        )
                    else:
                        row[f"{protocol}_sender"] = ""

            # Add receiver throughput
            for protocol in PROTOCOLS:
                if protocol in protocols_data:
                    row[protocol] = format_float(
                        protocols_data[protocol].receiver_mbps
                    )
                else:
                    row[protocol] = ""

            # Calculate and add derived metrics
            metrics = calculate_derived_metrics(protocols_data)
            for metric_name, metric_value in metrics.items():
                if metric_value is not None:
                    row[metric_name] = format_float(metric_value)
                else:
                    row[metric_name] = ""

            writer.writerow(row)

    print(f"CSV written to: {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
