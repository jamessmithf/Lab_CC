#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plot_benchmarks.py - Academic Visualization of PARCS-Python Distributed Benchmarks

Reads unified driver outputs (benchmarks/results-local/summary.csv and
benchmarks/results-cloud/summary.csv), with fallback to legacy JSON files.
Generates high-resolution figures (PNG, 300 DPI) for each available environment:
  1. Speedup S_1(k) = T_1 / T_k (and S(k) = T_seq / T_k) vs Ideal & Amdahl's Law
  2. Parallel Efficiency E_1(k) (%)
  3. Execution Time T_k(k) with standard deviation error bars
  4. Comprehensive 2x2 Performance Dashboard
"""

import csv
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["font.size"] = 11
plt.rcParams["axes.titlesize"] = 13
plt.rcParams["axes.titleweight"] = "bold"
plt.rcParams["axes.labelsize"] = 11
plt.rcParams["axes.labelweight"] = "bold"
plt.rcParams["xtick.labelsize"] = 10
plt.rcParams["ytick.labelsize"] = 10
plt.rcParams["legend.fontsize"] = 9.5
plt.rcParams["figure.titlesize"] = 15
plt.rcParams["figure.titleweight"] = "bold"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLOTS_DIR = SCRIPT_DIR

PALETTE = ["#1f77b4", "#9467bd", "#ff7f0e", "#2ca02c", "#d62728"]
MARKERS = ["o", "D", "s", "^", "v"]


def format_n_label(n_val):
    if n_val % 1000000 == 0:
        m = n_val // 1000000
        if m == 10:
            return r"$N = 10^7$"
        if m == 100:
            return r"$N = 10^8$"
        return rf"$N = {m} \cdot 10^6$"
    return f"N = {n_val:,}"


def load_summary_csv(csv_path):
    if not os.path.exists(csv_path):
        return None
    dataset = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            n = int(row["N"])
            cfg = row["config"]
            k = 0 if cfg == "seq" else int(row["workers"])
            dataset.setdefault(n, {})[k] = {
                "mean": float(row["total_mean"]),
                "std": float(row["total_std"]) if row.get("total_std") else 0.0,
                "speedup": float(row["speedup"]) if row.get("speedup") else None,
                "efficiency": float(row["efficiency"]) if row.get("efficiency") else None,
                "speedup_1": float(row["speedup_1"]) if row.get("speedup_1") else None,
                "efficiency_1": float(row["efficiency_1"]) if row.get("efficiency_1") else None,
                "job_wall": float(row["job_wall_mean"]) if row.get("job_wall_mean") else None,
            }
    return dataset if dataset else None


def load_legacy_json(json_path):
    if not os.path.exists(json_path):
        return None
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    dataset = {}
    for entry in data:
        n = int(entry["n"])
        k = int(entry["workers"])
        times = entry.get("all_times", [entry["avg_time_sec"]])
        std_val = float(np.std(times, ddof=1)) if len(times) >= 2 else 0.0
        dataset.setdefault(n, {})[k] = {
            "mean": float(entry["avg_time_sec"]),
            "std": std_val,
            "speedup": None,
            "efficiency": None,
            "speedup_1": None,
            "efficiency_1": None,
            "job_wall": None,
        }
    return dataset if dataset else None


def get_sizes_and_workers(dataset):
    sizes = sorted(dataset.keys())
    ks = sorted({k for n in sizes for k in dataset[n].keys() if k > 0})
    return sizes, ks


def calc_speedup_s1(dataset, n, k):
    t1 = dataset[n][1]["mean"]
    tk = dataset[n][k]["mean"]
    return t1 / tk


def plot_speedup(dataset, prefix="", env_name="Local Docker Cluster"):
    sizes, ks = get_sizes_and_workers(dataset)
    kmax = max(ks)
    fig, ax = plt.subplots(figsize=(8.2, 5.8), dpi=300)

    ax.plot([1, kmax], [1, kmax], "k--", linewidth=1.5, label=r"Ідеальне лінійне ($S_1(k) = k$)")

    for idx, n_val in enumerate(sizes):
        col = PALETTE[idx % len(PALETTE)]
        mk = MARKERS[idx % len(MARKERS)]
        s_vals = [calc_speedup_s1(dataset, n_val, k) for k in ks]
        ax.plot(ks, s_vals, marker=mk, color=col, linewidth=2.2, markersize=7.5,
                label=f"Виміряне ({format_n_label(n_val)})")
        if idx in (0, len(sizes) - 1):
            for k, s in zip(ks, s_vals):
                dy = 8 if idx == len(sizes) - 1 else -14
                ax.annotate(f"{s:.2f}x", (k, s), textcoords="offset points", xytext=(0, dy),
                            ha="center", fontsize=8.5, fontweight="bold", color=col)

    # Amdahl's Law curve fitted to largest N at kmax
    nmax = sizes[-1]
    s_max = calc_speedup_s1(dataset, nmax, kmax)
    p_cont = np.linspace(1, kmax, 100)
    alpha = max(0.0005, ((float(kmax) / s_max) - 1.0) / float(kmax - 1)) if kmax > 1 else 0.0
    amdahl = 1.0 / (alpha + (1.0 - alpha) / p_cont)
    ax.plot(p_cont, amdahl, "r:", linewidth=1.8, label=rf"Закон Амдала ($\alpha = {alpha*100:.2f}\%$)")

    ax.set_title(f"Прискорення $S_1(k) = T_1 / T_k$ залежно від воркерів\n[{env_name}]")
    ax.set_xlabel("Кількість активних воркерів ($k$)")
    ax.set_ylabel(r"Коефіцієнт прискорення ($S_1(k) = T_1 / T_k$)")
    ax.set_xticks(ks)
    ax.set_xlim(0.8, kmax + 0.3)
    ax.set_ylim(0.8, kmax + 0.4)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper left", frameon=True, framealpha=0.95)

    out_path = os.path.join(PLOTS_DIR, f"{prefix}speedup_comparison.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"Saved: {out_path}")


def plot_efficiency(dataset, prefix="", env_name="Local Docker Cluster"):
    sizes, ks = get_sizes_and_workers(dataset)
    kmax = max(ks)
    fig, ax = plt.subplots(figsize=(8.2, 5.8), dpi=300)

    ax.axhline(100.0, color="k", linestyle="--", linewidth=1.5, label="Ідеальна ефективність (100%)")

    min_eff = 100.0
    for idx, n_val in enumerate(sizes):
        col = PALETTE[idx % len(PALETTE)]
        mk = MARKERS[idx % len(MARKERS)]
        effs = [(calc_speedup_s1(dataset, n_val, k) / float(k)) * 100.0 for k in ks]
        min_eff = min(min_eff, min(effs))
        ax.plot(ks, effs, marker=mk, color=col, linewidth=2.2, markersize=7.5,
                label=f"Ефективність ({format_n_label(n_val)})")
        if idx in (0, len(sizes) - 1):
            for k, eff in zip(ks, effs):
                dy = 7 if idx == len(sizes) - 1 else -13
                ax.annotate(f"{eff:.1f}%", (k, eff), textcoords="offset points", xytext=(0, dy),
                            ha="center", fontsize=8.5, fontweight="bold", color=col)

    ax.set_title(f"Ефективність паралелізації $E_1(k) = S_1(k)/k$\n[{env_name}]")
    ax.set_xlabel("Кількість активних воркерів ($k$)")
    ax.set_ylabel(r"Ефективність паралельних обчислень ($\%$)")
    ax.set_xticks(ks)
    ax.set_xlim(0.8, kmax + 0.3)
    ax.set_ylim(max(50.0, min_eff - 10.0), 106.0)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="lower left", frameon=True, framealpha=0.95)

    out_path = os.path.join(PLOTS_DIR, f"{prefix}efficiency_comparison.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"Saved: {out_path}")


def plot_execution_time(dataset, prefix="", env_name="Local Docker Cluster"):
    sizes, ks = get_sizes_and_workers(dataset)
    kmax = max(ks)
    fig, ax = plt.subplots(figsize=(8.2, 5.8), dpi=300)

    for idx, n_val in enumerate(sizes):
        col = PALETTE[idx % len(PALETTE)]
        mk = MARKERS[idx % len(MARKERS)]
        means = [dataset[n_val][k]["mean"] for k in ks]
        stds = [dataset[n_val][k]["std"] for k in ks]
        ax.errorbar(ks, means, yerr=stds, marker=mk, color=col, linewidth=2.2,
                    markersize=7.5, capsize=3, label=format_n_label(n_val))
        for k, t in zip(ks, means):
            ax.annotate(f"{t:.2f} с", (k, t), textcoords="offset points", xytext=(0, 7),
                        ha="center", fontsize=8.5, fontweight="bold", color=col)

    ax.set_title(f"Час виконання $T_k$ залежно від кількості воркерів\n[{env_name}]")
    ax.set_xlabel("Кількість активних воркерів ($k$)")
    ax.set_ylabel("Середній час виконання (секунди)")
    ax.set_xticks(ks)
    ax.set_xlim(0.8, kmax + 0.3)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper right", frameon=True, framealpha=0.95)

    out_path = os.path.join(PLOTS_DIR, f"{prefix}execution_time.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"Saved: {out_path}")


def plot_dashboard(dataset, prefix="", env_name="Local Docker Cluster"):
    sizes, ks = get_sizes_and_workers(dataset)
    kmax = max(ks)
    has_seq = all(0 in dataset[n] for n in sizes)

    fig, axes = plt.subplots(2, 2, figsize=(14, 11), dpi=300)
    fig.suptitle(f"Аналіз продуктивності кластера PARCS-Python\n[{env_name}]", fontsize=15)

    # 1. Execution Time T_k(k)
    ax1 = axes[0, 0]
    for idx, n_val in enumerate(sizes):
        col = PALETTE[idx % len(PALETTE)]
        mk = MARKERS[idx % len(MARKERS)]
        means = [dataset[n_val][k]["mean"] for k in ks]
        stds = [dataset[n_val][k]["std"] for k in ks]
        ax1.errorbar(ks, means, yerr=stds, marker=mk, color=col, linewidth=2,
                     markersize=6.5, capsize=3, label=format_n_label(n_val))
    ax1.set_title("А. Час виконання $T_k(k)$")
    ax1.set_xlabel("Воркери ($k$)")
    ax1.set_ylabel("Час (секунди)")
    ax1.set_xticks(ks)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper right")

    # 2. Speedup S_1(k)
    ax2 = axes[0, 1]
    ax2.plot([1, kmax], [1, kmax], "k--", linewidth=1.5, label=r"Ідеальне $S_1 = k$")
    for idx, n_val in enumerate(sizes):
        col = PALETTE[idx % len(PALETTE)]
        mk = MARKERS[idx % len(MARKERS)]
        s_vals = [calc_speedup_s1(dataset, n_val, k) for k in ks]
        ax2.plot(ks, s_vals, marker=mk, color=col, linewidth=2, markersize=6.5,
                 label=format_n_label(n_val))
    nmax = sizes[-1]
    s_max = calc_speedup_s1(dataset, nmax, kmax)
    p_cont = np.linspace(1, kmax, 100)
    alpha = max(0.0005, ((float(kmax) / s_max) - 1.0) / float(kmax - 1)) if kmax > 1 else 0.0
    ax2.plot(p_cont, 1.0 / (alpha + (1.0 - alpha) / p_cont), "r:", linewidth=1.6,
             label=rf"Амдал ($\alpha={alpha*100:.2f}\%$)")
    ax2.set_title(r"Б. Прискорення $S_1(k) = T_1 / T_k$")
    ax2.set_xlabel("Воркери ($k$)")
    ax2.set_ylabel(r"Прискорення ($S_1$)")
    ax2.set_xticks(ks)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="upper left")

    # 3. Efficiency E_1(k)
    ax3 = axes[1, 0]
    ax3.axhline(100.0, color="k", linestyle="--", linewidth=1.5, label="Ідеальна (100%)")
    min_eff = 100.0
    for idx, n_val in enumerate(sizes):
        col = PALETTE[idx % len(PALETTE)]
        mk = MARKERS[idx % len(MARKERS)]
        effs = [(calc_speedup_s1(dataset, n_val, k) / float(k)) * 100.0 for k in ks]
        min_eff = min(min_eff, min(effs))
        ax3.plot(ks, effs, marker=mk, color=col, linewidth=2, markersize=6.5,
                 label=format_n_label(n_val))
    ax3.set_title(r"В. Ефективність паралелізації $E_1(k)$")
    ax3.set_xlabel("Воркери ($k$)")
    ax3.set_ylabel("Ефективність (%)")
    ax3.set_xticks(ks)
    ax3.set_ylim(max(50.0, min_eff - 10.0), 106.0)
    ax3.grid(True, linestyle=":", alpha=0.6)
    ax3.legend(loc="lower left")

    # 4. Scaling with Problem Size N (including seq if present)
    ax4 = axes[1, 1]
    n_millions = [n / 1e6 for n in sizes]
    if has_seq:
        t_seq = [dataset[n][0]["mean"] for n in sizes]
        ax4.plot(n_millions, t_seq, "s--", color="#222222", linewidth=2, markersize=6.5, label="Послідовно (seq)")
    worker_colors = {1: "#1f77b4", 2: "#ff7f0e", 3: "#9467bd", 4: "#2ca02c"}
    for idx, k in enumerate(ks):
        col = worker_colors.get(k, PALETTE[idx % len(PALETTE)])
        mk = MARKERS[idx % len(MARKERS)]
        t_n = [dataset[n][k]["mean"] for n in sizes]
        lbl = f"{k} воркер" if k == 1 else f"{k} воркери"
        ax4.plot(n_millions, t_n, marker=mk, color=col, linewidth=2, markersize=6.5, label=lbl)
    ax4.set_title("Г. Масштабування $T(N)$ від розміру задачі")
    ax4.set_xlabel("Кількість кроків $N$ (млн)")
    ax4.set_ylabel("Час (секунди)")
    ax4.set_xticks(n_millions)
    ax4.grid(True, linestyle=":", alpha=0.6)
    ax4.legend(loc="upper left")

    plt.tight_layout()
    out_path = os.path.join(PLOTS_DIR, f"{prefix}performance_dashboard.png")
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"Saved: {out_path}")


def main():
    local_data = (
        load_summary_csv(os.path.join(SCRIPT_DIR, "results-local", "summary.csv"))
        or load_legacy_json(os.path.join(SCRIPT_DIR, "cluster_benchmark_results.json"))
    )
    if local_data:
        print("Generating Local Docker visualizations...")
        plot_speedup(local_data, prefix="", env_name="Local Docker Cluster (CPU-pinned)")
        plot_efficiency(local_data, prefix="", env_name="Local Docker Cluster (CPU-pinned)")
        plot_execution_time(local_data, prefix="", env_name="Local Docker Cluster (CPU-pinned)")
        plot_dashboard(local_data, prefix="", env_name="Local Docker Cluster (CPU-pinned)")

    gcp_data = (
        load_summary_csv(os.path.join(SCRIPT_DIR, "results-cloud", "summary.csv"))
        or load_legacy_json(os.path.join(SCRIPT_DIR, "gcp_benchmark_results.json"))
    )
    if gcp_data:
        print("\nGenerating Google Cloud Platform visualizations...")
        plot_speedup(gcp_data, prefix="gcp_", env_name="Google Cloud Platform (Compute Engine)")
        plot_efficiency(gcp_data, prefix="gcp_", env_name="Google Cloud Platform (Compute Engine)")
        plot_execution_time(gcp_data, prefix="gcp_", env_name="Google Cloud Platform (Compute Engine)")
        plot_dashboard(gcp_data, prefix="gcp_", env_name="Google Cloud Platform (Compute Engine)")

    print("\nAll benchmark visualizations generated successfully!")


if __name__ == "__main__":
    main()
