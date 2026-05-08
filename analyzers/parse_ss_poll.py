#!/usr/bin/env python3
"""
Parser for ss_poll.log files to extract BBR state metrics.

Usage:
    python parse_ss_poll.py <input_ss_poll.log> [output.csv]

    or as library:
    from parse_ss_poll import parse_ss_poll_log
    df = parse_ss_poll_log('path/to/ss_poll.log')
"""

import re
import sys
import pandas as pd
from pathlib import Path
from typing import Optional


REQUIRED_FIELDS = {'inflight_hi', 'inflight_lo', 'bw_hi', 'bw_lo', 'phase', 'cwnd'}


def parse_ss_poll_log(log_path: str) -> pd.DataFrame:
    """
    Parse ss_poll.log file and extract BBR state metrics.

    Only includes flows that are:
      - In ESTAB state
      - Have a bbr:(...) block
      - Have all of: inflight_hi, bw_hi, bw_lo, phase, cwnd
      - inflight_lo is extracted when present (absent in some BBR phases)

    Args:
        log_path: Path to ss_poll.log file

    Returns:
        DataFrame with columns: timestamp, inflight_hi, inflight_lo,
                                bw_hi, bw_lo, phase, cwnd
    """
    records = []
    current_timestamp = None
    current_state = None
    timestamp_counter = {}
    timestamp_max_count = {}

    with open(log_path, 'r') as f:
        for line in f:
            line = line.rstrip('\n')

            # Timestamp marker: "=== 1778052889 ==="
            if line.startswith('===') and line.endswith('==='):
                match = re.search(r'===\s+(\d+)\s+===', line)
                if match:
                    current_timestamp = int(match.group(1))
                    timestamp_counter.setdefault(current_timestamp, 0)
                continue

            # State line: "ESTAB 0  554248  172.16.1.2:49138  172.16.2.2:5201"
            if current_timestamp is not None and re.match(r'^[A-Z\-]+\s+\d+', line):
                state_match = re.match(r'^([A-Z\-]+)\s+', line)
                if state_match:
                    current_state = state_match.group(1)
                continue

            # BBR metrics line — only for ESTAB flows with a bbr:(...) block.
            # inflight_lo and bw_lo are optional (absent in PROBE_BW_UP/DOWN/DRAIN);
            # field-level validation is handled inside _extract_bbr_metrics.
            if (current_timestamp is not None
                    and current_state == 'ESTAB'
                    and 'bbr:(' in line
                    and 'inflight_hi' in line):
                order = timestamp_counter.get(current_timestamp, 0)
                record = _extract_bbr_metrics(line, current_timestamp, order)
                if record:
                    records.append(record)
                    timestamp_counter[current_timestamp] = order + 1
                    timestamp_max_count[current_timestamp] = order + 1

    df = pd.DataFrame(records)

    if not df.empty:
        # Deduplicate on metric values before spreading timestamps.
        # Rows with identical (timestamp_sec, inflight_hi, inflight_lo, bw_hi, bw_lo, phase, cwnd)
        # are the same measurement — keep the first occurrence and reset the per-second
        # order counters so the timestamp spreading reflects true unique records.
        metric_cols = ['timestamp_sec', 'inflight_hi', 'inflight_lo', 'bw_hi', 'bw_lo', 'phase', 'cwnd']
        df = df.drop_duplicates(subset=metric_cols).reset_index(drop=True)

        # Recompute order and max-count after dedup so timestamp spreading is correct.
        df['timestamp_order'] = df.groupby('timestamp_sec').cumcount()
        timestamp_max_count = df.groupby('timestamp_sec').size().to_dict()

        # Spread records within each 1-second window using linear interpolation
        df['timestamp'] = df.apply(
            lambda row: int(
                row['timestamp_sec'] * 1000
                + (row['timestamp_order'] / max(1, timestamp_max_count.get(row['timestamp_sec'], 1))) * 999
            ),
            axis=1
        )
        df = df.drop(columns=['timestamp_sec', 'timestamp_order'])
        df = df.sort_values('timestamp').reset_index(drop=True)

    return df


def _extract_bbr_metrics(line: str, timestamp: int, record_order: int) -> Optional[dict]:
    """
    Extract BBR metrics from a single ss output line.

    Returns a dict with inflight_hi, inflight_lo, bw_hi, bw_lo, phase, cwnd,
    plus temporary timestamp_sec and timestamp_order fields used for interpolation.
    Returns None if any required field is missing.
    """
    record = {
        'timestamp_sec': timestamp,
        'timestamp_order': record_order,
    }

    # Extract the bbr:(...) block
    bbr_match = re.search(r'bbr:\(([^)]+)\)', line)
    if not bbr_match:
        return None

    # Parse key:value pairs from the BBR block
    bbr_pairs = {}
    for pair in bbr_match.group(1).split(','):
        if ':' in pair:
            key, val = pair.strip().split(':', 1)
            bbr_pairs[key.strip()] = val.strip()

    # Required numeric fields (strip unit suffixes like "bps")
    for field in ('inflight_hi', 'bw_hi'):
        if field not in bbr_pairs:
            return None
        numeric = re.sub(r'[a-zA-Z]+', '', bbr_pairs[field])
        try:
            record[field] = float(numeric) if '.' in numeric else int(numeric)
        except ValueError:
            return None

    # Optional numeric fields — absent in PROBE_BW_UP/DOWN/DRAIN phases
    for field in ('inflight_lo', 'bw_lo'):
        if field in bbr_pairs:
            numeric = re.sub(r'[a-zA-Z]+', '', bbr_pairs[field])
            try:
                record[field] = float(numeric) if '.' in numeric else int(numeric)
            except ValueError:
                record[field] = None
        else:
            record[field] = None

    # Extract phase (string value)
    if 'phase' not in bbr_pairs:
        return None
    record['phase'] = bbr_pairs['phase']

    # Extract cwnd from the main line (not inside the bbr block)
    cwnd_match = re.search(r'\bcwnd:(\d+)', line)
    if not cwnd_match:
        return None
    record['cwnd'] = int(cwnd_match.group(1))

    return record


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input_ss_poll.log> [output.csv]")
        sys.exit(1)

    log_file = sys.argv[1]
    csv_file = sys.argv[2] if len(sys.argv) > 2 else log_file.replace('.log', '.csv')

    print(f"Parsing {log_file}...")
    df = parse_ss_poll_log(log_file)

    if df.empty:
        print(f"No BBR records found in {log_file}")
        sys.exit(1)

    csv_path = Path(csv_file)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    print(f"✓ Wrote {len(df)} records to {csv_path}")
    print(f"\nFirst few rows:\n{df.head()}")
    print(f"\nStats:\n{df[list(REQUIRED_FIELDS - {'phase'})].describe()}")