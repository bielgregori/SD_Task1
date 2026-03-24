"""
FastAPI REST server for the Concert Ticket Acquisition System.

Endpoints:
    POST /buy/unnumbered   { "client_id": "...", "request_id": "..." }
    POST /buy/numbered     { "client_id": "...", "seat_id": "...", "request_id": "..." }
    POST /reset            (clear all ticket data)
    GET  /stats            (current ticket statistics)
    GET  /health           (health check)

Run:
    uvicorn direct.server:app --host 0.0.0.0 --port 8001
"""

from fastapi import FastAPI
from pydantic import BaseModel

from shared.redis_backend import TicketStore

app = FastAPI(title="Concert Ticket System – Direct (REST)")

# Lazy-init store on first request (allows import without Redis being up)
_store: TicketStore | None = None


def _get_store() -> TicketStore:
    global _store
    if _store is None:
        _store = TicketStore()
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
    return {"status": "OK", "message": "All ticket data cleared"}


@app.get("/stats")
def stats():
    return _get_store().stats()


@app.get("/health")
def health():
    return {"status": "healthy"}
