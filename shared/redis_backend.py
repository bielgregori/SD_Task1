"""
Redis-backed ticket store with Lua scripts for atomic operations.

Two ticket models:
  1. Unnumbered – atomic counter (INCR if < MAX)
  2. Numbered   – atomic SADD with existence check

Every buy is a single round-trip Lua script that, in one atomic step:
  * enforces the ticket invariant (≤ TOTAL_TICKETS),
  * guarantees **exactly-once effect per request_id** (idempotency / dedup),
    so a redelivered message – e.g. after a worker crash – never sells a
    second ticket, and
  * records **server-side metrics** (counts, per-node breakdown, service
    latency and a Redis-clock processing window) used for evaluation.

Because the metrics live in Redis – the single backend shared by every REST
server and every RabbitMQ worker – they aggregate naturally across all nodes
regardless of how the system was scaled.
"""

import redis

from shared.config import (
    REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, TOTAL_TICKETS,
)


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
KEY_UNNUMBERED       = "tickets:unnumbered:sold"        # string counter
KEY_NUMBERED         = "tickets:numbered:seats"         # set of sold seat ids
KEY_DEDUP_UNNUMBERED = "tickets:unnumbered:processed"   # request_id → outcome
KEY_DEDUP_NUMBERED   = "tickets:numbered:processed"     # request_id → outcome

ARCHITECTURES = ("direct", "indirect")


def metrics_keys(arch: str) -> tuple[str, str]:
    """Return (global-hash, per-node-hash) metric keys for an architecture."""
    return f"metrics:{arch}", f"metrics:{arch}:nodes"


# ─── Lua scripts ─────────────────────────────────────────────────────
#
# Shared metric-recording tail.  `prev` (whether the request was already
# processed) and `sold` (1 = ticket granted) must be defined before it runs,
# together with the timestamps t0/t1 captured around the buy.
_LUA_METRICS_TAIL = """
local t1 = redis.call('TIME')
local lat_us = (tonumber(t1[1]) - tonumber(t0[1])) * 1000000
             + (tonumber(t1[2]) - tonumber(t0[2]))
if lat_us < 0 then lat_us = 0 end

local mk = KEYS[3]
redis.call('HINCRBY', mk, 'count', 1)
if is_replay == 1 then
    redis.call('HINCRBY', mk, 'replays', 1)
elseif sold == 1 then
    redis.call('HINCRBY', mk, 'ok', 1)
else
    redis.call('HINCRBY', mk, 'rejected', 1)
end
redis.call('HINCRBYFLOAT', mk, 'lat_sum_us', lat_us)
local cmax = tonumber(redis.call('HGET', mk, 'lat_max_us') or '-1')
if lat_us > cmax then redis.call('HSET', mk, 'lat_max_us', lat_us) end
local cmin = redis.call('HGET', mk, 'lat_min_us')
if (not cmin) or lat_us < tonumber(cmin) then
    redis.call('HSET', mk, 'lat_min_us', lat_us)
end
local now_us = tonumber(t1[1]) * 1000000 + tonumber(t1[2])
if not redis.call('HGET', mk, 'first_ts_us') then
    redis.call('HSET', mk, 'first_ts_us', now_us)
end
redis.call('HSET', mk, 'last_ts_us', now_us)
redis.call('HINCRBY', KEYS[4], ARGV[2], 1)
return sold
"""

# Unnumbered: increment a counter while below the limit.
#   KEYS = counter, dedup-hash, metrics-hash, node-hash
#   ARGV = request_id, node_id, limit
_LUA_BUY_UNNUMBERED = """
if redis.replicate_commands then redis.replicate_commands() end
local t0 = redis.call('TIME')
local req = ARGV[1]
local prev = redis.call('HGET', KEYS[2], req)
local sold
local is_replay = 0
if prev then
    sold = tonumber(prev)
    is_replay = 1
else
    local limit = tonumber(ARGV[3])
    local current = tonumber(redis.call('GET', KEYS[1]) or '0')
    if current < limit then
        redis.call('INCR', KEYS[1])
        sold = 1
    else
        sold = 0
    end
    redis.call('HSET', KEYS[2], req, sold)
end
""" + _LUA_METRICS_TAIL

# Numbered: add a seat to the sold set if free.
#   KEYS = seat-set, dedup-hash, metrics-hash, node-hash
#   ARGV = request_id, node_id, seat_id
_LUA_BUY_NUMBERED = """
if redis.replicate_commands then redis.replicate_commands() end
local t0 = redis.call('TIME')
local req = ARGV[1]
local prev = redis.call('HGET', KEYS[2], req)
local sold
local is_replay = 0
if prev then
    sold = tonumber(prev)
    is_replay = 1
else
    sold = redis.call('SADD', KEYS[1], ARGV[3])
    redis.call('HSET', KEYS[2], req, sold)
end
""" + _LUA_METRICS_TAIL


