#!/usr/bin/env python3
"""
orchestrate bbr/cubic experiments from the middlebox

for each experiment we collect:
  - iperf3 JSON (sender)
  - bpftrace BBR internals (sender, background)
  - tc queue depth + drop counts polled every 1s (middlebox, background)
  - metadata JSON

Usage:
  sudo python3 run_experiments.py [--experiments experiments.csv]
                                  [--results-dir results]
                                  [--resume]
                                  [--dry-run]
"""

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# == Configuration =============================================================

SENDER_HOST = "172.16.1.2"
SENDER_USER = "user"  # sender username
SSH_PASS = "user"
SHAPE_SCRIPT = Path(__file__).parent / "shape.sh"  # local path on middlebox

# Load interface names from ifaces.conf (single source of truth)
_ifaces_conf = Path(__file__).parent / "ifaces.conf"
_ifaces = dict(
    line.split("=", 1)
    for line in _ifaces_conf.read_text().splitlines()
    if line and not line.startswith("#") and "=" in line
)
IFACE_FWD = _ifaces["IFACE_FWD"]
IFACE_REV = _ifaces["IFACE_REV"]

IPERF_DURATION = 300  # seconds/experiment (5 minutes)

COOLDOWN = 15  # seconds between experiments (drain queues)
TC_POLL_INTERVAL = 1  # seconds between tc -s snapshots

BPFTRACE_SCRIPT_LOCAL = Path(__file__).parent / "probes" / "bbr.bt"
BPFTRACE_SCRIPT_REMOTE = "/tmp/bbr.bt"  # deployed to sender before batch

SS_POLL_REMOTE = "/tmp/ss_poll.log"
SS_POLL_INTERVAL = 0.2  # seconds between ss -tni snapshots

# == Helpers ===================================================================


def kernel_cc(cc: str) -> str:
    "kernel-side it's just bbr"
    if cc in ("bbrv2", "bbrv3"):
        return "bbr"
    return cc


def tag(rtt_ms, bw_mbit, buf_bdp_ratio, loss_pct, cc_a, cc_b):
    buf_label = f"{buf_bdp_ratio:g}bdp"
    cc_label = f"{cc_a}vs{cc_b}" if cc_b else cc_a
    return f"rtt{rtt_ms}_bw{bw_mbit}_loss{loss_pct}_buf{buf_label}_{cc_label}"


def _ssh_base():
    return ["sshpass", "-p", SSH_PASS, "ssh", "-o", "StrictHostKeyChecking=no"]


def ssh(cmd: str, *, capture=True, timeout=None) -> subprocess.CompletedProcess:
    """run cmd on sender via ssh"""
    full = _ssh_base() + [f"{SENDER_USER}@{SENDER_HOST}", cmd]
    return subprocess.run(full, capture_output=capture, text=True, timeout=timeout)


