#!/usr/bin/env python3
"""
Generic parser for ss_poll.log files to extract BBR/BBR2 state metrics.

Usage:
    python parse_ss_poll.py <input_ss_poll.log> <output.csv>
    
    or as library:
    from parse_ss_poll import parse_ss_poll_log
    df = parse_ss_poll_log('path/to/ss_poll.log')
"""

import re
import sys
import pandas as pd
from pathlib import Path
from typing import Optional


def parse_ss_poll_log(log_path: str, version_filter: Optional[str] = None) -> pd.DataFrame:
    """
    Parse ss_poll.log file and extract BBR/BBR2 state metrics.
    
    Args:
        log_path: Path to ss_poll.log file
        version_filter: 'bbr2', 'bbr3', or None (default: None, include all)
        
    Returns:
        DataFrame with columns: timestamp, inflight_hi, inflight_lo, phase, bw_hi, bw_lo, cwnd
    """
    records = []
    current_timestamp = None
    current_state = None
    timestamp_counter = {}  # Track record order within each timestamp
    timestamp_max_count = {}  # Track max count for each timestamp (for interpolation)
    
    with open(log_path, 'r') as f:
        for line in f:
            line = line.rstrip('\n')
            
            # Check for timestamp marker
            if line.startswith('===') and line.endswith('==='):
                # Extract timestamp: "=== 1778052889 ===" -> 1778052889
                match = re.search(r'===\s+(\d+)\s+===', line)
                if match:
                    current_timestamp = int(match.group(1))
                    if current_timestamp not in timestamp_counter:
                        timestamp_counter[current_timestamp] = 0
                continue
            
            # Extract state from address line (e.g., "ESTAB 0      554248    172.16.1.2:49138   172.16.2.2:5201")
            if current_timestamp is not None and re.match(r'^[A-Z\-]+\s+\d+', line):
                # Extract state (first word before whitespace)
                state_match = re.match(r'^([A-Z\-]+)\s+', line)
                if state_match:
                    current_state = state_match.group(1)
                continue
            
            # Look for BBR lines (only for ESTAB flows)
            if 'bbr' in line and 'bbr:(' in line and current_timestamp is not None and current_state == 'ESTAB':
                record = _extract_bbr_metrics(line, current_timestamp, timestamp_counter[current_timestamp])
                if record:
                    # Version filter
                    if version_filter is None or record.get('version') == version_filter:
                        records.append(record)
                        timestamp_counter[current_timestamp] += 1
                        timestamp_max_count[current_timestamp] = timestamp_counter[current_timestamp]
    
    df = pd.DataFrame(records)
    
    # Filter to keep only the dominant flow based on inflight_hi (has actual congestion window)
    if not df.empty:
        # Group by timestamp and keep the flow with highest inflight_hi at each timestamp
        # This filters out low-activity spurious connections
        max_inflight_idx = df.groupby('timestamp_sec')['inflight_hi'].idxmax()
        df = df.loc[max_inflight_idx].reset_index(drop=True)
        
        # Now convert timestamp to milliseconds with linear interpolation
        # For each record, spread it within the 1-second window based on its original position
        df['timestamp'] = df.apply(
            lambda row: int(row['timestamp_sec'] * 1000 + 
                           (row['timestamp_order'] / max(1, timestamp_max_count.get(row['timestamp_sec'], 1))) * 999),
            axis=1
        )
        
        # Drop temporary columns
        df = df.drop(columns=['timestamp_sec', 'timestamp_order'])
        
        # Sort by timestamp for final output
        df = df.sort_values('timestamp').reset_index(drop=True)
    
    return df


def _extract_bbr_metrics(line: str, timestamp: int, record_order: int) -> Optional[dict]:
    """
    Extract BBR metrics from a single ss output line.
    
    BBR format example:
    bbr:(bw:443960bps,mrtt:52.197,pacing_gain:2.77344,cwnd_gain:2,version:3,bw_hi:443960bps,
         bw_lo:8bps,inflight_hi:0,inflight_lo:0,extra_acked:2,mode:0,phase:STARTUP)
    
    Also extract cwnd from the main line: "cwnd:13"
    
    Timestamps are stored temporarily as seconds and order, then converted to milliseconds 
    with linear interpolation after filtering.
    """
    # Store temporary values - will be converted to milliseconds later
    record = {
        'timestamp_sec': timestamp,
        'timestamp_order': record_order
    }
    
    # Extract BBR block (everything between "bbr:(" and ")")
    bbr_match = re.search(r'bbr:\(([^)]+)\)', line)
    if not bbr_match:
        return None
    
    bbr_str = bbr_match.group(1)
    
    # Parse key=value pairs from BBR block
    # Handle both number values (e.g., "123") and values with units (e.g., "443960bps")
    # and phase values (e.g., "STARTUP")
    bbr_pairs = {}
    for pair in bbr_str.split(','):
        if ':' in pair:
            key, val = pair.strip().split(':', 1)
            bbr_pairs[key.strip()] = val.strip()
    
    # Extract desired fields from BBR state
    for field in ['inflight_hi', 'inflight_lo', 'bw_hi', 'bw_lo', 'phase', 'version']:
        if field in bbr_pairs:
            val = bbr_pairs[field]
            if field == 'phase':
                # phase is a string like "STARTUP"
                record[field] = val
            elif field == 'version':
                # version is a number
                record[field] = int(val)
            else:
                # bw_* and inflight_* are numbers (strip units like "bps")
                numeric_val = re.sub(r'[a-zA-Z]+', '', val)
                try:
                    record[field] = float(numeric_val) if '.' in numeric_val else int(numeric_val)
                except (ValueError, TypeError):
                    record[field] = None
    
    # Extract cwnd from main line (not in BBR block)
    cwnd_match = re.search(r'\bcwnd:(\d+)', line)
    if cwnd_match:
        record['cwnd'] = int(cwnd_match.group(1))
    
    # Check that we got the key fields
    required_fields = {'inflight_hi', 'inflight_lo', 'phase', 'bw_hi', 'bw_lo', 'cwnd', 'version'}
    if all(field in record for field in required_fields):
        return record
    else:
        return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input_ss_poll.log> [output.csv] [version_filter]")
        sys.exit(1)
    
    log_file = sys.argv[1]
    csv_file = sys.argv[2] if len(sys.argv) > 2 else log_file.replace('.log', '.csv')
    version_filter = sys.argv[3] if len(sys.argv) > 3 else None
    
    print(f"Parsing {log_file} (version_filter={version_filter})...")
    df = parse_ss_poll_log(log_file, version_filter=version_filter)
    
    if df.empty:
        print(f"No BBR records found in {log_file}")
        sys.exit(1)
    
    # Save to CSV
    csv_path = Path(csv_file)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    
    print(f"✓ Wrote {len(df)} records to {csv_path}")
    print(f"\nFirst few rows:")
    print(df.head())
    print(f"\nStats:")
    print(df[['inflight_hi', 'inflight_lo', 'cwnd', 'bw_hi', 'bw_lo']].describe())
