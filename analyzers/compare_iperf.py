#!/usr/bin/env python3
"""
compare two iperf3 sender json outputs as matplotlib graph
do uv run ./analyzers/compare_iperf.py file1.json --label file1 file2.json --label file2
"""

import json
import sys
import argparse
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker


def load_iperf_json(path):
    with open(path) as f:
        data = json.load(f)

    intervals = data.get("intervals", [])
    times, bandwidth, retransmits = [], [], []

    for iv in intervals:
        sender = iv.get("sum", {})
        # fall back to streams[0] if sum is missing
        if not sender:
            streams = iv.get("streams", [])
            sender = streams[0] if streams else {}

        start = sender.get("start", None)
        bits_per_second = sender.get("bits_per_second", None)
        retrans = sender.get("retransmits", None)

        if start is not None and bits_per_second is not None:
            times.append(start)
            # Convert to Mbps
            bandwidth.append(bits_per_second / 1e6)
            retransmits.append(retrans)

    return times, bandwidth, retransmits, data


def format_summary(data, label):
    end = data.get("end", {})
    sender = end.get("sum_sent", end.get("sum", {}))
    bps = sender.get("bits_per_second", 0)
    retrans = sender.get("retransmits", "N/A")
    duration = sender.get("seconds", "?")
    return f"{label}: {bps/1e6:.1f} Mbps avg, {retrans} retransmits, {duration:.1f}s"


def main():
    parser = argparse.ArgumentParser(description="compare two iperf3 sender JSON files")
    parser.add_argument("file1", help="iperf3 json file #1")
    parser.add_argument("file2", help="iperf json file #2")
    parser.add_argument(
        "--label1", default=None, help="label for file1 (default: filename)"
    )
    parser.add_argument(
        "--label2", default=None, help="label for file2 (default: filename)"
    )
    parser.add_argument(
        "--out", default=None, help="output PNG path (default: show interactively)"
    )
    args = parser.parse_args()

    label1 = args.label1 or args.file1
    label2 = args.label2 or args.file2

    t1, bw1, rt1, data1 = load_iperf_json(args.file1)
    t2, bw2, rt2, data2 = load_iperf_json(args.file2)

    has_retransmits = any(r is not None for r in rt1 + rt2)

    fig, axes = plt.subplots(
        2 if has_retransmits else 1,
        1,
        figsize=(12, 7 if has_retransmits else 4.5),
        sharex=True,
    )
    if not has_retransmits:
        axes = [axes]

    fig.suptitle("iperf3 Sender Comparison", fontsize=14, fontweight="bold")

    # bandwidth plot
    ax_bw = axes[0]
    ax_bw.plot(
        t1, bw1, label=label1, linewidth=2, color="#2196F3", marker="o", markersize=3
    )
    ax_bw.plot(
        t2,
        bw2,
        label=label2,
        linewidth=2,
        color="#FF5722",
        marker="o",
        markersize=3,
        linestyle="--",
    )
    ax_bw.set_ylabel("Throughput (Mbps)", fontsize=11)
    ax_bw.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.0f"))
    ax_bw.legend(loc="upper right", fontsize=9)
    ax_bw.grid(True, linestyle="--", alpha=0.5)
    ax_bw.set_title("Throughput per Interval", fontsize=11)

    # annotate averages
    avg1 = sum(bw1) / len(bw1) if bw1 else 0
    avg2 = sum(bw2) / len(bw2) if bw2 else 0
    ax_bw.axhline(avg1, color="#2196F3", linestyle=":", alpha=0.6, linewidth=1)
    ax_bw.axhline(avg2, color="#FF5722", linestyle=":", alpha=0.6, linewidth=1)

    # retransmits plot (should not show up in loss 0)
    if has_retransmits:
        ax_rt = axes[1]
        clean_rt1 = [r if r is not None else 0 for r in rt1]
        clean_rt2 = [r if r is not None else 0 for r in rt2]
        ax_rt.bar(
            [t - 0.2 for t in t1],
            clean_rt1,
            width=0.4,
            label=label1,
            color="#2196F3",
            alpha=0.7,
        )
        ax_rt.bar(
            [t + 0.2 for t in t2],
            clean_rt2,
            width=0.4,
            label=label2,
            color="#FF5722",
            alpha=0.7,
        )
        ax_rt.set_ylabel("Retransmits", fontsize=11)
        ax_rt.set_xlabel("Time (s)", fontsize=11)
        ax_rt.legend(loc="upper right", fontsize=9)
        ax_rt.grid(True, linestyle="--", alpha=0.5, axis="y")
        ax_rt.set_title("TCP Retransmits per Interval", fontsize=11)
    else:
        axes[0].set_xlabel("Time (s)", fontsize=11)

    # foot
    summary = "\n".join(
        [
            format_summary(data1, label1),
            format_summary(data2, label2),
        ]
    )
    fig.text(
        0.5,
        0.01,
        summary,
        ha="center",
        fontsize=9,
        color="#555",
        family="monospace",
        bbox=dict(boxstyle="round", facecolor="#f5f5f5", alpha=0.8),
    )

    plt.tight_layout(rect=[0, 0.07, 1, 1])

    if args.out:
        plt.savefig(args.out, dpi=150, bbox_inches="tight")
        print(f"Saved to {args.out}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
