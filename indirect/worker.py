#!/usr/bin/env python3
"""
RabbitMQ worker for the Concert Ticket Acquisition System.

Consumes messages from the `ticket_requests` queue, processes them via
the Redis TicketStore, and publishes results to `ticket_results`.

Supports dynamic scaling: start/stop workers at any time.

Usage:
    python indirect/worker.py                       # single worker
    python indirect/worker.py --prefetch 20         # tuned prefetch
    python indirect/worker.py --worker-id w1        # named worker
"""

import argparse
import json
import signal
import sys

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
from shared.redis_backend import TicketStore


class TicketWorker:
    """Consumes ticket requests from RabbitMQ and processes them."""

    def __init__(self, worker_id: str = "worker-0", prefetch: int = 10):
        self.worker_id = worker_id
        self.prefetch = prefetch
        self.store = TicketStore()
        self._connection = None
        self._channel = None

    def connect(self):
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            virtual_host=RABBITMQ_VHOST,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300,
        )
        self._connection = pika.BlockingConnection(params)
        self._channel = self._connection.channel()

        # Declare queues (idempotent)
        self._channel.queue_declare(queue=RABBITMQ_REQUEST_QUEUE, durable=True)
        self._channel.queue_declare(queue=RABBITMQ_RESPONSE_QUEUE, durable=True)

        # Fair dispatch
        self._channel.basic_qos(prefetch_count=self.prefetch)

    def _on_request(self, ch, method, properties, body):
        """Process a single ticket request."""
        try:
            msg = json.loads(body)
            op_type = msg.get("type", "unnumbered")

            if op_type == "unnumbered":
                result = self.store.buy_unnumbered(
                    msg["client_id"], msg["request_id"]
                )
            else:
                result = self.store.buy_numbered(
                    msg["client_id"], msg["seat_id"], msg["request_id"]
                )

            result["worker_id"] = self.worker_id

        except Exception as exc:
            result = {
                "status": "ERROR",
                "error": str(exc),
                "worker_id": self.worker_id,
            }

        # Publish result
        self._channel.basic_publish(
            exchange="",
            routing_key=RABBITMQ_RESPONSE_QUEUE,
            body=json.dumps(result),
            properties=pika.BasicProperties(
                correlation_id=getattr(properties, "correlation_id", None),
                delivery_mode=2,  # persistent
            ),
        )

        # Ack original message
        ch.basic_ack(delivery_tag=method.delivery_tag)

    def run(self):
        """Start consuming (blocking)."""
        self.connect()
        self._channel.basic_consume(
            queue=RABBITMQ_REQUEST_QUEUE,
            on_message_callback=self._on_request,
        )

        # Graceful shutdown
        def _shutdown(signum, frame):
            print(f"\n[{self.worker_id}] Shutting down…")
            self._channel.stop_consuming()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        print(f"[{self.worker_id}] Waiting for requests (prefetch={self.prefetch})…")
        try:
            self._channel.start_consuming()
        except Exception:
            pass
        finally:
            if self._connection and self._connection.is_open:
                self._connection.close()
            print(f"[{self.worker_id}] Stopped.")


def main():
    parser = argparse.ArgumentParser(description="RabbitMQ ticket worker")
    parser.add_argument("--worker-id", default="worker-0", help="Unique worker name")
    parser.add_argument("--prefetch", type=int, default=10, help="Prefetch count")
    args = parser.parse_args()

    worker = TicketWorker(worker_id=args.worker_id, prefetch=args.prefetch)
    worker.run()


if __name__ == "__main__":
    main()