def ssh_bg(cmd: str) -> subprocess.Popen:
    """start cmd on sender via ssh (in background)"""
    full = _ssh_base() + [f"{SENDER_USER}@{SENDER_HOST}", cmd]
    return subprocess.Popen(
        full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def local_bg(cmd: list) -> subprocess.Popen:
    """start a local background process"""
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def deploy_bpftrace_script():
    """scp probes/bbr.bt to sender before the batch starts."""
    print(
        f"Deploying bpftrace script to {SENDER_USER}@{SENDER_HOST}:{BPFTRACE_SCRIPT_REMOTE} ..."
    )
    r = subprocess.run(
        [
            "sshpass",
            "-p",
            SSH_PASS,
            "scp",
            "-o",
            "StrictHostKeyChecking=no",
            str(BPFTRACE_SCRIPT_LOCAL),
            f"{SENDER_USER}@{SENDER_HOST}:{BPFTRACE_SCRIPT_REMOTE}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        sys.exit(f"ERROR: failed to scp bbr.bt to sender:\n{r.stderr}")
    print("  deployed.")


# == tc polling ================================================================


def tc_poll_loop(out_path: Path, stop_event: threading.Event):
    """
    Poll tc -s qdisc on both interfaces every TC_POLL_INTERVAL seconds.
    Write one JSON line per sample to out_path.
    Captures queue length and drop counts from the netem qdisc.
    """
    with open(out_path, "w") as f:
        while not stop_event.is_set():
            t = time.time()
            sample = {"ts": t, "fwd": {}, "rev": {}}

            for iface, key in [(IFACE_FWD, "fwd"), (IFACE_REV, "rev")]:
                r = subprocess.run(
                    ["tc", "-s", "-j", "qdisc", "show", "dev", iface],
                    capture_output=True,
                    text=True,
                )
                try:
                    qdiscs = json.loads(r.stdout)
                    # Find the netem qdisc entry
                    for q in qdiscs:
                        if q.get("kind") == "netem":
                            sample[key] = {
                                "qlen": q.get("qlen", 0),
                                "drops": q.get("drops", 0),
                                "overlimits": q.get("overlimits", 0),
                                "requeues": q.get("requeues", 0),
                            }
                except (json.JSONDecodeError, KeyError):
                    sample[key] = {"raw": r.stdout.strip()}

            f.write(json.dumps(sample) + "\n")
            f.flush()
            stop_event.wait(TC_POLL_INTERVAL)


# == Experiment runner =========================================================


def run_experiment(params: dict, out_dir: Path, dry_run: bool):
    rtt = params["rtt_ms"]
    bw = params["bw_mbit"]
    buf_ratio = params["buf_bdp_ratio"]
    loss = params["loss_pct"]
    cc_a = params["cc_a"]
    cc_b = params["cc_b"]

    # BDP in bytes = (bw_mbit * 1e6 / 8) * (rtt_ms / 1000)
    bdp_bytes = (bw * 1_000_000 / 8) * (rtt / 1000)
    buf = int(buf_ratio * bdp_bytes)

    print(f"\n{'='*60}")
    print(
        f"  {tag(rtt_ms=rtt,bw_mbit=bw,buf_bdp_ratio=buf_ratio,loss_pct=loss,cc_a=cc_a,cc_b=cc_b)}"
    )
    print(
        f"  RTT={rtt}ms  BW={bw}Mbps  buf={buf_ratio:g}xBDP={buf}B  loss={loss}%  cc={cc_a}{'vs'+cc_b if cc_b else ''}"
    )
    print(f"{'='*60}")

    out_dir.mkdir(parents=True, exist_ok=True)

    # == metadata ==============================================================
    meta = {
        "rtt_ms": rtt,
        "bw_mbit": bw,
        "buf_bdp_ratio": buf_ratio,
        "buf_bytes": buf,
        "loss_pct": loss,
        "cc_a": cc_a,
        "cc_b": cc_b if cc_b else None,
        "iperf_duration": IPERF_DURATION,
        "start_utc": datetime.now(timezone.utc).isoformat(),
        "sender": SENDER_HOST,
    }
    # grab kernel version from sender
    if not dry_run:
        r = ssh("uname -r", timeout=10)
        meta["sender_kernel"] = r.stdout.strip()
        r = ssh("sysctl -n net.ipv4.tcp_congestion_control", timeout=10)
        meta["sender_cc_default"] = r.stdout.strip()

    if dry_run:
        print("  [dry-run] skipping execution")
        return

    # == 1. apply shape.sh locally ===============================================
    print("  [1/4] Applying tc shaping...")
    r = subprocess.run(
        ["bash", SHAPE_SCRIPT, str(rtt), str(bw), str(loss), str(buf)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"  ERROR: shape.sh failed:\n{r.stderr}")
        return
    (out_dir / "shape_output.txt").write_text(r.stdout)

    # == 2. start bpftrace on sender ===========================================
    print("  [2/4] Starting bpftrace and ss poll on sender...")
    # Write output to a local file on the sender - avoids piping large logs over
    # SSH during the experiment (especially at high bandwidth).
    bpf_proc = ssh_bg(
        f"echo {SSH_PASS} | sudo -S bpftrace {BPFTRACE_SCRIPT_REMOTE} > /tmp/bpftrace_out.log 2>&1"
    )
    time.sleep(1)  # let bpftrace attach

    # Poll ss -tni on the sender to capture BBR-specific fields
    # (inflight_hi, inflight_lo, bw_hi, bw_lo, pacing_gain, cwnd_gain, etc.)
    ss_proc = ssh_bg(
        f"while true; do"
        f' echo "=== $(date +%s) ===";'
        f" ss -tni dst 172.16.2.2;"
        f" sleep {SS_POLL_INTERVAL};"
        f" done > {SS_POLL_REMOTE} 2>&1"
    )

    # == 3. start tc poll locally ==============================================
    print("  [3/4] Starting tc poll...")
    tc_stop = threading.Event()
    tc_thread = threading.Thread(
        target=tc_poll_loop,
        args=(out_dir / "tc_poll.jsonl", tc_stop),
        daemon=True,
    )
    tc_thread.start()

    # == 4. run iperf3 client on sender -> receiver ============================
    # iperf3 server runs on receiver (172.16.2.2) from one-time setup; no ssh needed
    if cc_b:
        print(
            f"  [4/4] Running two iperf3 streams for {IPERF_DURATION}s "
            f"(A={cc_a} port 5201, B={cc_b} port 5202)..."
        )
        proc_a = ssh_bg(
            f"iperf3 -c 172.16.2.2 -C {kernel_cc(cc_a)} -t {IPERF_DURATION} -J"
        )
        proc_b = ssh_bg(
            f"iperf3 -c 172.16.2.2 -C {kernel_cc(cc_b)} -t {IPERF_DURATION} -J -p 5202"
        )
        stdout_a, stderr_a = proc_a.communicate(timeout=IPERF_DURATION + 30)
        stdout_b, stderr_b = proc_b.communicate(timeout=IPERF_DURATION + 30)
        if proc_a.returncode != 0:
            print(
                f"  WARNING: iperf3 stream A ({cc_a}) exited with code {proc_a.returncode}"
            )
            print(stderr_a[:500])
            exit(1)
        if proc_b.returncode != 0:
            print(
                f"  WARNING: iperf3 stream B ({cc_b}) exited with code {proc_b.returncode}"
            )
            print(stderr_b[:500])
            exit(1)
        (out_dir / "iperf_sender_a.json").write_text(stdout_a)
        (out_dir / "iperf_sender_b.json").write_text(stdout_b)
    else:
        print(f"  [4/4] Running iperf3 for {IPERF_DURATION}s (cc={cc_a})...")
        r = ssh(
            f"iperf3 -c 172.16.2.2 -C {kernel_cc(cc_a)} -t {IPERF_DURATION} -J",
            timeout=IPERF_DURATION + 30,
        )
        if r.returncode != 0:
            print(f"  WARNING: iperf3 exited with code {r.returncode}")
            print(r.stderr[:500])
            exit(1)
        (out_dir / "iperf_sender.json").write_text(r.stdout)

    # == Stop tc poll ==========================================================

    tc_stop.set()
    tc_thread.join(timeout=5)

    # == Stop bpftrace and collect =============================================
    # SIGINT to the local SSH process causes the remote session to close,
    # which sends SIGHUP to bpftrace - it prints the END block and flushes.
    bpf_proc.send_signal(signal.SIGINT)
    bpf_proc.wait(timeout=15)  # wait for bpftrace to flush and SSH to close
    r_bpf = ssh("cat /tmp/bpftrace_out.log", timeout=120)
    (out_dir / "bpftrace.log").write_text(r_bpf.stdout)

    # == Stop ss poll and collect ==============================================
    ss_proc.send_signal(signal.SIGINT)
    ss_proc.wait(timeout=10)
    r_ss = ssh(f"cat {SS_POLL_REMOTE}", timeout=60)
    (out_dir / "ss_poll.log").write_text(r_ss.stdout)

    # == Finalize metadata =====================================================
    meta["end_utc"] = datetime.now(timezone.utc).isoformat()
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

    print(f"  Done. -> {out_dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiments", default="experiments.csv")
    parser.add_argument("--results-dir", default="results")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip experiments whose output dir already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print experiment list without running anything",
    )
    args = parser.parse_args()

    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root (needs tc and shape.sh)")

    results = Path(args.results_dir)
    results.mkdir(exist_ok=True)

    with open(args.experiments, newline="") as f:
        experiments = list(csv.DictReader(f))

    total = len(experiments)
    print(f"Loaded {total} experiments from {args.experiments}")
    print(f"Estimated runtime: {total * (IPERF_DURATION + COOLDOWN) / 60:.1f} minutes")

    if not args.dry_run:
        deploy_bpftrace_script()

    start_wall = time.time()

    for i, row in enumerate(experiments, 1):
        params = {
            "rtt_ms": int(row["rtt_ms"]),
            "bw_mbit": int(row["bw_mbit"]),
            "buf_bdp_ratio": float(row["buf_bdp_ratio"]),
            "loss_pct": int(row["loss_pct"]),
            "cc_a": row["cc_a"],
            "cc_b": row["cc_b"],
        }
        t = tag(**params)
        out_dir = results / t

        if args.resume and (out_dir / "metadata.json").exists():
            print(f"[{i}/{total}] SKIP (already done): {t}")
            continue

        print(f"\n[{i}/{total}]", end="")
        run_experiment(params, out_dir, dry_run=args.dry_run)

        if i < total and not args.dry_run:
            elapsed = time.time() - start_wall
            remaining_exps = total - i
            eta_s = remaining_exps * (IPERF_DURATION + COOLDOWN)
            print(
                f"  Cooling down {COOLDOWN}s... "
                f"(elapsed {elapsed/60:.1f}m, ETA ~{eta_s/60:.1f}m remaining)"
            )
            time.sleep(COOLDOWN)

    print(f"\nComplete :) see {results}")


if __name__ == "__main__":
    main()
