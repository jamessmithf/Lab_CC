#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automated Local Docker Cluster Benchmark Runner.

Executes src/driver.py INSIDE the `parcs-master` container (Python 2.7) so that
the sequential baseline (baseline.py) and PARCS workers run in the exact same
runtime environment. Results are copied to benchmarks/results-local/ and also
exported in legacy format to benchmarks/cluster_benchmark_results.json.

Usage:
  python3 run_cluster_benchmark.py
  python3 run_cluster_benchmark.py --quick
  python3 run_cluster_benchmark.py --sizes 10000000,25000000,50000000,100000000 --runs 3 --workers 1,2,3,4
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BENCH_DIR = os.path.join(PROJECT_ROOT, "benchmarks")
RESULTS_DIR = os.path.join(BENCH_DIR, "results-local")
LEGACY_JSON = os.path.join(BENCH_DIR, "cluster_benchmark_results.json")
CONTAINER = "parcs-master"


def run_cmd(cmd, check=True):
    print("$ " + " ".join(cmd))
    return subprocess.run(cmd, check=check)


def export_legacy_json(results_dir, out_json, env_label="Local Docker Cluster"):
    """Creates backward-compatible JSON summary alongside full results-local/."""
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
            "environment": env_label,
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
    print(f"Legacy JSON exported to: {out_json}")


def print_summary(results_dir):
    summary_csv = os.path.join(results_dir, "summary.csv")
    if not os.path.exists(summary_csv):
        return
    print("\n" + "=" * 95)
    print("LOCAL DOCKER CLUSTER BENCHMARK SUMMARY (benchmarks/results-local/summary.csv)")
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", default="10000000,25000000,50000000,100000000", help="Comma-separated N values")
    ap.add_argument("--runs", type=int, default=3, help="Repetitions per (N, config)")
    ap.add_argument("--workers", default="1,2,3,4", help="Comma-separated worker counts")
    ap.add_argument("--quick", action="store_true", help="Quick smoke test (1M,5M, 1 run)")
    ap.add_argument("--out", default=RESULTS_DIR, help="Local output directory")
    args = ap.parse_args()

    if args.quick:
        args.sizes = "1000000,5000000"
        args.runs = 1

    # Verify container is running
    chk = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True
    )
    if CONTAINER not in chk.stdout.splitlines():
        print(f"[ERROR] Container '{CONTAINER}' is not running. Start cluster with: ./start_local_cluster.sh")
        sys.exit(1)

    print("=" * 70)
    print("RUNNING UNIFIED BENCHMARK DRIVER INSIDE CONTAINER:", CONTAINER)
    print(f"Sizes: {args.sizes} | Workers: {args.workers} | Runs: {args.runs}")
    print("=" * 70)

    run_cmd(["docker", "exec", CONTAINER, "rm", "-rf", "/lab"])
    run_cmd(["docker", "cp", SRC_DIR, f"{CONTAINER}:/lab"])
    run_cmd(["docker", "exec", CONTAINER, "rm", "-rf", "/lab/results", "/lab/__pycache__"])

    driver_cmd = [
        "docker", "exec", CONTAINER, "python", "/lab/driver.py",
        "--sizes", args.sizes,
        "--runs", str(args.runs),
        "--workers", args.workers,
        "--out", "/lab/results",
        "--wait-workers", "120",
    ]
    res = run_cmd(driver_cmd, check=False)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    if os.path.exists(args.out):
        shutil.rmtree(args.out)
    run_cmd(["docker", "cp", f"{CONTAINER}:/lab/results", args.out])

    if res.returncode != 0:
        print(f"[ERROR] Benchmark driver failed with code {res.returncode}. Check {args.out}/progress.log")
        sys.exit(res.returncode)

    export_legacy_json(args.out, LEGACY_JSON)
    print_summary(args.out)


if __name__ == "__main__":
    main()
