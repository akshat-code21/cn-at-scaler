#!/usr/bin/env python3
"""edge.py - a CDN point of presence in one file.

Per request, in order:
   rate limit -> WAF -> gateway (JWT, header hygiene) -> cache -> origin pool
                                                                 -> ESI assembly
Every stage can be switched on from the command line, so each demo turns on
exactly one idea. GET /__edge/stats tells you what happened.
"""
import argparse
import asyncio
import contextvars
import json
import os
import random
import secrets
import sys
import time
from urllib.parse import parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)
from httpmini import (Headers, Request, Response, ProtocolError, read_request,  # noqa: E402
                      read_response, connect, nodelay, server_tls_context,
                      client_tls_context, parse_cache_control, peer_ip)
import waf  # noqa: E402
import jwtlite  # noqa: E402
from ratelimit import SlidingWindowCounter  # noqa: E402

CERTS = os.path.join(HERE, "..", "certs")

# Cloudflare's default is "by file extension"; HTML and JSON are not on the list.
DEFAULT_EXT = {"css", "js", "png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "woff",
               "woff2", "ttf", "pdf", "zip", "mp4", "mp3", "webm", "txt", "csv"}
DEFAULT_TTL = {200: 7200, 206: 7200, 301: 7200, 302: 1200, 303: 1200, 404: 180, 410: 180}
HOP_BY_HOP = ("Connection", "Keep-Alive", "TE", "Trailer", "Transfer-Encoding", "Upgrade",
              "Proxy-Connection", "Proxy-Authorization")


def new_stats():
    return dict(requests=0, origin_requests=0, origin_new_connections=0, origin_reused=0,
                origin_bytes_in=0, client_bytes_out=0, cache={}, blocked_waf=0, blocked_rate=0,
                blocked_auth=0, failovers=0, esi_fragments=0, collapsed=0, stale_retries=0)


STATS = new_stats()
WORKER = contextvars.ContextVar("worker", default=0)   # which simulated worker owns this client


class Conn:
    def __init__(self, reader, writer):
        self.reader, self.writer, self.used = reader, writer, 0

    def dead(self):
        return self.reader.at_eof() or self.writer.is_closing()


class OriginPool:
    """Idle keep-alive connections to one origin. max_idle=0 means
    'open a fresh connection for every request' - the cold path."""

    def __init__(self, host, port, tls_ctx, max_idle):
        self.host, self.port, self.tls_ctx, self.max_idle = host, port, tls_ctx, max_idle
        self.idle = []
        self.down_until = 0.0

    async def acquire(self):
        while self.idle:
            c = self.idle.pop()
            if not c.dead():
                STATS["origin_reused"] += 1
                return c, True
            c.writer.close()
        reader, writer, _, _ = await asyncio.wait_for(
            connect(self.host, self.port, self.tls_ctx), timeout=5)
        STATS["origin_new_connections"] += 1
        return Conn(reader, writer), False

    def release(self, c, reusable):
        c.used += 1
        if reusable and len(self.idle) < self.max_idle and not c.dead():
            self.idle.append(c)
        else:
            c.writer.close()


class CacheEntry:
    def __init__(self, resp, ttl, cc):
        self.resp, self.ttl, self.stored = resp, ttl, time.monotonic()
        self.swr = int(cc.get("stale-while-revalidate", 0) or 0)
        self.sie = int(cc.get("stale-if-error", 0) or 0)

    @property
    def age(self):
        return time.monotonic() - self.stored

    def fresh(self):
        return self.age < self.ttl


