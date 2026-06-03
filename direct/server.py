"""
FastAPI REST server for the Concert Ticket Acquisition System.

Endpoints:
    POST /buy/unnumbered   { "client_id": "...", "request_id": "..." }
    POST /buy/numbered     { "client_id": "...", "seat_id": "...", "request_id": "..." }
    POST /reset            (clear all ticket data, dedup state and metrics)
    GET  /stats            (current ticket statistics)
    GET  /metrics          (server-side metrics, aggregated across all servers)
    GET  /health           (health check)

Metrics are measured here on the server tier (not at the client) and stored in
Redis, so /metrics returns the global aggregate no matter which server instance
behind the load balancer answers the request.

Run:
    uvicorn direct.server:app --host 0.0.0.0 --port 8001
    NODE_ID=rest-8002 uvicorn direct.server:app --host 0.0.0.0 --port 8002
"""

import os

from fastapi import FastAPI
from pydantic import BaseModel

from shared.config import NODE_ID, SERVER_PORT
from shared.redis_backend import TicketStore

app = FastAPI(title="Concert Ticket System – Direct (REST)")

# Stable per-process node id for the per-node server-side metrics.
_NODE_ID = NODE_ID or f"rest-{SERVER_PORT}-{os.getpid()}"

# Lazy-init store on first request (allows import without Redis being up)
_store: TicketStore | None = None


def _get_store() -> TicketStore:
    global _store
    if _store is None:
        _store = TicketStore(node_id=_NODE_ID, arch="direct")
    return _store


# ─── Request models ─────────────────────────────────────────────────

class UnnumberedRequest(BaseModel):
    client_id: str
    request_id: str


class NumberedRequest(BaseModel):
    client_id: str
    seat_id: str
    request_id: str


# ─── Endpoints ──────────────────────────────────────────────────────

@app.post("/buy/unnumbered")
def buy_unnumbered(req: UnnumberedRequest):
    return _get_store().buy_unnumbered(req.client_id, req.request_id)


@app.post("/buy/numbered")
def buy_numbered(req: NumberedRequest):
    return _get_store().buy_numbered(req.client_id, req.seat_id, req.request_id)


@app.post("/reset")
def reset():
    _get_store().reset()
    return {"status": "OK", "message": "Ticket data, dedup and metrics cleared"}


@app.get("/stats")
def stats():
    return _get_store().stats()


@app.get("/metrics")
def metrics():
    """Server-side metrics aggregated across every REST server via Redis."""
    return _get_store().get_metrics("direct")


@app.get("/health")
def health():
    return {"status": "healthy", "node_id": _NODE_ID}
