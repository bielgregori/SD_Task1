#!/usr/bin/env python3
"""
Utility to drain and aggregate results from the RabbitMQ response queue.

Useful for debugging or when benchmark_client did not collect all results.

Usage:
    python indirect/results.py --output leftover_results.json --timeout 10
"""

import argparse
import json
import time

import pika

from shared.config import (
    RABBITMQ_HOST,
    RABBITMQ_PORT,
    RABBITMQ_USER,
    RABBITMQ_PASS,
    RABBITMQ_VHOST,
    RABBITMQ_RESPONSE_QUEUE,
)


def drain_results(timeout: int = 10) -> list[dict]:
    """Consume all pending messages from the results queue."""
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=credentials,
    )
    conn = pika.BlockingConnection(params)
    ch = conn.channel()
    ch.queue_declare(queue=RABBITMQ_RESPONSE_QUEUE, durable=True)

    results = []
    deadline = time.time() + timeout

    while time.time() < deadline:
        method, properties, body = ch.basic_get(queue=RABBITMQ_RESPONSE_QUEUE, auto_ack=True)
        if body is None:
            time.sleep(0.1)
            continue
        results.append(json.loads(body))

    conn.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="Drain RabbitMQ result queue")
    parser.add_argument("--output", default="leftover_results.json")
    parser.add_argument("--timeout", type=int, default=10, help="Seconds to poll")
    args = parser.parse_args()

    results = drain_results(timeout=args.timeout)
    print(f"Collected {len(results)} leftover results")

    if results:
        success = sum(1 for r in results if r.get("status") == "OK")
        rejected = sum(1 for r in results if r.get("status") == "REJECTED")
        print(f"  OK: {success}  |  REJECTED: {rejected}")

        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
