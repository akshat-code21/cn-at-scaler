#!/usr/bin/env python3
"""origin.py - the application server that sits behind the CDN.

Deliberately naive in the ways real origins are naive:
  * /api/*     trusts an X-User header (the edge is supposed to set it)
  * /search    builds SQL with string formatting (unless --safe)
  * /page/landing reflects X-Forwarded-Host into the page
  * every response leaks X-Powered-By

It counts everything it does, so the benchmarks can ask it afterwards:
    GET /__origin/stats     POST /__origin/reset     POST /__origin/bump
"""
import argparse
import asyncio
import hashlib
import json
import os
import random
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from httpmini import (Headers, Response, ProtocolError, read_request, nodelay,  # noqa: E402
                      server_tls_context, peer_ip)

STATS = {}


def reset_stats():
    STATS.clear()
    STATS.update(connections=0, requests=0, bytes_out=0, by_path={}, max_requests_on_one_conn=0,
                 tls_client_certs=0)


reset_stats()
VERSION = {"/static/app.css": 1}
WORDS = ("edge cache origin anycast latency packet socket header framing stream quic tcp "
         "handshake pool vary etag purge shield tiered colo peering transit fibre photon").split()


def lorem(seed, n_words):
    rnd = random.Random(seed)
    return " ".join(rnd.choice(WORDS) for _ in range(n_words))


def css_body():
    v = VERSION["/static/app.css"]
    rules = [f".c{i} {{ margin: {i % 7}px; color: #{(i * 2654435761 + v) & 0xFFFFFF:06x}; }}"
             for i in range(600)]
    return (f"/* app.css version {v} */\n" + "\n".join(rules) + "\n").encode()


def page_shell(personal_user=None, cart=None):
    """~40 KB of HTML that is identical for every visitor, with two holes."""
    articles = "\n".join(
        f"<article><h2>Story {i}</h2><p>{lorem(i, 60)}</p></article>" for i in range(90))
    if personal_user is None:
        greet = '<esi:include src="/fragment/user"/>'
        cart_html = '<esi:include src="/fragment/cart"/>'
    else:
        greet = fragment_user(personal_user).decode()
        cart_html = fragment_cart(personal_user, cart).decode()
    return (f"<!doctype html><html><head><title>Session 6 news</title>"
            f'<link rel="stylesheet" href="/static/app.css"></head><body>'
            f"<header>{greet} {cart_html}</header>\n<main>{articles}</main>"
            f"<footer>served by the origin</footer></body></html>\n").encode()


def fragment_user(user):
    return f'<span class="hello">Hello, {user}! You have {len(user) % 5} new messages.</span>'.encode()


def fragment_cart(user, cart=None):
    n = cart if cart is not None else (sum(map(ord, user)) % 9)
    return f'<a class="cart" href="/cart">Cart ({n})</a>'.encode()


