#!/usr/bin/env python3
"""
Benchmark client for the Indirect (RabbitMQ) architecture.

Reads a benchmark file, publishes every operation to the `ticket_requests`
queue, then consumes results from `ticket_results` until all responses
are collected (or a timeout fires).

Usage:
    python indirect/client.py \\
        --benchmark benchmarks/benchmark_unnumbered.txt \\
        --concurrency 200 \\
        --output results_indirect_unnumbered.json
"""

import argparse
import json
import threading
import time
from collections import Counter

import pika

from shared.config import (
    RABBITMQ_HOST,
    RABBITMQ_PORT,
    RABBITMQ_USER,
    RABBITMQ_PASS,
    RABBITMQ_VHOST,
    RABBITMQ_REQUEST_QUEUE,
    RABBITMQ_RESPONSE_QUEUE,
)


def read_server_metrics() -> dict | None:
    """Best-effort read of server-side metrics from Redis (workers record them).

    The client may run on a different host; if Redis is not reachable from
    here, the per-worker breakdown is still derived from the result messages.
    """
    try:
        from shared.redis_backend import read_metrics
        return read_metrics("indirect")
    except Exception as exc:
        print(f"[warn] could not read server metrics from Redis: {exc}")
        return None


def reset_server_state() -> None:
    """Best-effort reset of ticket/dedup/metric state for a clean run."""
    try:
        from shared.redis_backend import reset_all
        reset_all()
    except Exception as exc:
        print(f"[warn] could not reset Redis state: {exc}")


def parse_benchmark(path: str) -> list[dict]:
    ops = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 3:
                ops.append({
                    "type": "unnumbered",
                    "client_id": parts[1],
                    "request_id": parts[2],
                })
            elif len(parts) == 4:
                ops.append({
                    "type": "numbered",
                    "client_id": parts[1],
                    "seat_id": parts[2],
                    "request_id": parts[3],
                })
    return ops


class BenchmarkProducer:
    """Publishes benchmark requests and collects results."""

    def __init__(self, concurrency: int = 200, timeout: int = 300):
        self.concurrency = concurrency
        self.timeout = timeout
        self.results: dict[str, dict] = {}      # correlation_id → result
        self._send_times: dict[str, float] = {}  # correlation_id → timestamp
        self._expected = 0
        self._lock = threading.Lock()
        self._done = threading.Event()

    def _get_connection(self):
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            virtual_host=RABBITMQ_VHOST,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300,
        )
        return pika.BlockingConnection(params)

    def _result_consumer(self):
        """Consume results in a background thread."""
        conn = self._get_connection()
        ch = conn.channel()
        ch.queue_declare(queue=RABBITMQ_RESPONSE_QUEUE, durable=True)
        ch.basic_qos(prefetch_count=100)

        def _on_result(_ch, method, properties, body):
            result = json.loads(body)
            corr_id = properties.correlation_id
            t_recv = time.perf_counter()

            with self._lock:
                t_send = self._send_times.get(corr_id, t_recv)
                result["latency_ms"] = round((t_recv - t_send) * 1000, 2)
                self.results[corr_id] = result

                if len(self.results) >= self._expected:
                    self._done.set()

            _ch.basic_ack(delivery_tag=method.delivery_tag)

        ch.basic_consume(queue=RABBITMQ_RESPONSE_QUEUE, on_message_callback=_on_result)

        # Consume until done or timeout
        while not self._done.is_set():
            conn.process_data_events(time_limit=1)

        try:
            conn.close()
        except Exception:
            pass

    def run(self, ops: list[dict]) -> dict:
        self._expected = len(ops)

        # Purge old results
        pub_conn = self._get_connection()
        pub_ch = pub_conn.channel()
        pub_ch.queue_declare(queue=RABBITMQ_REQUEST_QUEUE, durable=True)
        pub_ch.queue_declare(queue=RABBITMQ_RESPONSE_QUEUE, durable=True)
        pub_ch.queue_purge(queue=RABBITMQ_RESPONSE_QUEUE)

        # Start result consumer thread
        consumer_thread = threading.Thread(target=self._result_consumer, daemon=True)
        consumer_thread.start()

        # Publish all requests
        print(f"Publishing {len(ops)} requests…")
        t_start = time.perf_counter()

        for op in ops:
            corr_id = op["request_id"]
            self._send_times[corr_id] = time.perf_counter()

            pub_ch.basic_publish(
                exchange="",
                routing_key=RABBITMQ_REQUEST_QUEUE,
                body=json.dumps(op),
                properties=pika.BasicProperties(
                    correlation_id=corr_id,
                    delivery_mode=2,
                ),
            )

        pub_conn.close()
        t_published = time.perf_counter() - t_start
        print(f"All requests published in {t_published:.2f}s.  Waiting for results…")

        # Wait for all results
        self._done.wait(timeout=self.timeout)
        t_total = time.perf_counter() - t_start

        # Aggregate
        all_results = list(self.results.values())
        success = sum(1 for r in all_results if r.get("status") == "OK")
        rejected = sum(1 for r in all_results if r.get("status") == "REJECTED")
        errors = sum(1 for r in all_results if r.get("status") == "ERROR")
        latencies = [r.get("latency_ms", 0) for r in all_results]

        # Load distribution across workers, derived from the result messages
        # (each result carries the worker_id that processed it).
        by_node = dict(Counter(r["worker_id"] for r in all_results if r.get("worker_id")))

        return {
            "architecture": "indirect",
            "total_requests": len(ops),
            "responses_received": len(all_results),
            "success": success,
            "rejected": rejected,
            "errors": errors,
            # ── client-side (end-to-end, includes queue wait) view ──
            "total_time_s": round(t_total, 3),
            "publish_time_s": round(t_published, 3),
            "throughput_ops": round(len(ops) / t_total, 1) if t_total > 0 else 0,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "max_latency_ms": round(max(latencies), 2) if latencies else 0,
            "min_latency_ms": round(min(latencies), 2) if latencies else 0,
            "client_by_node": by_node,
            "details": all_results,
        }