class TicketStore:
    """Ticket store backed by atomic Redis Lua scripts.

    `node_id` identifies the REST server / worker process so the server-side
    metrics can break load down per node.  `arch` selects the metric namespace
    ("direct" or "indirect").
    """

    def __init__(
        self,
        connection: redis.Redis | None = None,
        node_id: str = "node-0",
        arch: str = "direct",
    ):
        self.r = connection or _get_connection()
        self.node_id = node_id
        self.arch = arch
        self._mkey, self._nkey = metrics_keys(arch)
        # Register Lua scripts once
        self._buy_unnumbered_sha = self.r.script_load(_LUA_BUY_UNNUMBERED)
        self._buy_numbered_sha   = self.r.script_load(_LUA_BUY_NUMBERED)

    # ── public API ───────────────────────────────────────────────────

    def buy_unnumbered(self, client_id: str, request_id: str) -> dict:
        """
        Attempt to buy an unnumbered ticket (idempotent per request_id).
        Returns {"status": "OK"} or {"status": "REJECTED"}.
        """
        result = self.r.evalsha(
            self._buy_unnumbered_sha,
            4,                       # numkeys
            KEY_UNNUMBERED,          # KEYS[1] counter
            KEY_DEDUP_UNNUMBERED,    # KEYS[2] dedup hash
            self._mkey,              # KEYS[3] metrics hash
            self._nkey,              # KEYS[4] per-node hash
            request_id,              # ARGV[1]
            self.node_id,            # ARGV[2]
            TOTAL_TICKETS,           # ARGV[3]
        )
        status = "OK" if int(result) == 1 else "REJECTED"
        return {
            "status": status,
            "client_id": client_id,
            "request_id": request_id,
            "worker_id": self.node_id,
        }

    def buy_numbered(self, client_id: str, seat_id: str, request_id: str) -> dict:
        """
        Attempt to buy a specific numbered seat (idempotent per request_id).
        Returns {"status": "OK"} or {"status": "REJECTED"}.
        """
        result = self.r.evalsha(
            self._buy_numbered_sha,
            4,                     # numkeys
            KEY_NUMBERED,          # KEYS[1] seat set
            KEY_DEDUP_NUMBERED,    # KEYS[2] dedup hash
            self._mkey,            # KEYS[3] metrics hash
            self._nkey,            # KEYS[4] per-node hash
            request_id,            # ARGV[1]
            self.node_id,          # ARGV[2]
            seat_id,               # ARGV[3]
        )
        status = "OK" if int(result) == 1 else "REJECTED"
        return {
            "status": status,
            "client_id": client_id,
            "seat_id": seat_id,
            "request_id": request_id,
            "worker_id": self.node_id,
        }

    # ── helpers ──────────────────────────────────────────────────────

    def reset(self):
        """Clear all ticket data, dedup state and metrics (fresh run)."""
        reset_all(self.r)

    def stats(self) -> dict:
        """Return current ticket statistics."""
        sold_unnumbered = int(self.r.get(KEY_UNNUMBERED) or 0)
        sold_numbered   = self.r.scard(KEY_NUMBERED)
        return {
            "unnumbered_sold": sold_unnumbered,
            "numbered_sold": sold_numbered,
            "total_tickets": TOTAL_TICKETS,
        }

    def get_metrics(self, arch: str | None = None) -> dict:
        """Server-side metrics for `arch` (defaults to this store's arch)."""
        return read_metrics(arch or self.arch, self.r)


# ─── Module-level metric helpers (usable without a TicketStore) ──────

def read_metrics(arch: str, connection: redis.Redis | None = None) -> dict:
    """
    Read and derive the server-side metrics for an architecture.

    These are recorded by the servers/workers themselves (not the client),
    so they reflect what actually happened on the server tier:

      * server_throughput_ops – deliveries processed per second over the
        real processing window (first→last request, on Redis' own clock),
      * server_avg/min/max_latency_ms – Redis-side service time per request,
      * workers / by_node – how the load was distributed across nodes,
      * replays – extra deliveries caused by redelivery (fault tolerance).
    """
    r = connection or _get_connection()
    mkey, nkey = metrics_keys(arch)
    h = r.hgetall(mkey)
    nodes = r.hgetall(nkey)

    count   = int(h.get("count", 0))
    ok      = int(h.get("ok", 0))
    rejected = int(h.get("rejected", 0))
    replays = int(h.get("replays", 0))
    lat_sum_us = float(h.get("lat_sum_us", 0.0))
    lat_max_us = float(h.get("lat_max_us", 0.0))
    lat_min_us = float(h.get("lat_min_us", 0.0))
    first_us = int(float(h.get("first_ts_us", 0)))
    last_us  = int(float(h.get("last_ts_us", 0)))

    window_s = (last_us - first_us) / 1_000_000 if count else 0.0
    throughput = count / window_s if window_s > 0 else 0.0

    return {
        "source": "server",
        "architecture": arch,
        "processed": count,                 # total deliveries (incl. replays)
        "unique_requests": ok + rejected,   # distinct request_ids handled
        "ok": ok,
        "rejected": rejected,
        "replays": replays,                 # redeliveries deduped away
        "server_window_s": round(window_s, 3),
        "server_throughput_ops": round(throughput, 1),
        "server_avg_latency_ms": round((lat_sum_us / count) / 1000, 4) if count else 0.0,
        "server_max_latency_ms": round(lat_max_us / 1000, 4),
        "server_min_latency_ms": round(lat_min_us / 1000, 4),
        "workers": len(nodes),
        "by_node": {k: int(v) for k, v in nodes.items()},
    }


def reset_metrics(connection: redis.Redis | None = None):
    """Clear only the metric keys (keeps ticket/dedup state)."""
    r = connection or _get_connection()
    keys = []
    for arch in ARCHITECTURES:
        keys.extend(metrics_keys(arch))
    r.delete(*keys)


def reset_all(connection: redis.Redis | None = None):
    """Clear ticket data, dedup state and metrics for a fresh benchmark run."""
    r = connection or _get_connection()
    keys = [
        KEY_UNNUMBERED, KEY_NUMBERED,
        KEY_DEDUP_UNNUMBERED, KEY_DEDUP_NUMBERED,
    ]
    for arch in ARCHITECTURES:
        keys.extend(metrics_keys(arch))
    r.delete(*keys)
