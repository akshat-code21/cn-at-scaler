#!/usr/bin/env python3
"""04_esi_bytes.py - what Edge Side Includes actually save, and for whom.

100 different logged-in users load the same news page.
  A: the origin assembles the page (it is personal, so nobody can cache it)
  B: the origin sends a cacheable shell with two <esi:include> holes and the
     edge fills them from two tiny private fragments
We check the two pages are byte-for-byte identical per user, then count.
"""
import asyncio

from harness import Procs, Client, astats, one_shot, table

USERS = 100


async def fetch_all(port, path):
    bodies = []
    for i in range(USERS):
        c = Client(port, cookie=f"user=reader{i:03d}")
        resp, _ = await c.get(path)
        assert resp.status == 200
        bodies.append(resp.body)
        c.close()
    return bodies


async def measure(port, path):
    await one_shot(9150, "/__origin/reset")
    await one_shot(port, "/__edge/reset")
    bodies = await fetch_all(port, path)
    o = await astats(9150, "origin")
    e = await astats(port)
    return bodies, o, e


async def run():
    a_bodies, ao, ae = await measure(8150, "/page/home-full")
    b_bodies, bo, be = await measure(8151, "/page/home")
    assert a_bodies == b_bodies, "assembled pages differ!"
    print(f"\n{USERS} users; pages identical per user: yes ({len(a_bodies[0]):,} B each)\n")
    rows = [
        ("A  origin assembles", ao["requests"], f"{ao['bytes_out']:,}", f"{ae['client_bytes_out']:,}",
         " ".join(f"{k}={v}" for k, v in ae["cache"].items())),
        ("B  ESI at the edge", bo["requests"], f"{bo['bytes_out']:,}", f"{be['client_bytes_out']:,}",
         " ".join(f"{k}={v}" for k, v in be["cache"].items())),
    ]
    table(rows, ("", "origin requests", "origin -> edge bytes", "edge -> users bytes", "edge cache"))
    print(f"\norigin bytes cut by {1 - bo['bytes_out'] / ao['bytes_out']:.1%}; "
          f"bytes to users changed by {be['client_bytes_out'] / ae['client_bytes_out'] - 1:+.1%}.")
    print("ESI shrinks the origin's job, not the user's download. Requests went UP.")


def main():
    with Procs() as p:
        p.origin(9150)
        p.edge(8150, "--origin", "127.0.0.1:9150")
        p.edge(8151, "--origin", "127.0.0.1:9150", "--esi", "--cache-prefix", "/page/")
        asyncio.run(run())


if __name__ == "__main__":
    main()
