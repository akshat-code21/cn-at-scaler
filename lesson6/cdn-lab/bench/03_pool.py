#!/usr/bin/env python3
"""03_pool.py - connection reuse between the edge and the origin.

300 visitors arrive one every 40 ms (25 req/s). Each opens its own
connection to the edge and asks for one dynamic page. The edge is 50 ms from
the origin over TLS 1.3, and the origin closes idle keep-alive connections
after 1 s - as real origins do.

The only thing that changes is how the edge keeps its origin connections:
  no pool             every request opens TCP + TLS to the origin
  N worker pools      nginx: each worker process owns its pool, and the kernel
                      decides which worker gets each visitor
  1 shared pool       Pingora: one pool for every thread

Reuse ratio = 1 - new origin connections / origin requests: the metric in
Cloudflare's Pingora post (87.1% -> 99.92% for one customer).
"""
import asyncio
import statistics
import time

from harness import Procs, Client, astats, table, one_shot

VISITORS, GAP, ORIGIN_RTT, ORIGIN_IDLE = 300, 0.040, 50, 1.0
PAGE = "/page/home-full"


async def visitor(port, i, ttfbs):
    c = Client(port, cookie=f"user=v{i}")
    resp, ms = await c.get(PAGE)
    assert resp.status == 200, resp.status
    ttfbs.append(ms)
    c.close()


async def load(port):
    await one_shot(9140, "/__origin/reset", tls=True)
    await one_shot(port, "/__edge/reset")
    ttfbs, tasks = [], []
    for i in range(VISITORS):
        tasks.append(asyncio.ensure_future(visitor(port, i, ttfbs)))
        await asyncio.sleep(GAP)
    await asyncio.gather(*tasks)
    return ttfbs, await astats(port)


async def run(configs):
    rows = []
    for label, port in configs:
        ttfbs, s = await load(port)
        req, new = s["origin_requests"], s["origin_new_connections"]
        rows.append((label, req, new, f"{1 - new / req:6.1%}",
                     f"{statistics.mean(ttfbs):5.0f}", f"{statistics.quantiles(ttfbs, n=10)[-1]:5.0f}"))
        await asyncio.sleep(ORIGIN_IDLE + 0.5)          # let every pool go cold between runs
    print(f"\n{VISITORS} visitors, one every {GAP * 1000:.0f} ms; edge<->origin RTT {ORIGIN_RTT} ms, "
          f"TLS 1.3; origin idle timeout {ORIGIN_IDLE:g} s\n")
    table(rows, ("edge configuration", "origin reqs", "new conns", "reuse", "mean ms", "p90 ms"))
    print("\nSame traffic, same idle budget per process. More workers means each pool\n"
          "sees fewer requests, so its connections time out before anyone reuses them.")


def main():
    with Procs() as p:
        p.origin(9140, "--tls", "--idle", ORIGIN_IDLE)
        p.laggy(9141, 9140, ORIGIN_RTT)
        common = ("--origin", "127.0.0.1:9141", "--origin-tls", "--no-cache")
        p.edge(8140, *common, "--pool", 0)
        p.edge(8141, *common, "--pool", 8, "--pools", 32)
        p.edge(8142, *common, "--pool", 8, "--pools", 8)
        p.edge(8143, *common, "--pool", 8, "--pools", 1)
        asyncio.run(run([("no pool", 8140), ("32 worker pools", 8141),
                         ("8 worker pools", 8142), ("1 shared pool", 8143)]))


if __name__ == "__main__":
    main()
