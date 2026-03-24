#!/usr/bin/env python3
"""
Generate benchmark workload files for the ticket acquisition system.

Usage:
    python benchmarks/generate.py                       # normal workloads
    python benchmarks/generate.py --high-contention     # 80% requests → 5% seats
"""

import argparse
import os
import random
import uuid

TOTAL_TICKETS = 20_000
EXTRA_REQUESTS = 5_000          # requests beyond capacity → must be rejected
TOTAL_REQUESTS = TOTAL_TICKETS + EXTRA_REQUESTS
NUM_CLIENTS = 500               # simulated unique clients


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def generate_unnumbered(path: str):
    """Each line: BUY <client_id> <request_id>"""
    with open(path, "w") as f:
        for _ in range(TOTAL_REQUESTS):
            client_id = f"c{random.randint(1, NUM_CLIENTS)}"
            request_id = _uid()
            f.write(f"BUY {client_id} {request_id}\n")
    print(f"[✓] Generated {TOTAL_REQUESTS} unnumbered requests → {path}")


def generate_numbered(path: str, high_contention: bool = False):
    """
    Each line: BUY <client_id> <seat_id> <request_id>

    Normal mode:    seats drawn uniformly from 1..20000
    High contention: 80% of requests target seats 1..1000 (5% of seats)
    """
    with open(path, "w") as f:
        for _ in range(TOTAL_REQUESTS):
            client_id = f"c{random.randint(1, NUM_CLIENTS)}"
            request_id = _uid()

            if high_contention and random.random() < 0.80:
                seat_id = random.randint(1, int(TOTAL_TICKETS * 0.05))  # 1..1000
            else:
                seat_id = random.randint(1, TOTAL_TICKETS)

            f.write(f"BUY {client_id} {seat_id} {request_id}\n")
    mode = "high-contention" if high_contention else "normal"
    print(f"[✓] Generated {TOTAL_REQUESTS} numbered requests ({mode}) → {path}")


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark files")
    parser.add_argument(
        "--high-contention",
        action="store_true",
        help="80%% of numbered requests target 5%% of seats",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(os.path.dirname(__file__)),
        help="Directory for output files",
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    unnumbered_path = os.path.join(args.output_dir, "benchmark_unnumbered.txt")
    numbered_path = os.path.join(args.output_dir, "benchmark_numbered.txt")

    if args.high_contention:
        numbered_path = os.path.join(args.output_dir, "benchmark_numbered_highcont.txt")

    generate_unnumbered(unnumbered_path)
    generate_numbered(numbered_path, high_contention=args.high_contention)


if __name__ == "__main__":
    main()