class Edge:
    def __init__(self, args):
        self.args = args
        origin_ctx = None
        if args.origin_tls:
            cert = os.path.join(CERTS, "edge-client.pem") if args.client_cert else None
            key = os.path.join(CERTS, "edge-client.key") if args.client_cert else None
            origin_ctx = client_tls_context(os.path.join(CERTS, "ca.pem"), cert, key)
        oh, op = args.origin.split(":")
        # --pools K simulates K worker processes, each with its own pool (nginx);
        # K=1 is one shared pool (Pingora).
        self.pools = [OriginPool(oh, int(op), origin_ctx, args.pool) for _ in range(args.pools)]
        self.rng = random.Random(args.seed)
        self.backup = None
        if args.backup:
            bh, bp = args.backup.split(":")
            self.backup = OriginPool(bh, int(bp), origin_ctx, args.pool)
        self.cache = {}
        self.inflight = {}
        self.limiter = None
        if args.rate:
            n, per = args.rate.split("/")
            self.limiter = SlidingWindowCounter(int(n), float(per))

    # ------------------------------------------------------------------ origin
    async def to_origin(self, req, pool):
        """One request on one pooled connection; retry once if a reused
        connection turns out to have been closed by the origin meanwhile."""
        for attempt in (1, 2):
            conn, reused = await pool.acquire()
            try:
                if not self.args.pool:
                    req.headers.set("Connection", "close")
                conn.writer.write(req.encode())
                await conn.writer.drain()
                resp = await asyncio.wait_for(read_response(conn.reader, req.method),
                                              timeout=self.args.origin_timeout)
            except (ConnectionError, ProtocolError, asyncio.IncompleteReadError):
                conn.writer.close()
                if reused and attempt == 1 and req.method in ("GET", "HEAD"):
                    STATS["stale_retries"] += 1
                    continue
                raise
            except BaseException:
                conn.writer.close()
                raise
            reusable = (resp.headers.get("Connection") or "").lower() != "close"
            pool.release(conn, reusable)
            STATS["origin_requests"] += 1
            STATS["origin_bytes_in"] += len(resp.encode())
            return resp

    def pick_pool(self):
        # A client connection belongs to one worker for its whole life, and the
        # kernel decides which; so does that worker's pool.
        return self.pools[WORKER.get() % len(self.pools)]

    async def fetch_origin(self, req):
        """Primary, then backup (passive health check, like nginx max_fails)."""
        fwd = Request(req.method, req.target, "HTTP/1.1", req.headers.copy(), req.body)
        primary = self.pick_pool()
        t0 = time.perf_counter()
        if time.monotonic() >= primary.down_until:
            try:
                resp = await self.to_origin(fwd, primary)
                if resp.status < 500 or not self.backup:
                    return resp, (time.perf_counter() - t0) * 1000
            except (OSError, ProtocolError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                if not self.backup:
                    raise
                primary.down_until = time.monotonic() + self.args.fail_timeout
        if not self.backup:
            raise ConnectionError("primary marked down")
        STATS["failovers"] += 1
        resp = await self.to_origin(fwd, self.backup)
        return resp, (time.perf_counter() - t0) * 1000

    # ------------------------------------------------------------------- cache
    def eligible(self, req):
        if self.args.no_cache or req.method not in ("GET", "HEAD"):
            return False
        ext = req.path.rsplit(".", 1)[-1].lower() if "." in req.path.rsplit("/", 1)[-1] else ""
        return ext in DEFAULT_EXT or any(req.path.startswith(p) for p in self.args.cache_prefix)

    def cache_key(self, req):
        # scheme + host + path + query: the Cloudflare default. Note what is
        # NOT here - every other request header. That is the poisoning demo.
        return f"{req.headers.get('Host', '')}{req.target}"

    def storable(self, resp):
        cc = parse_cache_control(resp.headers.get("Cache-Control"))
        if any(k in cc for k in ("private", "no-store", "no-cache")) or resp.headers.get("Set-Cookie"):
            return None, cc
        if "s-maxage" in cc:
            ttl = int(cc["s-maxage"])
        elif "max-age" in cc:
            ttl = int(cc["max-age"])
        else:
            ttl = DEFAULT_TTL.get(resp.status)
        if not ttl or resp.status not in DEFAULT_TTL:
            return None, cc
        return ttl, cc

    def remember(self, key, resp):
        ttl, cc = self.storable(resp)
        if ttl is None:
            return False
        self.cache[key] = CacheEntry(resp, ttl, cc)
        return True

    async def cached_fetch(self, req):
        """Returns (response, cache_status, origin_ms)."""
        if not self.eligible(req):
            resp, ms = await self.fetch_origin(req)
            return resp, "DYNAMIC", ms
        key = self.cache_key(req)
        entry = self.cache.get(key)
        if entry and entry.fresh():
            return entry.resp, "HIT", 0.0

        if entry and entry.age < entry.ttl + entry.swr:           # RFC 5861
            asyncio.ensure_future(self.revalidate(key, req, entry))
            return entry.resp, "UPDATING", 0.0

        if entry:
            etag = entry.resp.headers.get("ETag")
            cond = Request(req.method, req.target, "HTTP/1.1", req.headers.copy())
            if etag:
                cond.headers.set("If-None-Match", etag)
            try:
                resp, ms = await self.fetch_origin(cond)
            except (OSError, ProtocolError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                resp, ms = None, 0.0
            if resp is None or resp.status >= 500:
                if entry.age < entry.ttl + max(entry.sie, self.args.stale_if_error):
                    return entry.resp, "STALE", ms
                if resp is None:
                    raise ConnectionError("origin unreachable and nothing stale to serve")
                return resp, "EXPIRED", ms
            if resp.status == 304:
                entry.stored = time.monotonic()                     # fresh again
                return entry.resp, "REVALIDATED", ms
            self.remember(key, resp)
            return resp, "EXPIRED", ms

        # MISS. Request collapsing: one origin fetch per key, everyone else waits
        # (nginx's proxy_cache_lock from Session 4, Varnish/Fastly "collapsing").
        if key in self.inflight and self.args.collapse:
            STATS["collapsed"] += 1
            await asyncio.shield(self.inflight[key])
            entry = self.cache.get(key)
            if entry and entry.fresh():
                return entry.resp, "HIT", 0.0
        fut = asyncio.get_running_loop().create_future()
        self.inflight[key] = fut
        try:
            resp, ms = await self.fetch_origin(req)
            status = "MISS" if self.remember(key, resp) else "BYPASS"
            return resp, status, ms
        finally:
            fut.set_result(None)
            self.inflight.pop(key, None)

    async def revalidate(self, key, req, entry):
        try:
            resp, _ = await self.fetch_origin(req)
            self.remember(key, resp)
        except Exception:
            pass

    # --------------------------------------------------------------------- ESI
    async def assemble(self, req, resp):
        import re
        body = resp.body.decode("utf-8", "replace")
        tags = list(re.finditer(r'<esi:include\s+src="([^"]+)"\s*/>', body))
        if not tags:
            return resp

        async def one(src):
            sub = Request("GET", src, "HTTP/1.1", req.headers.copy())
            STATS["esi_fragments"] += 1
            try:
                r, _, _ = await self.cached_fetch(sub)
                return r.body.decode("utf-8", "replace") if r.status == 200 else ""
            except Exception:
                return ""

        # fragments in parallel - the same choice nginx's SSI module makes
        parts = await asyncio.gather(*(one(m.group(1)) for m in tags))
        out, last = [], 0
        for m, part in zip(tags, parts):
            out.append(body[last:m.start()])
            out.append(part)
            last = m.end()
        out.append(body[last:])
        h = resp.headers.copy()
        h.remove("Surrogate-Control")
        h.set("Cache-Control", "private, no-store")   # the assembled page is personal
        h.set("X-ESI-Fragments", len(tags))
        return Response(resp.status, resp.reason, h, "".join(out).encode())

    # ------------------------------------------------------------ the pipeline
    def trace(self, req, writer):
        tls = writer.get_extra_info("ssl_object")
        lines = [f"fl=cdn-lab", f"h={req.headers.get('Host', '')}", f"ip={peer_ip(writer)}",
                 f"ts={time.time():.3f}", f"visit_scheme={'https' if tls else 'http'}",
                 f"colo={self.args.name}", "http=http/1.1",
                 f"tls={tls.version() if tls else 'off'}", f"cache_entries={len(self.cache)}"]
        return Response(200, headers=Headers([("Content-Type", "text/plain")]),
                        body=("\n".join(lines) + "\n").encode())

    def admin(self, req):
        h = Headers([("Content-Type", "application/json")])
        if req.path == "/__edge/stats":
            s = dict(STATS, cache_entries=len(self.cache),
                     idle_pooled=sum(len(p.idle) for p in self.pools))
            return Response(200, headers=h, body=json.dumps(s).encode())
        if req.path == "/__edge/reset":
            STATS.clear()
            STATS.update(new_stats())
            return Response(204)
        if req.path == "/__edge/purge":
            q = parse_qs(req.query)
            if "all" in q:
                n = len(self.cache)
                self.cache.clear()
            else:
                keys = [k for k in self.cache if k.endswith(q.get("path", ["?"])[0])]
                n = len(keys)
                for k in keys:
                    del self.cache[k]
            return Response(200, headers=h, body=json.dumps({"purged": n}).encode())
        return Response(404)

    async def handle(self, req, writer):
        a = self.args
        client = req.headers.get("X-Sim-Client") or peer_ip(writer)
        if req.path == "/cdn-cgi/trace":
            return self.trace(req, writer), "EDGE", 0.0
        if req.path.startswith("/__edge/"):
            return self.admin(req), "EDGE", 0.0
        if a.name in (req.headers.get("CDN-Loop") or ""):          # RFC 8586
            return Response(508, "Loop Detected", body=b"CDN loop detected\n"), "EDGE", 0.0

        if self.limiter and not self.limiter.allow(client, time.monotonic()):
            STATS["blocked_rate"] += 1
            return Response(429, headers=Headers([("Retry-After", "10")]),
                            body=b"rate limited at the edge\n"), "BLOCKED", 0.0

        rule = waf.inspect(req.target, req.body, a.waf)
        if rule:
            STATS["blocked_waf"] += 1
            return Response(403, headers=Headers([("X-Edge-Block", rule)]),
                            body=f"blocked by edge rule {rule}\n".encode()), "BLOCKED", 0.0

        fwd = req.headers.copy()
        for name in HOP_BY_HOP:
            fwd.remove(name)
        fwd.remove("X-User")                  # never trust identity the client sent
        fwd.remove("X-Edge-Auth")
        if a.strip_unkeyed:
            fwd.remove("X-Forwarded-Host")    # or add it to the cache key - pick one
        if a.jwt_secret and req.path.startswith("/api/"):
            auth = req.headers.get("Authorization") or ""
            try:
                if not auth.startswith("Bearer "):
                    raise jwtlite.InvalidToken("missing bearer token")
                claims = jwtlite.verify(a.jwt_secret, auth.removeprefix("Bearer ").strip())
            except jwtlite.InvalidToken as e:
                STATS["blocked_auth"] += 1
                return Response(401, headers=Headers([("WWW-Authenticate", f'Bearer error="{e}"')]),
                                body=f"edge: {e}\n".encode()), "BLOCKED", 0.0
            fwd.set("X-User", claims["sub"])
            fwd.remove("Authorization")
        fwd.set("X-Forwarded-For", ", ".join(filter(None, [req.headers.get("X-Forwarded-For"),
                                                           peer_ip(writer)])))
        fwd.set("X-Forwarded-Proto", "https" if writer.get_extra_info("ssl_object") else "http")
        fwd.set("CDN-Loop", ", ".join(filter(None, [req.headers.get("CDN-Loop"), a.name])))
        if a.edge_secret:
            fwd.set("X-Edge-Auth", a.edge_secret)

        inner = Request(req.method, req.target, "HTTP/1.1", fwd, req.body)
        try:
            resp, status, ms = await self.cached_fetch(inner)
        except (OSError, ProtocolError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
            return Response(502, body=f"edge could not reach origin: {type(e).__name__}\n".encode()), \
                "ERROR", 0.0
        if a.esi and 'ESI/1.0' in (resp.headers.get("Surrogate-Control") or ""):
            t0 = time.perf_counter()
            resp = await self.assemble(inner, resp)
            ms += (time.perf_counter() - t0) * 1000
        return resp, status, ms

    async def serve_conn(self, reader, writer):
        nodelay(writer)
        WORKER.set(self.rng.randrange(len(self.pools)))
        try:
            while True:
                try:
                    req = await asyncio.wait_for(read_request(reader), timeout=self.args.idle)
                except asyncio.TimeoutError:
                    break
                if req is None:
                    break
                t0 = time.perf_counter()
                resp, status, origin_ms = await self.handle(req, writer)
                out = Response(resp.status, resp.reason, resp.headers.copy(), resp.body)
                h = out.headers
                for name in HOP_BY_HOP + ("X-Powered-By",):
                    h.remove(name)
                h.remove("Surrogate-Control")
                h.set("Server", "cdn-lab")
                if status not in ("EDGE",):
                    h.set("X-Cache", status)
                    h.set("X-Edge-Ray", f"{secrets.token_hex(8)}-{self.args.name}")
                    h.set("Via", f"1.1 {self.args.name}")
                    if status in ("HIT", "UPDATING", "STALE", "REVALIDATED"):
                        entry = self.cache.get(self.cache_key(req))
                        if entry:
                            h.set("Age", int(entry.age))
                    edge_ms = (time.perf_counter() - t0) * 1000 - origin_ms
                    h.set("Server-Timing", f"edge;dur={edge_ms:.1f}, origin;dur={origin_ms:.1f}")
                if writer.get_extra_info("ssl_object"):
                    h.set("Strict-Transport-Security", "max-age=31536000")
                if status != "EDGE":
                    STATS["requests"] += 1
                    STATS["cache"][status] = STATS["cache"].get(status, 0) + 1
                data = out.encode(head_only=req.method == "HEAD")
                STATS["client_bytes_out"] += len(data) if not req.path.startswith("/__edge") else 0
                writer.write(data)
                await writer.drain()
                if self.args.verbose:
                    print(f"[{self.args.name}] {req.method} {req.target} -> {out.status} {status}",
                          flush=True)
                if (req.headers.get("Connection") or "").lower() == "close":
                    break
        except (ProtocolError, ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()


async def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--name", default="BOM", help="colo code, like the suffix of a cf-ray")
    p.add_argument("--tls", action="store_true", help="terminate TLS with certs/edge.pem")
    p.add_argument("--origin", default="127.0.0.1:9000")
    p.add_argument("--origin-tls", action="store_true", help="HTTPS to the origin")
    p.add_argument("--client-cert", action="store_true", help="present certs/edge-client.pem (mTLS)")
    p.add_argument("--backup", help="host:port of a second origin")
    p.add_argument("--fail-timeout", type=float, default=10.0)
    p.add_argument("--origin-timeout", type=float, default=10.0)
    p.add_argument("--pool", type=int, default=64, help="max idle origin connections; 0 = no reuse")
    p.add_argument("--pools", type=int, default=1, help="isolated pools (simulated workers)")
    p.add_argument("--seed", type=int, default=6)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--cache-prefix", action="append", default=[], help="treat this path prefix as cacheable")
    p.add_argument("--no-collapse", dest="collapse", action="store_false")
    p.add_argument("--stale-if-error", type=int, default=0)
    p.add_argument("--esi", action="store_true")
    p.add_argument("--waf", choices=["off", "raw", "decode", "full"], default="off")
    p.add_argument("--rate", help="N/SECONDS per client, e.g. 20/10")
    p.add_argument("--jwt-secret")
    p.add_argument("--edge-secret")
    p.add_argument("--strip-unkeyed", action="store_true", help="drop client X-Forwarded-Host")
    p.add_argument("--idle", type=float, default=60.0)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    ctx = server_tls_context(os.path.join(CERTS, "edge.pem"), os.path.join(CERTS, "edge.key")) \
        if args.tls else None
    edge = Edge(args)
    server = await asyncio.start_server(edge.serve_conn, "127.0.0.1", args.port, ssl=ctx,
                                        limit=1 << 22, backlog=1024)
    print(f"edge {args.name} listening on {'https' if ctx else 'http'}://127.0.0.1:{args.port} "
          f"-> origin {args.origin}{' (tls)' if args.origin_tls else ''}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