def user_from_cookie(req):
    for part in (req.headers.get("Cookie") or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == "user" and v:
            return v
    return "guest"


def make_db():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE products (id INTEGER, title TEXT, hidden INTEGER)")
    rows = [(1, "fibre patch cable", 0), (2, "anycast sticker", 0), (3, "edge server", 0),
            (4, "INTERNAL: admin price list", 1), (5, "INTERNAL: unreleased router", 1)]
    db.executemany("INSERT INTO products VALUES (?,?,?)", rows)
    return db


ORDERS = {"alice": ["#1001 fibre patch cable"], "bob": ["#1002 anycast sticker"],
          "admin": ["#0001 EVERY ORDER IN THE SYSTEM", "#0002 payroll export"]}


class Origin:
    def __init__(self, args):
        self.args = args
        self.db = make_db()

    def base_headers(self):
        h = Headers()
        h.add("Server", "origin/0.1")
        h.add("X-Origin", self.args.name)
        h.add("X-Powered-By", "PHP/5.4.45")    # the header nobody meant to publish
        return h

    async def handle(self, req, writer):
        h = self.base_headers()
        path = req.path
        if self.args.edge_secret and not path.startswith("/__origin"):
            if req.headers.get("X-Edge-Auth") != self.args.edge_secret:
                return Response(403, headers=h, body=b"direct access to origin refused\n")

        if path == "/__origin/stats":
            h.set("Content-Type", "application/json")
            return Response(200, headers=h, body=json.dumps(STATS).encode())
        if path == "/__origin/reset":
            reset_stats()
            return Response(204, headers=h)
        if path == "/__origin/bump":
            VERSION["/static/app.css"] += 1
            return Response(200, headers=h, body=f"deployed build {VERSION['/static/app.css']}\n".encode())
        if path == "/health":
            return Response(200, headers=h, body=b"ok\n")

        if self.args.delay_ms:
            await asyncio.sleep(self.args.delay_ms / 1000)

        if path == "/static/app.css":
            body = css_body()
            etag = '"' + hashlib.sha256(body).hexdigest()[:16] + '"'
            h.set("Content-Type", "text/css")
            h.set("Cache-Control", f"public, max-age={self.args.css_ttl}")
            h.set("ETag", etag)
            if req.headers.get("If-None-Match") == etag:
                return Response(304, headers=h)
            return Response(200, headers=h, body=body)

        if path == "/static/site.js":                 # long-lived, versioned by deploys
            h.set("Content-Type", "application/javascript")
            h.set("Cache-Control", "public, max-age=3600")
            body = f"// site.js build {VERSION['/static/app.css']}\nconsole.log('hello');\n".encode()
            return Response(200, headers=h, body=body)

        if path == "/me/avatar.png":                  # cacheable extension, personal content
            h.set("Content-Type", "image/png")
            h.set("Cache-Control", "private, max-age=600")
            return Response(200, headers=h, body=b"\x89PNG fake avatar for " + user_from_cookie(req).encode())

        if path == "/page/home":                      # the ESI shell
            h.set("Content-Type", "text/html")
            h.set("Cache-Control", "public, max-age=0, s-maxage=300")
            h.set("Surrogate-Control", 'content="ESI/1.0"')
            return Response(200, headers=h, body=page_shell())

        if path == "/page/home-full":                 # the same page, assembled here
            h.set("Content-Type", "text/html")
            h.set("Cache-Control", "private, no-store")
            return Response(200, headers=h, body=page_shell(personal_user=user_from_cookie(req)))

        if path == "/fragment/user":
            h.set("Content-Type", "text/html")
            h.set("Cache-Control", "private, no-store")
            return Response(200, headers=h, body=fragment_user(user_from_cookie(req)))

        if path == "/fragment/cart":
            h.set("Content-Type", "text/html")
            h.set("Cache-Control", "private, no-store")
            return Response(200, headers=h, body=fragment_cart(user_from_cookie(req)))

        if path == "/page/landing":
            # Web cache poisoning (Kettle, 2018): a header that changes the page
            # but is not part of the cache key.
            host = req.headers.get("X-Forwarded-Host") or req.headers.get("Host") or "localhost"
            h.set("Content-Type", "text/html")
            h.set("Cache-Control", "public, s-maxage=60")
            body = (f'<!doctype html><title>landing</title>'
                    f'<script src="https://{host}/static/app.js"></script>'
                    f"<p>Welcome.</p>\n").encode()
            return Response(200, headers=h, body=body)

        if path == "/api/orders":
            user = req.headers.get("X-User")            # trusts whoever set it
            h.set("Content-Type", "application/json")
            h.set("Cache-Control", "private, no-store")
            if not user:
                return Response(401, headers=h, body=b'{"error":"who are you?"}\n')
            body = json.dumps({"user": user, "orders": ORDERS.get(user, [])}).encode() + b"\n"
            return Response(200, headers=h, body=body)

        if path == "/search":
            from urllib.parse import parse_qs
            q = parse_qs(req.query).get("q", [""])[0]
            h.set("Content-Type", "text/plain")
            h.set("Cache-Control", "no-store")
            try:
                if self.args.safe:
                    rows = self.db.execute(
                        "SELECT title FROM products WHERE title LIKE ? AND hidden=0",
                        (f"%{q}%",)).fetchall()
                else:
                    sql = f"SELECT title FROM products WHERE title LIKE '%{q}%' AND hidden=0"
                    rows = self.db.execute(sql).fetchall()
            except sqlite3.Error as e:
                return Response(500, headers=h, body=f"sql error: {e}\n".encode())
            body = "".join(f"{r[0]}\n" for r in rows) or "no results\n"
            return Response(200, headers=h, body=body.encode())

        if path == "/slow":
            await asyncio.sleep(0.1)
            h.set("Cache-Control", "no-store")
            return Response(200, headers=h, body=f"generated at {time.time():.3f}\n".encode())

        return Response(404, headers=h, body=b"not found\n")

    async def serve_conn(self, reader, writer):
        nodelay(writer)
        STATS["connections"] += 1
        if writer.get_extra_info("peercert"):
            STATS["tls_client_certs"] += 1
        served = 0
        try:
            while True:
                try:
                    req = await asyncio.wait_for(read_request(reader), timeout=self.args.idle)
                except asyncio.TimeoutError:
                    break
                if req is None:
                    break
                served += 1
                if not req.path.startswith("/__origin"):
                    STATS["requests"] += 1
                    STATS["by_path"][req.path] = STATS["by_path"].get(req.path, 0) + 1
                resp = await self.handle(req, writer)
                data = resp.encode(head_only=req.method == "HEAD")
                STATS["bytes_out"] += len(data) if not req.path.startswith("/__origin") else 0
                writer.write(data)
                await writer.drain()
                if self.args.verbose:
                    print(f"[{self.args.name}] {peer_ip(writer)} {req.method} {req.target} "
                          f"-> {resp.status} ({len(resp.body)} B)", flush=True)
                if (req.headers.get("Connection") or "").lower() == "close":
                    break
        except (ProtocolError, ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            STATS["max_requests_on_one_conn"] = max(STATS["max_requests_on_one_conn"], served)
            writer.close()


async def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--name", default="primary")
    p.add_argument("--tls", action="store_true", help="serve HTTPS with certs/origin.pem")
    p.add_argument("--client-ca", help="require a client cert signed by this CA (mTLS)")
    p.add_argument("--edge-secret", help="refuse requests without X-Edge-Auth: SECRET")
    p.add_argument("--safe", action="store_true", help="use parameterised SQL in /search")
    p.add_argument("--delay-ms", type=int, default=0, help="think time per request")
    p.add_argument("--css-ttl", type=int, default=5)
    p.add_argument("--idle", type=float, default=90.0, help="keep-alive idle timeout (s)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "certs")
    ctx = None
    if args.tls or args.client_ca:
        ctx = server_tls_context(os.path.join(here, "origin.pem"), os.path.join(here, "origin.key"),
                                 args.client_ca)
    origin = Origin(args)
    server = await asyncio.start_server(origin.serve_conn, "127.0.0.1", args.port, ssl=ctx,
                                        limit=1 << 22, backlog=1024)
    mode = "https" + ("+mTLS" if args.client_ca else "") if ctx else "http"
    print(f"origin '{args.name}' listening on {mode}://127.0.0.1:{args.port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
