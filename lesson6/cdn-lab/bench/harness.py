"""harness.py - start origins, edges and laggy links; time requests.

Used by every bench script so that each one reads like the diagram it tests.
"""
import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lib"))
from httpmini import Request, Headers, read_response, connect, client_tls_context  # noqa: E402

CA = os.path.join(ROOT, "certs", "ca.pem")
PY = sys.executable


def wait_port(port, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), 0.2):
            return
        time.sleep(0.05)
    raise RuntimeError(f"nothing listening on {port}")


class Procs:
    def __init__(self):
        self.procs = []

    def start(self, script, *args, port):
        p = subprocess.Popen([PY, os.path.join(ROOT, script), *map(str, args)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.procs.append(p)
        wait_port(port)
        return p

    def origin(self, port, *args):
        return self.start("origin/origin.py", "--port", port, *args, port=port)

    def edge(self, port, *args):
        return self.start("edge/edge.py", "--port", port, *args, port=port)

    def laggy(self, port, to, rtt):
        return self.start("tools/laggy.py", "--listen", port, "--to", f"127.0.0.1:{to}",
                          "--rtt", rtt, port=port)

    def stop(self, p):
        p.terminate()
        p.wait(5)
        self.procs.remove(p)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            with contextlib.suppress(Exception):
                p.wait(5)


class Client:
    """One client connection. new() opens it; get() times one request."""

    def __init__(self, port, tls=False, cookie=None, headers=()):
        self.port, self.tls = port, tls
        self.ctx = client_tls_context(CA) if tls else None
        self.extra = [("Host", "news.example")] + ([("Cookie", cookie)] if cookie else []) + list(headers)
        self.reader = self.writer = None
        self.bytes_in = 0

    async def open(self):
        self.reader, self.writer, _, _ = await connect("127.0.0.1", self.port, self.ctx)

    async def get(self, target, headers=(), method="GET", body=b""):
        t0 = time.perf_counter()
        if self.writer is None:
            await self.open()
        req = Request(method, target, "HTTP/1.1", Headers(self.extra + list(headers)), body)
        self.writer.write(req.encode())
        await self.writer.drain()
        resp = await read_response(self.reader, method)
        self.bytes_in += len(resp.encode())
        return resp, (time.perf_counter() - t0) * 1000

    def close(self):
        if self.writer:
            self.writer.close()
            self.writer = None


async def one_shot(port, target, tls=False, **kw):
    c = Client(port, tls, **kw)
    try:
        return await c.get(target)
    finally:
        c.close()


def stats(port, which="edge"):
    path = "/__edge/stats" if which == "edge" else "/__origin/stats"
    resp, _ = asyncio.run(one_shot(port, path))
    return json.loads(resp.body)


async def astats(port, which="edge", tls=False):
    path = "/__edge/stats" if which == "edge" else "/__origin/stats"
    resp, _ = await one_shot(port, path, tls=tls)
    return json.loads(resp.body)


def table(rows, header):
    rows = [tuple(str(x) for x in r) for r in rows]
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    line = "  ".join(f"{{:<{w}}}" for w in widths)
    print(line.format(*header))
    print(line.format(*["-" * w for w in widths]))
    for r in rows:
        print(line.format(*r))
