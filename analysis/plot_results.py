#!/usr/bin/env python3
"""
Generate performance plots from benchmark result JSON files.

Usage:
    python analysis/plot_results.py \\
        --results results_direct_unnumbered.json \\
                  results_direct_numbered.json \\
                  results_indirect_unnumbered.json \\
                  results_indirect_numbered.json \\
        --output-dir analysis/plots

    # Compare scalability across worker counts
    python analysis/plot_results.py \\
        --scalability results_1w.json results_2w.json results_4w.json results_8w.json \\
        --output-dir analysis/plots
"""

import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")               # headless backend for servers
import matplotlib.pyplot as plt


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


# ─── Plot 1: Throughput comparison bar chart ─────────────────────────

def plot_throughput_comparison(result_files: list[str], out_dir: str):
    """Bar chart comparing throughput across architectures and ticket models."""
    labels, values = [], []
    for path in result_files:
        data = load(path)
        name = os.path.basename(path).replace("results_", "").replace(".json", "")
        labels.append(name)
        values.append(data.get("throughput_ops", 0))

    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ["#2196F3", "#4CAF50", "#FF9800", "#F44336"][:len(labels)]
    bars = ax.bar(labels, values, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_ylabel("Throughput (ops/s)")
    ax.set_title("Throughput Comparison")
    ax.bar_label(bars, fmt="%.0f")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "throughput_comparison.png"), dpi=150)
    plt.close(fig)
    print(f"  → throughput_comparison.png")


# ─── Plot 2: Success / Rejected / Error stacked bars ────────────────

def plot_outcome_breakdown(result_files: list[str], out_dir: str):
    """Stacked bar chart of success/rejected/error counts."""
    labels = []
    success_vals, rejected_vals, error_vals = [], [], []

    for path in result_files:
        data = load(path)
        name = os.path.basename(path).replace("results_", "").replace(".json", "")
        labels.append(name)
        success_vals.append(data.get("success", 0))
        rejected_vals.append(data.get("rejected", 0))
        error_vals.append(data.get("errors", 0))

    fig, ax = plt.subplots(figsize=(10, 5))
    x = range(len(labels))
    ax.bar(x, success_vals, label="Success", color="#4CAF50")
    ax.bar(x, rejected_vals, bottom=success_vals, label="Rejected", color="#FF9800")
    bottoms = [s + r for s, r in zip(success_vals, rejected_vals)]
    ax.bar(x, error_vals, bottom=bottoms, label="Error", color="#F44336")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Requests")
    ax.set_title("Request Outcome Breakdown")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "outcome_breakdown.png"), dpi=150)
    plt.close(fig)
    print(f"  → outcome_breakdown.png")


# ─── Plot 3: Scalability – Throughput vs workers ────────────────────

def plot_scalability(result_files: list[str], out_dir: str):
    """Line plot of throughput vs. number of workers (files ordered by worker count)."""
    points = []
    for i, path in enumerate(result_files, start=1):
        data = load(path)
        workers = data.get("workers", i)       # fallback to file index
        points.append((workers, data.get("throughput_ops", 0)))
    points.sort()

    xs, ys = zip(*points)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xs, ys, "o-", color="#2196F3", linewidth=2, markersize=8)
    ax.set_xlabel("Number of Workers")
    ax.set_ylabel("Throughput (ops/s)")
    ax.set_title("Scalability: Throughput vs Workers")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "scalability.png"), dpi=150)
    plt.close(fig)
    print(f"  → scalability.png")


# ─── Plot 4: Latency distribution histogram ─────────────────────────

def plot_latency_distribution(result_files: list[str], out_dir: str):
    """Histogram of per-request latencies."""
    for path in result_files:
        data = load(path)
        name = os.path.basename(path).replace("results_", "").replace(".json", "")
        latencies = [d.get("latency_ms", 0) for d in data.get("details", [])]
        if not latencies:
            continue

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.hist(latencies, bins=80, color="#673AB7", edgecolor="white", alpha=0.85)
        ax.set_xlabel("Latency (ms)")
        ax.set_ylabel("Count")
        ax.set_title(f"Latency Distribution – {name}")
        ax.axvline(sum(latencies)/len(latencies), color="red", linestyle="--",
                    label=f"avg={sum(latencies)/len(latencies):.1f}ms")
        ax.legend()
        fig.tight_layout()
        fname = f"latency_{name}.png"
        fig.savefig(os.path.join(out_dir, fname), dpi=150)
        plt.close(fig)
        print(f"  → {fname}")


# ─── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate benchmark analysis plots")
    parser.add_argument("--results", nargs="+", help="Result JSON files for comparison")
    parser.add_argument("--scalability", nargs="+", help="Result JSONs ordered by worker count")
    parser.add_argument("--output-dir", default="analysis/plots", help="Directory for PNG files")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    print(f"Saving plots to {args.output_dir}/\n")

    if args.results:
        plot_throughput_comparison(args.results, args.output_dir)
        plot_outcome_breakdown(args.results, args.output_dir)
        plot_latency_distribution(args.results, args.output_dir)

    if args.scalability:
        plot_scalability(args.scalability, args.output_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
