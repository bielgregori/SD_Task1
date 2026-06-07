# Concert Ticket Acquisition System

A scalable distributed ticket system for 20,000 concert tickets.  
Implements **two communication architectures** (REST direct + RabbitMQ indirect) with a **Redis consistency backend**.

## Architecture Overview

```
┌─────────┐         ┌───────────┐         ┌───────┐
│  Client  │──HTTP──▶│   NGINX   │──RR────▶│ FastAPI│──┐
│(benchmark│         │   :8080   │         │ :8001  │  │    ┌───────┐
│  runner) │         └───────────┘         │ :8002  │──┼───▶│ Redis │
└─────────┘                                │  ...   │  │    └───────┘
                                           └────────┘  │
┌─────────┐         ┌───────────┐         ┌─────────┐ │
│  Client  │──AMQP──▶│ RabbitMQ  │──consume▶│ Worker  │─┘
│(benchmark│         │           │◀─publish─│ Worker  │
│  runner) │◀────────│           │         │  ...    │
└─────────┘         └───────────┘         └─────────┘
```

## Quick Start (Local Development)

### Prerequisites
- Python 3.11+
- Redis server
- RabbitMQ server

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Generate benchmark files
```bash
python benchmarks/generate.py
python benchmarks/generate.py --high-contention   # optional
```

### 3. Run Direct (REST) architecture
```bash
# Terminal 1 & 2: Start REST servers
uvicorn direct.server:app --host 0.0.0.0 --port 8001 &
uvicorn direct.server:app --host 0.0.0.0 --port 8002 &

# (Optional) Start NGINX load balancer – see direct/nginx.conf

# Terminal 3: Run benchmark
python direct/client.py \
    --benchmark benchmarks/benchmark_unnumbered.txt \
    --url http://localhost:8001 \
    --concurrency 200 \
    --output results_direct_unnumbered.json
```

### 4. Run Indirect (RabbitMQ) architecture
```bash
# Terminal 1: Start workers (start as many as needed)
python indirect/worker.py --worker-id w1 &
python indirect/worker.py --worker-id w2 &

# Terminal 2: Run benchmark
python indirect/client.py \
    --benchmark benchmarks/benchmark_unnumbered.txt \
    --output results_indirect_unnumbered.json
```

### 5. Generate plots
```bash
python analysis/plot_results.py \
    --results results_direct_unnumbered.json results_indirect_unnumbered.json \
    --output-dir analysis/plots
```

## AWS Academy Deployment

### Single VM (everything on one box)
```bash
sudo ./scripts/deploy.sh           # Redis + RabbitMQ + NGINX + deps
./scripts/run_benchmark.sh         # automated sweep
```

### One worker per VM (distributed)
Run each RabbitMQ worker on its **own** EC2 instance, all sharing one central
broker (Redis + RabbitMQ):

```bash
# On the BROKER VM (once) – opens Redis/RabbitMQ for remote workers:
sudo ./scripts/deploy_broker.sh

# On EACH WORKER VM – installs deps + a systemd worker pointing at the broker:
sudo BROKER_HOST=<broker-private-ip> ./scripts/deploy_worker.sh

# On the CLIENT VM – point at the broker and run the benchmark:
export RABBITMQ_HOST=<broker-private-ip> REDIS_HOST=<broker-private-ip>
export RABBITMQ_USER=ticket RABBITMQ_PASS=ticket
python indirect/client.py --benchmark benchmarks/benchmark_unnumbered.txt \
    --output results_indirect_unnumbered.json
```

Each worker VM auto-identifies by its hostname in the per-node metrics, runs as
an auto-restarting `systemd` service (`ticket-worker@1`), and RabbitMQ's fair
dispatch balances load across all VMs. Full walkthrough: **`GUIA_VM_WORKERS.md`**.

See `scripts/deploy.sh` for single-box setup and `scripts/run_benchmark.sh` for the automated sweep.

## Project Structure

```
├── shared/
│   ├── config.py            # Central configuration (env vars)
│   └── redis_backend.py     # Redis ticket store (Lua scripts)
├── direct/
│   ├── server.py            # FastAPI REST API
│   ├── client.py            # Async HTTP benchmark runner
│   └── nginx.conf           # NGINX load balancer config
├── indirect/
│   ├── worker.py            # RabbitMQ consumer worker
│   ├── client.py            # RabbitMQ benchmark producer
│   └── results.py           # Result queue drain utility
├── benchmarks/
│   └── generate.py          # Workload file generator
├── analysis/
│   └── plot_results.py      # Performance plot generator
├── scripts/
│   ├── deploy.sh            # Single-VM setup (Redis+RabbitMQ+NGINX+deps)
│   ├── deploy_broker.sh     # Central broker VM (Redis+RabbitMQ, remote-open)
│   ├── deploy_worker.sh     # Per-worker VM setup + systemd service
│   ├── ticket-worker@.service # systemd template unit (one worker per VM)
│   └── run_benchmark.sh     # Full benchmark sweep
└── requirements.txt
```

