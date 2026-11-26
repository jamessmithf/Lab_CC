#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
05_gcp_run_benchmark.py - Automated Cloud Benchmark Controller for GCP PARCS Cluster.

Copies src/ and deploy/remote.sh to the GCP Master VM and launches src/driver.py
INSIDE the `parcs-master` container in the background (docker exec -d).
Measurements continue safely even if the laptop sleeps or loses Wi-Fi, and the
sequential baseline runs on the exact same GCP Python 2.7 runtime as PARCS.

Usage:
  python3 05_gcp_run_benchmark.py --wait              # Full benchmark (10M..100M, k=1..4, 3 runs)
  python3 05_gcp_run_benchmark.py --quick --wait      # Fast cloud smoke test (~1 min)
  python3 05_gcp_run_benchmark.py --status            # Check background progress on Master VM
  python3 05_gcp_run_benchmark.py --fetch             # Download results to benchmarks/results-cloud/
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
REMOTE_SH = os.path.join(SCRIPT_DIR, "remote.sh")
CLUSTER_ENV = os.path.join(SCRIPT_DIR, "gcp_cluster_info.env")
BENCH_DIR = os.path.join(PROJECT_ROOT, "benchmarks")
RESULTS_DIR = os.path.join(BENCH_DIR, "results-cloud")
LEGACY_JSON = os.path.join(BENCH_DIR, "gcp_benchmark_results.json")


def load_cluster_env():
    env = {
        "GCP_ZONE": "europe-north1-b",
        "MASTER_NAME": "master",
        "GCP_PROJECT_ID": "",
    }
    if os.path.exists(CLUSTER_ENV):
        with open(CLUSTER_ENV, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("export ") and "=" in line:
                    k, v = line[len("export "):].split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def gcloud_bin():
    local_sdk = os.path.expanduser("~/google-cloud-sdk/bin/gcloud")
    return local_sdk if os.path.exists(local_sdk) else "gcloud"


def ssh_cmd(master, zone, project, remote_cmd, capture=False):
    cmd = [gcloud_bin(), "compute", "ssh", master, f"--zone={zone}"]
    if project:
        cmd.append(f"--project={project}")
    cmd.extend(["--command", remote_cmd])
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, check=True)
    return subprocess.run(cmd, check=True)


def scp_to_master(master, zone, project, sources, dest):
    cmd = [gcloud_bin(), "compute", "scp", "--recurse", f"--zone={zone}"]
    if project:
        cmd.append(f"--project={project}")
    cmd.extend(sources)
    cmd.append(f"{master}:{dest}")
    subprocess.run(cmd, check=True)


def scp_from_master(master, zone, project, remote_src, local_dest):
    cmd = [gcloud_bin(), "compute", "scp", "--recurse", f"--zone={zone}"]
    if project:
        cmd.append(f"--project={project}")
    cmd.extend([f"{master}:{remote_src}", local_dest])
    subprocess.run(cmd, check=True)


def export_legacy_json(results_dir, out_json):
    full_path = os.path.join(results_dir, "results.json")
    if not os.path.exists(full_path):
        return
    with open(full_path, "r") as f:
        data = json.load(f)

    grouped = {}
    order = []
    for r in data.get("rows", []):
        if r.get("config") == "seq":
            continue
        key = (r["N"], r["workers"])
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(r)

    legacy = []
    for n, p in order:
        rs = grouped[(n, p)]
        times = [r["timing"]["total"] for r in rs]
        legacy.append({
            "environment": "Google Cloud Platform (Compute Engine)",
            "n": n,
            "workers": p,
            "repeats": len(times),
            "avg_time_sec": sum(times) / len(times),
            "min_time_sec": min(times),
            "all_times": times,
            "integral": rs[-1]["timing"]["integral"],
            "abs_error": rs[-1]["timing"]["abs_error"],
        })

    with open(out_json, "w") as f:
        json.dump(legacy, f, indent=2)
    print(f"Legacy GCP JSON exported to: {out_json}")


def print_summary(results_dir):
    summary_csv = os.path.join(results_dir, "summary.csv")
    if not os.path.exists(summary_csv):
        return
    print("\n" + "=" * 95)
    print("GCP CLOUD BENCHMARK SUMMARY (benchmarks/results-cloud/summary.csv)")
    print("=" * 95)
    with open(summary_csv, "r") as f:
        rows = list(csv.DictReader(f))
    header = (
        f"{'N':>11} | {'Cfg':>4} | {'T_mean(s)':>9} | {'T_std':>6} | "
        f"{'S(k)':>6} | {'E(k)':>6} | {'S1(k)':>6} | {'Tr_max':>7} | {'Imb':>6} | {'OK':>4}"
    )
    print(header)
    print("-" * 95)
    for r in rows:
        print(
            f"{int(r['N']):>11,d} | {r['config']:>4} | {r['total_mean']:>9} | {r['total_std']:>6} | "
            f"{r['speedup'] or '-':>6} | {r['efficiency'] or '-':>6} | {r['speedup_1'] or '-':>6} | "
            f"{r['transfer_max_mean'] or '-':>7} | {r['imbalance_mean'] or '-':>6} | {r['all_correct']:>4}"
        )
    print("=" * 95)


