"""
Redis-backed ticket store with Lua scripts for atomic operations.

Two ticket models:
  1. Unnumbered – atomic counter (INCR if < MAX)
  2. Numbered   – atomic SADD with existence check

All operations are single-round-trip thanks to Redis EVAL (Lua).
"""

import redis
from shared.config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, TOTAL_TICKETS


def _get_connection() -> redis.Redis:
    """Return a Redis connection (caller should cache if needed)."""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )


# ─── Keys ────────────────────────────────────────────────────────────
KEY_UNNUMBERED = "tickets:unnumbered:sold"  # string counter
KEY_NUMBERED   = "tickets:numbered:seats"   # set of sold seat ids


# ─── Lua scripts ─────────────────────────────────────────────────────

# Unnumbered: increment counter if below limit
_LUA_BUY_UNNUMBERED = """
local key   = KEYS[1]
local limit = tonumber(ARGV[1])
local current = tonumber(redis.call('GET', key) or '0')
if current < limit then
    redis.call('INCR', key)
    return 1
else
    return 0
end
"""

# Numbered: add seat if not already sold
_LUA_BUY_NUMBERED = """
local key     = KEYS[1]
local seat_id = ARGV[1]
local added   = redis.call('SADD', key, seat_id)
return added
"""


class TicketStore:
    """Thread-safe ticket store backed by Redis Lua scripts."""

    def __init__(self, connection: redis.Redis | None = None):
        self.r = connection or _get_connection()
        # Register Lua scripts once
        self._buy_unnumbered_sha = self.r.script_load(_LUA_BUY_UNNUMBERED)
        self._buy_numbered_sha   = self.r.script_load(_LUA_BUY_NUMBERED)

    # ── public API ───────────────────────────────────────────────────

    def buy_unnumbered(self, client_id: str, request_id: str) -> dict:
        """
        Attempt to buy an unnumbered ticket.
        Returns {"status": "OK"} or {"status": "REJECTED"}.
        """
        result = self.r.evalsha(
            self._buy_unnumbered_sha,
            1,              # numkeys
            KEY_UNNUMBERED,  # KEYS[1]
            TOTAL_TICKETS,   # ARGV[1]
        )
        status = "OK" if int(result) == 1 else "REJECTED"
        return {
            "status": status,
            "client_id": client_id,
            "request_id": request_id,
        }

    def buy_numbered(self, client_id: str, seat_id: str, request_id: str) -> dict:
        """
        Attempt to buy a specific numbered seat.
        Returns {"status": "OK"} or {"status": "REJECTED"}.
        """
        result = self.r.evalsha(
            self._buy_numbered_sha,
            1,             # numkeys
            KEY_NUMBERED,  # KEYS[1]
            seat_id,       # ARGV[1]
        )
        status = "OK" if int(result) == 1 else "REJECTED"
        return {
            "status": status,
            "client_id": client_id,
            "seat_id": seat_id,
            "request_id": request_id,
        }

    # ── helpers ──────────────────────────────────────────────────────

    def reset(self):
        """Clear all ticket data (for fresh benchmark runs)."""
        self.r.delete(KEY_UNNUMBERED, KEY_NUMBERED)

    def stats(self) -> dict:
        """Return current ticket statistics."""
        sold_unnumbered = int(self.r.get(KEY_UNNUMBERED) or 0)
        sold_numbered   = self.r.scard(KEY_NUMBERED)
        return {
            "unnumbered_sold": sold_unnumbered,
            "numbered_sold": sold_numbered,
            "total_tickets": TOTAL_TICKETS,
        }
