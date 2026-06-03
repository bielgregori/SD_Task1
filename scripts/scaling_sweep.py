#!/usr/bin/env python3
"""
Dynamic-scaling sweep for the Indirect (RabbitMQ) architecture.

Runs the same benchmark with an increasing number of workers and records one
result file per worker count, so you can plot server-side throughput vs. number
of workers (the "workers graph").  Each step starts the workers, runs the
client, then stops the workers — demonstrating that workers can be added and
removed between runs without touching the queue, the client, or Redis.

Prerequisites: Redis + RabbitMQ running and reachable.

Usage:
    export PYTHONPATH=$(pwd)
    python scripts/scaling_sweep.py \
        --benchmark benchmarks/benchmark_unnumbered.txt \
        --workers 1 2 4 8 --output-dir results
"""

import argparse
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from shared.redis_backend import reset_all, read_metrics    # noqa: E402

_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}


def _spawn_workers(n: int) -> list[subprocess.Popen]:
    procs = []
    for i in range(1, n + 1):
        procs.append(subprocess.Popen(
            [sys.executable, os.path.join("indirect", "worker.py"),
             "--worker-id", f"w{i}"],
            cwd=PROJECT_ROOT, env=_ENV,
        ))
    return procs


def _stop(procs: list[subprocess.Popen]):
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def main():
    ap = argparse.ArgumentParser(description="Indirect dynamic-scaling sweep")
    ap.add_argument("--benchmark", default="benchmarks/benchmark_unnumbered.txt")
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--output-dir", default="results")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    produced = []

    for n in args.workers:
        print(f"\n{'='*60}\n  SWEEP STEP: {n} worker(s)\n{'='*60}")
        reset_all()
        procs = _spawn_workers(n)
        time.sleep(1.0)

        out = os.path.join(args.output_dir, f"results_indirect_{n}w.json")
        subprocess.run(
            [sys.executable, os.path.join("indirect", "client.py"),
             "--benchmark", args.benchmark, "--output", out,
             "--timeout", str(args.timeout), "--no-reset"],
            cwd=PROJECT_ROOT, env=_ENV, check=False,
        )
        m = read_metrics("indirect")
        print(f"  -> {n} workers: server throughput "
              f"{m['server_throughput_ops']} ops/s, by_node={m['by_node']}")
        _stop(procs)
        produced.append(out)

    print(f"\nResult files: {produced}")
    print("Plot with:")
    print(f"  python analysis/plot_results.py --scalability {' '.join(produced)} "
          f"--output-dir analysis/plots")


if __name__ == "__main__":
    main()
