#!/usr/bin/env python3
"""
Benchmark client for the Direct (REST) architecture.

Reads a benchmark file and sends concurrent HTTP POST requests to the
REST API via aiohttp.  Records per-request latency and writes a JSON
results file.

Usage:
    # Unnumbered benchmark
    python direct/client.py \\
        --benchmark benchmarks/benchmark_unnumbered.txt \\
        --url http://localhost:8080 \\
        --concurrency 200 \\
        --output results_direct_unnumbered.json

    # Numbered benchmark
    python direct/client.py \\
        --benchmark benchmarks/benchmark_numbered.txt \\
        --url http://localhost:8080 \\
        --concurrency 200 \\
        --output results_direct_numbered.json
"""

import argparse
import asyncio
import json
import time

import aiohttp


def parse_benchmark(path: str) -> list[dict]:
    """
    Parse benchmark file.
    Unnumbered: BUY <client_id> <request_id>
    Numbered:   BUY <client_id> <seat_id> <request_id>
    """
    ops = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 3:
                # BUY client_id request_id  →  unnumbered
                ops.append({
                    "type": "unnumbered",
                    "client_id": parts[1],
                    "request_id": parts[2],
                })
            elif len(parts) == 4:
                # BUY client_id seat_id request_id  →  numbered
                ops.append({
                    "type": "numbered",
                    "client_id": parts[1],
                    "seat_id": parts[2],
                    "request_id": parts[3],
                })
    return ops


async def send_request(
    session: aiohttp.ClientSession,
    base_url: str,
    op: dict,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Send a single buy request and return timing + result."""
    if op["type"] == "unnumbered":
        url = f"{base_url}/buy/unnumbered"
        payload = {"client_id": op["client_id"], "request_id": op["request_id"]}
    else:
        url = f"{base_url}/buy/numbered"
        payload = {
            "client_id": op["client_id"],
            "seat_id": op["seat_id"],
            "request_id": op["request_id"],
        }

    async with semaphore:
        t0 = time.perf_counter()
        try:
            async with session.post(url, json=payload) as resp:
                body = await resp.json()
                latency = time.perf_counter() - t0
                return {
                    "request_id": op["request_id"],
                    "status": body.get("status", "ERROR"),
                    "latency_ms": round(latency * 1000, 2),
                }
        except Exception as exc:
            latency = time.perf_counter() - t0
            return {
                "request_id": op["request_id"],
                "status": "ERROR",
                "error": str(exc),
                "latency_ms": round(latency * 1000, 2),
            }


async def run_benchmark(base_url: str, ops: list[dict], concurrency: int) -> dict:
    """Execute all operations concurrently and return aggregated results."""
    semaphore = asyncio.Semaphore(concurrency)

    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency)
    async with aiohttp.ClientSession(connector=connector) as session:
        t_start = time.perf_counter()
        tasks = [send_request(session, base_url, op, semaphore) for op in ops]
        results = await asyncio.gather(*tasks)
        t_total = time.perf_counter() - t_start

    success = sum(1 for r in results if r["status"] == "OK")
    rejected = sum(1 for r in results if r["status"] == "REJECTED")
    errors = sum(1 for r in results if r["status"] == "ERROR")
    latencies = [r["latency_ms"] for r in results]

    return {
        "architecture": "direct",
        "total_requests": len(ops),
        "success": success,
        "rejected": rejected,
        "errors": errors,
        "total_time_s": round(t_total, 3),
        "throughput_ops": round(len(ops) / t_total, 1),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
        "max_latency_ms": round(max(latencies), 2),
        "min_latency_ms": round(min(latencies), 2),
        "concurrency": concurrency,
        "details": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Direct (REST) benchmark client")
    parser.add_argument("--benchmark", required=True, help="Path to benchmark file")
    parser.add_argument("--url", default="http://localhost:8080", help="Base URL of REST API (or NGINX)")
    parser.add_argument("--concurrency", type=int, default=200, help="Max concurrent requests")
    parser.add_argument("--output", default="results_direct.json", help="Output JSON file")
    args = parser.parse_args()

    ops = parse_benchmark(args.benchmark)
    print(f"Loaded {len(ops)} operations from {args.benchmark}")
    print(f"Target: {args.url}  |  Concurrency: {args.concurrency}")

    summary = asyncio.run(run_benchmark(args.url, ops, args.concurrency))

    # Write full report
    with open(args.output, "w") as f:
        json.dump(summary, f, indent=2)

    # Console summary
    print(f"\n{'='*50}")
    print(f"  Total time:    {summary['total_time_s']} s")
    print(f"  Throughput:    {summary['throughput_ops']} ops/s")
    print(f"  Success:       {summary['success']}")
    print(f"  Rejected:      {summary['rejected']}")
    print(f"  Errors:        {summary['errors']}")
    print(f"  Avg latency:   {summary['avg_latency_ms']} ms")
    print(f"{'='*50}")
    print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
