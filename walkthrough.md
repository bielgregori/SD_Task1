# Walkthrough – Concert Ticket Acquisition System

## What Was Built

A complete scalable distributed ticket system for **20,000 concert tickets** with two communication architectures and a Redis consistency backend.

### Project Structure (17 files)

```
Prova1/
├── shared/config.py              # Env-based configuration
├── shared/redis_backend.py       # Redis Lua-scripted ticket store
├── direct/server.py              # FastAPI REST endpoints
├── direct/client.py              # Async HTTP benchmark runner (aiohttp)
├── direct/nginx.conf             # NGINX round-robin load balancer
├── indirect/worker.py            # RabbitMQ consumer with graceful shutdown
├── indirect/client.py            # RabbitMQ producer + result collector
├── indirect/results.py           # Queue drain utility
├── benchmarks/generate.py        # Workload generator (normal + high-contention)
├── analysis/plot_results.py      # Matplotlib plots (throughput, latency, scalability)
├── scripts/deploy.sh             # AWS VM one-command setup
├── scripts/run_benchmark.sh      # Full benchmark sweep automation
├── requirements.txt              # Python deps
└── README.md                     # Usage & deployment docs
```

## Architecture Highlights

| Component | Direct (REST) | Indirect (RabbitMQ) |
|---|---|---|
| Entry point | NGINX → FastAPI instances | RabbitMQ queue |
| Load balancing | NGINX round-robin | RabbitMQ fair dispatch |
| Scaling | Add uvicorn processes + reload NGINX | Start more [worker.py](file:///c:/Users/usuari/OneDrive%20-%20URV/Documentos/UNI/3r%20curs/Sistemes%20distribuits/Task1/Prova1/indirect/worker.py) processes |
| Consistency | Redis Lua scripts (atomic) | Same Redis Lua scripts |

## Consistency Backend

Both architectures share [redis_backend.py](file:///c:/Users/usuari/OneDrive%20-%20URV/Documentos/UNI/3r%20curs/Sistemes%20distribuits/Task1/Prova1/shared/redis_backend.py):

- **Unnumbered**: Lua script does `INCR` only if counter < 20,000 → guarantees exactly 20K sales
- **Numbered**: Lua script does `SADD` → returns 0 if seat already sold → guarantees no double-sell

Both are **atomic** (single Redis `EVAL` round-trip).

## How to Run

1. Install: `pip install -r requirements.txt`
2. Start Redis + RabbitMQ
3. Generate benchmarks: `python benchmarks/generate.py`
4. **Direct**: Start FastAPI servers → run [direct/client.py](file:///c:/Users/usuari/OneDrive%20-%20URV/Documentos/UNI/3r%20curs/Sistemes%20distribuits/Task1/Prova1/direct/client.py)
5. **Indirect**: Start workers → run [indirect/client.py](file:///c:/Users/usuari/OneDrive%20-%20URV/Documentos/UNI/3r%20curs/Sistemes%20distribuits/Task1/Prova1/indirect/client.py)
6. Plot: `python analysis/plot_results.py --results *.json`

Full automated sweep: [./scripts/run_benchmark.sh](file:///c:/Users/usuari/OneDrive%20-%20URV/Documentos/UNI/3r%20curs/Sistemes%20distribuits/Task1/Prova1/scripts/run_benchmark.sh)

## Validation

All correctness is enforced at the Redis layer via Lua scripts—regardless of how many workers/servers are running or which architecture is used. The benchmark clients verify:

- Success count ≤ 20,000 (unnumbered) 
- No duplicate seat IDs (numbered)
- Full JSON reports with per-request latency