def fetch_results(master, zone, project, out_dir):
    print("[INFO] Collecting results from Master container...")
    ssh_cmd(master, zone, project, "sudo bash lab/remote.sh collect")
    os.makedirs(os.path.dirname(out_dir), exist_ok=True)
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    print(f"[INFO] Downloading results into {out_dir} ...")
    scp_from_master(master, zone, project, "lab/results", out_dir)
    export_legacy_json(out_dir, LEGACY_JSON)
    print_summary(out_dir)


def main():
    env = load_cluster_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", default=env.get("MASTER_NAME", "master"), help="Master VM instance name")
    ap.add_argument("--zone", default=env.get("GCP_ZONE", "europe-north1-b"), help="GCP zone")
    ap.add_argument("--project", default=env.get("GCP_PROJECT_ID", ""), help="GCP project ID")
    ap.add_argument("--sizes", default="10000000,25000000,50000000,100000000", help="Comma-separated N values")
    ap.add_argument("--runs", type=int, default=3, help="Repetitions per (N, config)")
    ap.add_argument("--workers", default="1,2,3,4", help="Comma-separated worker counts")
    ap.add_argument("--quick", action="store_true", help="Quick cloud smoke test (1M,5M, 1 run)")
    ap.add_argument("--wait", action="store_true", help="Wait for completion and automatically fetch results")
    ap.add_argument("--status", action="store_true", help="Show current status on Master VM and exit")
    ap.add_argument("--fetch", action="store_true", help="Download results from Master VM and exit")
    ap.add_argument("--out", default=RESULTS_DIR, help="Local directory for downloaded cloud results")
    args = ap.parse_args()

    if args.status:
        ssh_cmd(args.master, args.zone, args.project, "sudo bash lab/remote.sh status")
        return

    if args.fetch:
        fetch_results(args.master, args.zone, args.project, args.out)
        return

    if args.quick:
        args.sizes = "1000000,5000000"
        args.runs = 1

    print("=" * 70)
    print("STARTING GCP PARCS CLOUD BENCHMARK (REMOTE CONTAINER MODE)")
    print(f"Master VM : {args.master} (zone: {args.zone})")
    print(f"Sizes     : {args.sizes} | Workers: {args.workers} | Runs: {args.runs}")
    print("=" * 70)

    print("[1/3] Preparing ~/lab directory on Master VM...")
    ssh_cmd(args.master, args.zone, args.project, "rm -rf lab && mkdir -p lab")

    print("[2/3] Uploading src/ and deploy/remote.sh to Master VM...")
    scp_to_master(args.master, args.zone, args.project, [SRC_DIR, REMOTE_SH], "lab")

    print("[3/3] Starting driver.py in background inside parcs-master container...")
    ssh_cmd(
        args.master, args.zone, args.project,
        f"sudo bash lab/remote.sh start {args.sizes} {args.runs} {args.workers}"
    )

    print("\n[SUCCESS] Cloud benchmarks started in background on Master VM!")
    print("  Check status : python3 05_gcp_run_benchmark.py --status")
    print("  Fetch results: python3 05_gcp_run_benchmark.py --fetch")

    if args.wait:
        print("\n[WAIT] Monitoring progress every 30s (safe to Ctrl+C; job keeps running on Master)...")
        errors = 0
        while True:
            time.sleep(30)
            try:
                res = ssh_cmd(args.master, args.zone, args.project, "sudo bash lab/remote.sh status", capture=True)
                out = res.stdout.strip()
                errors = 0
            except Exception as e:
                errors += 1
                print(f"[WARN] SSH poll failed ({errors}/10): {e}")
                if errors >= 10:
                    print("[ERROR] Master unreachable for 10 attempts. Check later with --status.")
                    sys.exit(1)
                continue

            lines = [ln for ln in out.splitlines() if ln.strip()]
            last = lines[-1] if lines else ""
            print(f"[{time.strftime('%H:%M:%S')}] {last}")
            if "STATE: DONE" in out:
                print("\n[SUCCESS] All GCP benchmarks finished!")
                fetch_results(args.master, args.zone, args.project, args.out)
                break
            if "STATE: FAILED" in out:
                print(out)
                print("[ERROR] Benchmark driver failed on Master VM.")
                sys.exit(1)


if __name__ == "__main__":
    main()
