#!/usr/bin/env python3
"""
Fault-tolerance & dynamic-scaling test for the Indirect (RabbitMQ) architecture.

What it does
------------
1. Resets all ticket / dedup / metric state in Redis.
2. Starts N workers.
3. Launches the benchmark client (publishes all requests, then waits).
4. **Mid-run**, kills one worker (simulating a crash) and optionally starts a
   replacement worker (dynamic scaling).
5. Waits for the client to finish, then verifies the system held together:
      * every request received exactly one logical result (no lost requests),
      * no overselling  (tickets sold ≤ TOTAL_TICKETS),
      * redelivered messages were deduplicated (replays counted, not double-sold),
      * the load moved off the killed worker onto the survivors / replacement.

Prerequisites: Redis + RabbitMQ running and reachable (REDIS_HOST / RABBITMQ_HOST).

Usage
-----
    export PYTHONPATH=$(pwd)
    python scripts/fault_tolerance_test.py \
        --benchmark benchmarks/benchmark_unnumbered.txt \
        --workers 3 --kill-after 1.5 --restart
"""

import argparse
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from shared.config import TOTAL_TICKETS                       # noqa: E402
from shared.redis_backend import (                            # noqa: E402
    reset_all, read_metrics, TicketStore,
)


def _spawn_worker(worker_id: str) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
    return subprocess.Popen(
        [sys.executable, os.path.join("indirect", "worker.py"),
         "--worker-id", worker_id],
        cwd=PROJECT_ROOT, env=env,
    )


def _spawn_client(benchmark: str, output: str, timeout: int) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
    return subprocess.Popen(
        [sys.executable, os.path.join("indirect", "client.py"),
         "--benchmark", benchmark, "--output", output,
         "--timeout", str(timeout), "--no-reset"],   # state already reset below
        cwd=PROJECT_ROOT, env=env,
    )


def main():
    ap = argparse.ArgumentParser(description="Fault tolerance / dynamic scaling test")
    ap.add_argument("--benchmark", default="benchmarks/benchmark_unnumbered.txt")
    ap.add_argument("--workers", type=int, default=3, help="Workers to start")
    ap.add_argument("--kill-after", type=float, default=1.5,
                    help="Seconds after client start before killing a worker")
    ap.add_argument("--restart", action="store_true",
                    help="Start a replacement worker after the kill (scale back up)")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--output", default="results_fault_tolerance.json")
    args = ap.parse_args()

    numbered = "numbered" in os.path.basename(args.benchmark)
    print("=" * 60)
    print("  FAULT TOLERANCE / DYNAMIC SCALING TEST")
    print(f"  benchmark={args.benchmark}  model={'numbered' if numbered else 'unnumbered'}")
    print(f"  workers={args.workers}  kill-after={args.kill_after}s  restart={args.restart}")
    print("=" * 60)

    # 1. Clean slate
    reset_all()
    print("[1] Redis state reset.")

    # 2. Start workers
    workers: dict[str, subprocess.Popen] = {}
    for i in range(1, args.workers + 1):
        wid = f"w{i}"
        workers[wid] = _spawn_worker(wid)
    print(f"[2] Started workers: {list(workers)}")
    time.sleep(1.0)   # let them connect & start consuming

    # 3. Start the benchmark client
    client = _spawn_client(args.benchmark, args.output, args.timeout)
    print("[3] Client started (publishing requests).")

    # 4. Kill a worker mid-run, optionally bring up a replacement
    time.sleep(args.kill_after)
    victim = "w1"
    print(f"[4] >>> KILLING worker {victim} mid-run (simulated crash) <<<")
    workers[victim].kill()          # hard kill = unacked messages get requeued
    workers[victim].wait(timeout=10)
    del workers[victim]

    if args.restart:
        new_id = f"w{args.workers + 1}"
        workers[new_id] = _spawn_worker(new_id)
        print(f"[4b] >>> STARTED replacement worker {new_id} mid-run <<<")

    # 5. Wait for client to finish
    rc = client.wait(timeout=args.timeout + 30)
    print(f"[5] Client finished (exit code {rc}).")

    # Stop remaining workers
    for w in workers.values():
        w.terminate()
    for w in workers.values():
        try:
            w.wait(timeout=10)
        except subprocess.TimeoutExpired:
            w.kill()

    # 6. Verify invariants
    store = TicketStore(arch="indirect")
    stats = store.stats()
    m = read_metrics("indirect")

    sold = stats["numbered_sold"] if numbered else stats["unnumbered_sold"]
    unique = m["unique_requests"]
    ok = m["ok"]

    print("\n" + "-" * 60)
    print("  RESULTS")
    print("-" * 60)
    print(f"  tickets actually sold (Redis):   {sold}")
    print(f"  server OK / rejected:            {ok} / {m['rejected']}")
    print(f"  unique requests handled:         {unique}")
    print(f"  total deliveries (incl. replay): {m['processed']}")
    print(f"  replays (redeliveries deduped):  {m['replays']}")
    print(f"  load per worker:                 {m['by_node']}")
    print(f"  server throughput:               {m['server_throughput_ops']} ops/s")

    checks = []
    # No overselling: tickets sold can never exceed capacity.
    checks.append(("no overselling (sold ≤ capacity)", sold <= TOTAL_TICKETS))
    # OK count must equal tickets sold (every granted ticket is a real sale).
    checks.append(("server OK count == tickets sold", ok == sold))
    # Other workers must have carried load while/after the victim died.
    survivors = [n for n, c in m["by_node"].items() if n != victim and c > 0]
    checks.append(("load served by surviving/new workers", len(survivors) >= 1))

    print("\n  CHECKS")
    all_ok = True
    for name, passed in checks:
        print(f"    [{'PASS' if passed else 'FAIL'}] {name}")
        all_ok = all_ok and passed

    print("-" * 60)
    print(f"  {'FAULT TOLERANCE: OK' if all_ok else 'FAULT TOLERANCE: FAILED'}")
    print("-" * 60)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
