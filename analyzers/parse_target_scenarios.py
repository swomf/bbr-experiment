#!/usr/bin/env python3
"""
Parse ss_poll.log files for target v2 vs v3 scenarios (lossy networks).

Scenarios:
- RTT 10ms: all buffer sizes (0.1, 1, 10 bdp) — v3 > v2
- RTT 50ms: all buffer sizes — mixed patterns
- RTT 100ms: medium buffer (1 bdp) — v3 degrades

Outputs CSVs to out/ss_poll_<scenario>.csv
"""

import sys
from pathlib import Path
import pandas as pd

# Add analyzers to path so we can import parse_ss_poll
sys.path.insert(0, str(Path(__file__).parent))
from parse_ss_poll import parse_ss_poll_log


def main():
    base_dir = Path("04-108-fairness-throughput")
    out_dir = Path("out")
    out_dir.mkdir(exist_ok=True)
    
    # Define target scenarios: (rtt, bdp_list)
    scenarios = [
        ("10", ["0.1bdp", "1bdp", "10bdp"]),    # RTT 10ms, all buffers
        ("50", ["0.1bdp", "1bdp", "10bdp"]),    # RTT 50ms, all buffers
        ("100", ["0.1bdp", "1bdp", "10bdp"]),                       # RTT 100ms, medium buffer only
    ]
    
    all_results = []
    
    for rtt, bdp_list in scenarios:
        for bdp in bdp_list:
            # v2 and v3 config names
            config_v2 = f"rtt{rtt}_bw100_loss2_buf{bdp}_bbrv2"
            config_v3 = f"rtt{rtt}_bw100_loss2_buf{bdp}_bbrv3"
            
            scenario_name = f"rtt{rtt}_{bdp}"
            
            for version, config in [("v2", config_v2), ("v3", config_v3)]:
                ss_log = base_dir / config / "ss_poll.log"
                csv_out = out_dir / f"ss_poll_{scenario_name}_{version}.csv"
                
                if not ss_log.exists():
                    print(f"⚠ Not found: {ss_log}")
                    continue
                
                print(f"\nParsing {scenario_name} {version}...")
                try:
                    df = parse_ss_poll_log(str(ss_log))
                    df.to_csv(csv_out, index=False)
                    print(f"  ✓ Wrote {len(df)} records to {csv_out}")
                    
                    # Log summary stats
                    result = {
                        "scenario": scenario_name,
                        "version": version,
                        "num_records": len(df),
                        "inflight_hi_mean": df["inflight_hi"].mean(),
                        "inflight_lo_mean": df["inflight_lo"].mean(),
                        "cwnd_mean": df["cwnd"].mean(),
                        "bw_hi_mean": df["bw_hi"].mean(),
                        "bw_lo_mean": df["bw_lo"].mean(),
                    }
                    all_results.append(result)
                    
                except Exception as e:
                    print(f"  ✗ Error parsing {ss_log}: {e}")
    
    # Print summary
    print("\n" + "="*80)
    print("SUMMARY OF PARSED SCENARIOS")
    print("="*80)
    for result in all_results:
        print(f"\n{result['scenario']} ({result['version']}):")
        print(f"  Records: {result['num_records']}")
        print(f"  inflight_hi_mean: {result['inflight_hi_mean']:.2f}")
        print(f"  inflight_lo_mean: {result['inflight_lo_mean']:.2f}")
        print(f"  cwnd_mean: {result['cwnd_mean']:.2f}")
        print(f"  bw_hi_mean (Mbps): {result['bw_hi_mean']/1e6:.2f}")
        print(f"  bw_lo_mean (Mbps): {result['bw_lo_mean']/1e6:.2f}")


if __name__ == "__main__":
    main()
