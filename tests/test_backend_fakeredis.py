#!/usr/bin/env python3
"""
Local verification of the ticket backend's correctness guarantees, using an
in-process fake Redis (no real Redis/RabbitMQ needed).

Proves the two properties the assignment cares about:
  * the ticket invariant is never violated (no overselling), and
  * processing is **exactly-once per request_id**, so a redelivered message
    (what happens when a worker crashes and RabbitMQ requeues) does NOT sell a
    second ticket — it replays the original outcome.

Also checks that the server-side metrics aggregate correctly across nodes.

Run:
    python tests/test_backend_fakeredis.py        # standalone
    pytest tests/test_backend_fakeredis.py         # or under pytest
"""

import os
import sys

# Small capacity so overselling is easy to exercise. Must be set before import.
os.environ["TOTAL_TICKETS"] = "5"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fakeredis                                              # noqa: E402
from shared.redis_backend import (                           # noqa: E402
    TicketStore, read_metrics, KEY_UNNUMBERED, KEY_NUMBERED,
)

CAP = 5


def _fresh():
    """A shared fake-Redis server plus two stores acting as two nodes."""
    server = fakeredis.FakeServer()
    conn = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    w1 = TicketStore(connection=conn, node_id="w1", arch="indirect")
    w2 = TicketStore(connection=conn, node_id="w2", arch="indirect")
    w1.reset()
    return conn, w1, w2


def test_unnumbered_no_overselling():
    conn, w1, w2 = _fresh()
    # 12 unique requests for 5 tickets, split across two workers.
    for i in range(12):
        w = w1 if i % 2 == 0 else w2
        w.buy_unnumbered(client_id=f"c{i}", request_id=f"req-{i}")

    sold = int(conn.get(KEY_UNNUMBERED))
    m = read_metrics("indirect", conn)
    assert sold == CAP, f"oversold: {sold} > {CAP}"
    assert m["ok"] == CAP, m
    assert m["rejected"] == 12 - CAP, m
    assert m["unique_requests"] == 12, m
    assert sum(m["by_node"].values()) == 12, m            # every delivery counted
    assert set(m["by_node"]) == {"w1", "w2"}, m
    print("  [PASS] unnumbered: no overselling, counts/metrics correct")


def test_idempotent_redelivery():
    """Re-processing the same request_id (worker crash → requeue) must not
    sell a second ticket; it replays the same outcome."""
    conn, w1, w2 = _fresh()
    first = w1.buy_unnumbered(client_id="c1", request_id="req-X")
    assert first["status"] == "OK"
    sold_after_first = int(conn.get(KEY_UNNUMBERED))

    # Same request redelivered to a DIFFERENT worker 5 times.
    for _ in range(5):
        again = w2.buy_unnumbered(client_id="c1", request_id="req-X")
        assert again["status"] == "OK", "replay changed the outcome"

    sold_after_replays = int(conn.get(KEY_UNNUMBERED))
    m = read_metrics("indirect", conn)
    assert sold_after_first == 1
    assert sold_after_replays == 1, f"redelivery double-counted: {sold_after_replays}"
    assert m["ok"] == 1, m
    assert m["replays"] == 5, m
    assert m["processed"] == 6, m                          # 1 real + 5 replays
    print("  [PASS] redelivery is idempotent: no double-count (5 replays absorbed)")


def test_numbered_consistency_and_replay():
    conn, w1, w2 = _fresh()
    r1 = w1.buy_numbered(client_id="c1", seat_id="42", request_id="r1")
    r2 = w2.buy_numbered(client_id="c2", seat_id="42", request_id="r2")  # contended
    assert r1["status"] == "OK"
    assert r2["status"] == "REJECTED", "same seat sold twice!"

    # Redelivery of r1 must still say OK (not flip to REJECTED).
    r1_again = w2.buy_numbered(client_id="c1", seat_id="42", request_id="r1")
    assert r1_again["status"] == "OK", "replay flipped a winning seat to REJECTED"

    assert conn.scard(KEY_NUMBERED) == 1
    m = read_metrics("indirect", conn)
    assert m["ok"] == 1 and m["rejected"] == 1, m
    assert m["replays"] == 1, m
    print("  [PASS] numbered: seat sold once, contender rejected, replay consistent")


def test_metrics_window_and_workers():
    conn, w1, w2 = _fresh()
    for i in range(6):
        (w1 if i < 4 else w2).buy_unnumbered(client_id=f"c{i}", request_id=f"q{i}")
    m = read_metrics("indirect", conn)
    assert m["workers"] == 2, m
    assert m["by_node"] == {"w1": 4, "w2": 2}, m
    assert m["server_window_s"] >= 0, m
    assert m["server_throughput_ops"] >= 0, m
    print("  [PASS] metrics: per-node breakdown + processing window present")


def main():
    tests = [
        test_unnumbered_no_overselling,
        test_idempotent_redelivery,
        test_numbered_consistency_and_replay,
        test_metrics_window_and_workers,
    ]
    print("Running backend correctness tests (fakeredis)...")
    for t in tests:
        t()
    print(f"\n[OK] All {len(tests)} tests passed.")


if __name__ == "__main__":
    main()
