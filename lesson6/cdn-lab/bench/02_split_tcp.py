#!/usr/bin/env python3
"""02_split_tcp.py - what the edge can save you, and what it cannot.

    you --10 ms-- edge (Mumbai) --194 ms-- origin (Washington)      = 204 ms
    you ------------------ 204 ms ------------------ origin         (measured, Sep 2026)

Every link is TLS 1.3 over TCP. We time the first response byte for one
dynamic page (private, never cached) and one static asset (cached).
"""
import asyncio
import statistics
import sys

from harness import Procs, Client, table

EDGE_RTT, ORIGIN_RTT = 10, 194
DIRECT = EDGE_RTT + ORIGIN_RTT
REPEAT = 5
DYN, STATIC = "/page/home-full", "/static/app.css"


async def fresh(port, target, n=REPEAT):
    """New client connection each time: TCP + TLS + request."""
    out = []
    for _ in range(n):
        c = Client(port, tls=True, cookie="user=jeet")
        _, ms = await c.get(target)
        c.close()
        out.append(ms)
    return statistics.median(out)


async def warm(port, target, n=REPEAT):
    """One client connection, already open: request only."""
    c = Client(port, tls=True, cookie="user=jeet")
    await c.get(target)
    out = []
    for _ in range(n):
        _, ms = await c.get(target)
        out.append(ms)
    c.close()
    return statistics.median(out)


async def run():
    rows = []

    def add(label, path, ms, note):
        rows.append((label, path, f"{ms:6.0f}", f"{ms / DIRECT:4.1f}", note))

    # direct: you -> origin
    add("direct, new connection", "dynamic", await fresh(9111, DYN), "3 RTT: TCP, TLS, request")
    add("direct, kept-alive", "dynamic", await warm(9111, DYN), "1 RTT")
    # edge without a pool: it is just a longer proxy
    add("edge, no origin pool", "dynamic", await fresh(8211, DYN), "3 short + 3 long RTTs")
    # edge with a warm pool (warm it first)
    await fresh(8111, DYN, 1)
    add("edge, warm origin pool", "dynamic", await fresh(8111, DYN), "3 short + 1 long")
    add("edge, warm pool, kept-alive", "dynamic", await warm(8111, DYN), "1 short + 1 long = direct")
    # cache
    await fresh(8111, STATIC, 1)
    add("edge, cache HIT", "static", await fresh(8111, STATIC), "3 short RTTs, no origin")
    add("edge, cache HIT, kept-alive", "static", await warm(8111, STATIC), "1 short RTT")
    print(f"\nRTT you<->edge {EDGE_RTT} ms, edge<->origin {ORIGIN_RTT} ms, you<->origin {DIRECT} ms;"
          f" median of {REPEAT}\n")
    table(rows, ("path", "content", "TTFB ms", "x direct RTT", "why"))
    print("\nThe pool saves the handshakes. Only the cache saves the round trip.")


def main():
    with Procs() as p:
        p.origin(9110, "--tls", "--css-ttl", 3600)
        p.laggy(9111, 9110, DIRECT)            # you -> origin
        p.laggy(9112, 9110, ORIGIN_RTT)        # edge -> origin
        p.edge(8110, "--tls", "--origin", "127.0.0.1:9112", "--origin-tls", "--pool", 64)
        p.edge(8210, "--tls", "--origin", "127.0.0.1:9112", "--origin-tls", "--pool", 0)
        p.laggy(8111, 8110, EDGE_RTT)          # you -> edge (pooled)
        p.laggy(8211, 8210, EDGE_RTT)          # you -> edge (no pool)
        asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