def main():
    parser = argparse.ArgumentParser(description="Indirect (RabbitMQ) benchmark client")
    parser.add_argument("--benchmark", required=True, help="Path to benchmark file")
    parser.add_argument("--concurrency", type=int, default=200, help="(reserved for future use)")
    parser.add_argument("--timeout", type=int, default=300, help="Max wait seconds for results")
    parser.add_argument("--output", default="results_indirect.json", help="Output JSON file")
    parser.add_argument("--reset", action=argparse.BooleanOptionalAction, default=True,
                        help="Reset Redis ticket/dedup/metric state before the run")
    args = parser.parse_args()

    ops = parse_benchmark(args.benchmark)
    print(f"Loaded {len(ops)} operations from {args.benchmark}")

    if args.reset:
        reset_server_state()

    producer = BenchmarkProducer(concurrency=args.concurrency, timeout=args.timeout)
    summary = producer.run(ops)

    # Server-side metrics (recorded by the workers themselves, read via Redis)
    server = read_server_metrics()
    if server:
        summary["server_metrics"] = server

    with open(args.output, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*50}")
    print(f"  CLIENT (end-to-end, includes queue wait)")
    print(f"  Total time:      {summary['total_time_s']} s")
    print(f"  Publish time:    {summary['publish_time_s']} s")
    print(f"  Throughput:      {summary['throughput_ops']} ops/s")
    print(f"  Success:         {summary['success']}")
    print(f"  Rejected:        {summary['rejected']}")
    print(f"  Errors:          {summary['errors']}")
    print(f"  Responses:       {summary['responses_received']}/{summary['total_requests']}")
    print(f"  Avg latency:     {summary['avg_latency_ms']} ms")
    if server:
        print(f"  {'-'*46}")
        print(f"  SERVER-SIDE (measured on workers, via Redis)")
        print(f"  Throughput:      {server['server_throughput_ops']} ops/s "
              f"(window {server['server_window_s']} s)")
        print(f"  Avg latency:     {server['server_avg_latency_ms']} ms (service time)")
        print(f"  Workers:         {server['workers']}  ->  {server['by_node']}")
        print(f"  Replays:         {server['replays']} (redeliveries deduped)")
    print(f"{'='*50}")
    print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
