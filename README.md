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

```bash
# On each VM:
sudo ./scripts/deploy.sh

# Adjust direct/nginx.conf upstream IPs for multi-VM setup
# Then run:
./scripts/run_benchmark.sh
```

See `scripts/deploy.sh` for full setup and `scripts/run_benchmark.sh` for automated sweep.

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
│   ├── deploy.sh            # AWS VM setup script
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

## Dynamic Scaling

- **REST**: Add/remove `uvicorn` instances, update NGINX upstream, reload (`nginx -s reload`)
- **RabbitMQ**: Start/stop `worker.py` processes at any time – RabbitMQ's fair dispatch handles rebalancing

## Ticket Models

| Model | Consistency Mechanism | Primary Evaluation |
|-------|----------------------|-------------------|
| **Unnumbered** | Redis `INCR` via Lua (atomic counter ≤ 20,000) | Throughput & scalability |
| **Numbered** | Redis `SADD` via Lua (atomic set membership) | Consistency under contention |
