"""
Central configuration for the Concert Ticket Acquisition System.
All settings can be overridden via environment variables.
"""

import os


# ─── Redis ───────────────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB   = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# ─── RabbitMQ ────────────────────────────────────────────────────────
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", 5672))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

RABBITMQ_REQUEST_QUEUE  = "ticket_requests"
RABBITMQ_RESPONSE_QUEUE = "ticket_results"

# ─── Ticket system ──────────────────────────────────────────────────
TOTAL_TICKETS = int(os.getenv("TOTAL_TICKETS", 20_000))

# ─── Server ─────────────────────────────────────────────────────────
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8001))

# Identifies this REST server / worker process in the per-node server-side
# metrics.  Defaults are derived per process so two local servers differ.
NODE_ID = os.getenv("NODE_ID", "")

# ─── Benchmark ──────────────────────────────────────────────────────
BENCHMARK_CONCURRENCY = int(os.getenv("BENCHMARK_CONCURRENCY", 100))
