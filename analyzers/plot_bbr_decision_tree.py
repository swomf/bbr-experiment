#!/usr/bin/env python3
"""Train and plot a decision tree from the BBR comparison CSV.

The plot uses sklearn's default class color coding, shows readable feature
labels, and annotates each branch with the actual split direction.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt


FEATURE_NAMES = ["Loss (%)", "RTT (ms)", "Bandwidth (Mbps)", "Buffer (MB)"]
CLASS_NAMES = ["BBRv2", "BBRv3"]


def read_csv(path: Path) -> tuple[list[list[float]], list[str]]:
    features: list[list[float]] = []
    labels: list[str] = []

    with path.open() as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                loss = float(row["loss_pct"])
                rtt = float(row["rtt_ms"])
                bw = float(row["bw_mbit"])
                buf_mb = float(row["buf_bytes"]) / (1024.0 * 1024.0)
            except Exception:
                continue

            features.append([loss, rtt, bw, buf_mb])
            labels.append(row["winner"].strip())

    return features, labels


def format_threshold(feature_index: int, threshold: float) -> str:
    if feature_index == 0:
        return f"{threshold:.2f}%"
    if feature_index == 1:
        return f"{threshold:.2f} ms"
    if feature_index == 2:
        return f"{threshold:.2f} Mbps"
    return f"{threshold:.2f} MB"


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot a BBRv2 vs BBRv3 decision tree")
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--csv",
        type=Path,
        default=repo_root / "out" / "bbrv2_vs_bbrv3_throughput.csv",
        help="comparison CSV path",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=3,
        help="maximum tree depth (default: 3)",
    )
    parser.add_argument(
        "--min-samples-leaf",
        type=int,
        default=4,
        help="minimum samples per leaf (default: 4)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=repo_root / "out" / "bbr_decision_tree.png",
        help="output PNG path",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"missing CSV: {args.csv}", file=sys.stderr)
        return 1

    try:
        from sklearn.tree import DecisionTreeClassifier, plot_tree
    except Exception:
        print("scikit-learn is required. Install with: pip install scikit-learn", file=sys.stderr)
        return 2

    X, y = read_csv(args.csv)
    if not X:
        print("no data found in CSV", file=sys.stderr)
        return 1

    clf = DecisionTreeClassifier(
        max_depth=args.max_depth,
        min_samples_leaf=args.min_samples_leaf,
        random_state=42,
    )
    clf.fit(X, y)

    # Print feature importances and tree structure
    print("\n=== Feature Importances ===")
    for fname, importance in zip(FEATURE_NAMES, clf.feature_importances_):
        print(f"  {fname:20s}: {importance:.4f}")

    print("\n=== Tree Text Representation ===")
    from sklearn.tree import export_text
    tree_rules = export_text(clf, feature_names=FEATURE_NAMES)
    print(tree_rules)

    fig, ax = plt.subplots(figsize=(50, 30))
    plot_tree(
        clf,
        feature_names=FEATURE_NAMES,
        class_names=CLASS_NAMES,
        filled=True,
        rounded=True,
        impurity=False,
        label="all",
        proportion=True,
        precision=2,
        node_ids=False,
        fontsize=50,
        ax=ax,
    )

    for text in list(ax.texts):
        lines = [line for line in text.get_text().splitlines() if not line.startswith("samples =") and not line.startswith("value =")]
        text.set_text("\n".join(lines))

    ax.set_title(
        "BBRv2 vs BBRv3 decision tree\n"
        "branching on loss, RTT, bandwidth, and buffer size",
        fontsize=50,
        fontweight='bold',
    )
    plt.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.out, dpi=200)
    print(f"wrote plot to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())