## Configuration

All settings via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Redis server address |
| `REDIS_PORT` | `6379` | Redis port |
| `RABBITMQ_HOST` | `localhost` | RabbitMQ address |
| `RABBITMQ_PORT` | `5672` | RabbitMQ port |
| `RABBITMQ_USER` | `guest` | RabbitMQ username |
| `RABBITMQ_PASS` | `guest` | RabbitMQ password |
| `TOTAL_TICKETS` | `20000` | Max ticket capacity |
| `SERVER_PORT` | `8001` | Default REST server port |
| `NODE_ID` | *(auto)* | Identifies this server/worker in the per-node server-side metrics |

## Server-Side Metrics

Performance is measured **on the server tier**, not at the client. Every buy is
a single atomic Lua script that also records metrics into Redis (the shared
backend), so they aggregate automatically across all REST servers / workers no
matter how the system was scaled.

- **Direct**: `GET /metrics` returns the global aggregate (any instance behind
  NGINX answers it, since the data lives in Redis).
- **Indirect**: the workers record the metrics; the client reads them from Redis
  (best-effort) and also derives the per-worker split from the result messages.

Each result file now carries a `server_metrics` block:

| Field | Meaning |
|-------|---------|
| `server_throughput_ops` | Deliveries/sec over the real processing window (first→last request, on Redis' own clock) |
| `server_window_s` | Duration the server tier was actively processing |
| `server_avg/min/max_latency_ms` | Server-side **service time** per request (excludes client transport & queue wait) |
| `workers` / `by_node` | How load was distributed across nodes (the "workers graph") |
| `replays` | Redelivered messages that were deduplicated instead of re-sold |

> The client-side numbers (`throughput_ops`, `avg_latency_ms`) are kept for
> reference. For the indirect path they include **queue-waiting time**, which is
> why client-side latency looks huge — the server-side metric is the real one.

## Fault Tolerance

- **Exactly-once per `request_id`.** Each buy is idempotent: the Lua script
  records the outcome per request id, so a message **redelivered after a worker
  crash** replays the original result instead of selling a second ticket. This
  keeps the `≤ TOTAL_TICKETS` invariant even when nodes fail mid-run. (`INCR`
  alone is not idempotent — this is the fix.)
- **RabbitMQ** requeues a dead worker's unacked messages to the survivors.
- **NGINX** (direct) uses `max_fails` + `proxy_next_upstream` so a crashed REST
  server is taken out of rotation and in-flight requests retry on a healthy one.

Reproduce it:
```bash
export PYTHONPATH=$(pwd)
python scripts/fault_tolerance_test.py \
    --benchmark benchmarks/benchmark_unnumbered.txt \
    --workers 3 --kill-after 1.5 --restart
```
It starts workers, runs the benchmark, **kills a worker mid-run** (optionally
starting a replacement), then asserts no overselling and that load moved to the
survivors.

## Dynamic Scaling

- **REST**: Add/remove `uvicorn` instances, update NGINX upstream, reload (`nginx -s reload`)
- **RabbitMQ**: Start/stop `worker.py` processes at any time – RabbitMQ's fair dispatch handles rebalancing

Sweep throughput vs. worker count (produces the scalability / workers graph):
```bash
export PYTHONPATH=$(pwd)
python scripts/scaling_sweep.py \
    --benchmark benchmarks/benchmark_unnumbered.txt --workers 1 2 4 8 --output-dir results
python analysis/plot_results.py --scalability results/results_indirect_*w.json --output-dir analysis/plots
```

## Testing

The backend's correctness guarantees (no overselling, idempotent redelivery,
metric aggregation) can be verified locally **without** Redis/RabbitMQ:
```bash
pip install -r requirements-dev.txt
python tests/test_backend_fakeredis.py
```

## Ticket Models

| Model | Consistency Mechanism | Primary Evaluation |
|-------|----------------------|-------------------|
| **Unnumbered** | Redis `INCR` via Lua (atomic counter ≤ 20,000) | Throughput & scalability |
| **Numbered** | Redis `SADD` via Lua (atomic set membership) | Consistency under contention |
