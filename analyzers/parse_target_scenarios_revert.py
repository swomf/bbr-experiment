#!/usr/bin/env python3
"""
Parse ss_poll.log files from all subdirectories in a target experiment directory.

Automatically discovers subdirectories of the form:
  rtt<N>_bw<N>_loss<N>_buf<BDP>_bbr<version>

And generates output CSVs with matching names:
  ss_poll_rtt<N>_bw<N>_loss<N>_buf<BDP>_bbr<version>.csv
"""

import sys
import re
from pathlib import Path
import pandas as pd

# Add analyzers to path so we can import parse_ss_poll
sys.path.insert(0, str(Path(__file__).parent))
from parse_ss_poll import parse_ss_poll_log


def main(base_dir=None):
    """
    Parse all ss_poll.log files from subdirectories in base_dir.
    
    Args:
        base_dir: Root directory containing experiment subdirectories.
                  If None, defaults to "04-108-fairness-throughput"
    """
    if base_dir is None:
        base_dir = Path("05-036-bbrv3-constants-revert")
    else:
        base_dir = Path(base_dir)
    
    out_dir = Path("out/ss_poll_csv")
    out_dir.mkdir(exist_ok=True)
    
    if not base_dir.exists():
        print(f"Error: Directory not found: {base_dir}")
        sys.exit(1)
    
    # Find all subdirectories that contain ss_poll.log
    all_results = []
    processed_count = 0
    
    # Pattern to parse directory names like: rtt10_bw100_loss2_buf0.1bdp_bbrv2
    dir_pattern = re.compile(r'(rtt\d+)_(bw\d+)_(loss2)_(buf[\d.]+bdp)_(bbr[^/]+)$')
    
    for subdir in sorted(base_dir.iterdir()):
        if not subdir.is_dir():
            continue
        
        ss_log = subdir / "ss_poll.log"
        if not ss_log.exists():
            continue
        
        # Extract directory name parameters
        match = dir_pattern.match(subdir.name)
        if not match:
            continue
        
        rtt, bw, loss, buf, bbr = match.groups()
        csv_filename = f"ss_poll_{rtt}_{bw}_{loss}_{buf}_{bbr}_revert.csv"
        csv_out = out_dir / csv_filename
        
        print(f"\nParsing {subdir.name}...")
        try:
            df = parse_ss_poll_log(str(ss_log))
            
            if df.empty:
                print(f"  ⚠ No records parsed from {ss_log}")
                continue
            
            df.to_csv(csv_out, index=False)
            print(f"  ✓ Wrote {len(df)} records to {csv_out}")
            
            # Log summary stats
            result = {
                "directory": subdir.name,
                "csv_filename": csv_filename,
                "num_records": len(df),
                "phases": ", ".join(sorted(df['phase'].unique())),
                "inflight_hi_mean": df["inflight_hi"].mean(),
                "inflight_lo_mean": df["inflight_lo"].mean(),
                "cwnd_mean": df["cwnd"].mean(),
                "bw_hi_mean": df["bw_hi"].mean(),
                "bw_lo_mean": df["bw_lo"].mean(),
            }
            all_results.append(result)
            processed_count += 1
            
        except Exception as e:
            print(f"  ✗ Error parsing {ss_log}: {e}")
            import traceback
            traceback.print_exc()
    
    # Print summary
    print("\n" + "="*100)
    print(f"SUMMARY: Processed {processed_count} scenarios")
    print("="*100)
    for result in all_results:
        print(f"\n{result['directory']}:")
        print(f"  Output: {result['csv_filename']}")
        print(f"  Records: {result['num_records']}")
        print(f"  Phases: {result['phases']}")
        print(f"  inflight_hi_mean: {result['inflight_hi_mean']:.2f}")
        print(f"  inflight_lo_mean: {result['inflight_lo_mean']:.2f}")
        print(f"  cwnd_mean: {result['cwnd_mean']:.2f}")
        print(f"  bw_hi_mean (Mbps): {result['bw_hi_mean']/1e6:.2f}")
        print(f"  bw_lo_mean (Mbps): {result['bw_lo_mean']/1e6:.2f}")


if __name__ == "__main__":
    base_dir = sys.argv[1] if len(sys.argv) > 1 else None
    main(base_dir)
