"""httpmini - just enough HTTP/1.1 for a toy origin and a toy CDN edge.

Framing rule used everywhere in this repo (Session 2, Session 5):
    headers end at the blank line; the body is exactly Content-Length bytes.
No chunked encoding on the wire we generate - it keeps the edge honest about
where one message ends and the next begins on a kept-alive connection.
"""
import asyncio
import socket
import ssl
import time

MAX_HEAD = 64 * 1024


class Headers:
    """Ordered, case-insensitive, multi-valued header list."""

    def __init__(self, items=None):
        self.items = list(items or [])

    def get(self, name, default=None):
        n = name.lower()
        for k, v in self.items:
            if k.lower() == n:
                return v
        return default

    def get_all(self, name):
        n = name.lower()
        return [v for k, v in self.items if k.lower() == n]

    def set(self, name, value):
        self.remove(name)
        self.items.append((name, str(value)))

    def add(self, name, value):
        self.items.append((name, str(value)))

    def remove(self, name):
        n = name.lower()
        self.items = [(k, v) for k, v in self.items if k.lower() != n]

    def __contains__(self, name):
        return self.get(name) is not None

    def copy(self):
        return Headers(self.items)

    def encode(self):
        return b"".join(f"{k}: {v}\r\n".encode("latin-1") for k, v in self.items)


class Request:
    def __init__(self, method, target, version, headers, body=b""):
        self.method, self.target, self.version = method, target, version
        self.headers, self.body = headers, body

    @property
    def path(self):
        return self.target.split("?", 1)[0]

    @property
    def query(self):
        return self.target.split("?", 1)[1] if "?" in self.target else ""

    def encode(self):
        h = self.headers.copy()
        if self.body or self.method in ("POST", "PUT"):
            h.set("Content-Length", len(self.body))
        head = f"{self.method} {self.target} HTTP/1.1\r\n".encode() + h.encode() + b"\r\n"
        return head + self.body


class Response:
    def __init__(self, status, reason="", headers=None, body=b""):
        self.status, self.reason = status, reason or REASONS.get(status, "")
        self.headers = headers or Headers()
        self.body = body

    def encode(self, head_only=False):
        h = self.headers.copy()
        h.set("Content-Length", len(self.body))
        head = f"HTTP/1.1 {self.status} {self.reason}\r\n".encode() + h.encode() + b"\r\n"
        return head if head_only else head + self.body


REASONS = {200: "OK", 204: "No Content", 301: "Moved Permanently", 304: "Not Modified",
           400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
           405: "Method Not Allowed", 429: "Too Many Requests", 500: "Internal Server Error",
           502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout"}


class ProtocolError(Exception):
    pass


async def _read_head(reader):
    try:
        raw = await reader.readuntil(b"\r\n\r\n")
    except asyncio.IncompleteReadError as e:
        if not e.partial:
            return None          # clean EOF between messages
        raise ProtocolError("connection closed mid-head")
    except asyncio.LimitOverrunError:
        raise ProtocolError("head too large")
    lines = raw[:-4].decode("latin-1").split("\r\n")
    headers = Headers()
    for line in lines[1:]:
        if ":" not in line:
            raise ProtocolError(f"bad header line {line!r}")
        k, v = line.split(":", 1)
        headers.add(k.strip(), v.strip())
    return lines[0], headers


async def _read_body(reader, headers):
    if headers.get("Transfer-Encoding"):
        raise ProtocolError("chunked not supported by httpmini")
    n = int(headers.get("Content-Length", "0") or 0)
    return await reader.readexactly(n) if n else b""


async def read_request(reader):
    got = await _read_head(reader)
    if got is None:
        return None
    start, headers = got
    parts = start.split(" ")
    if len(parts) != 3:
        raise ProtocolError(f"bad request line {start!r}")
    method, target, version = parts
    body = await _read_body(reader, headers)
    return Request(method, target, version, headers, body)


async def read_response(reader, method="GET"):
    got = await _read_head(reader)
    if got is None:
        raise ProtocolError("upstream closed before responding")
    start, headers = got
    _, code, *reason = start.split(" ", 2)
    status = int(code)
    body = b"" if (method == "HEAD" or status in (204, 304)) else await _read_body(reader, headers)
    return Response(status, reason[0] if reason else "", headers, body)


def nodelay(writer):
    """Session 5's bug: write(head); write(body) + Nagle + delayed ACK = 40 ms.
    We always write whole messages, and turn Nagle off anyway."""
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass


def server_tls_context(cert, key, client_ca=None):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(cert, key)
    ctx.num_tickets = 0          # keep the handshake to exactly one server flight
    if client_ca:
        ctx.verify_mode = ssl.CERT_REQUIRED     # mTLS: "authenticated origin pulls"
        ctx.load_verify_locations(client_ca)
    return ctx


def client_tls_context(ca, cert=None, key=None):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_verify_locations(ca)
    if cert:
        ctx.load_cert_chain(cert, key)
    return ctx


async def connect(host, port, tls_ctx=None, server_hostname="localhost"):
    """Open TCP, then TLS, and report how long each took (ms)."""
    t0 = time.perf_counter()
    reader, writer = await asyncio.open_connection(host, port, limit=MAX_HEAD * 64)
    t1 = time.perf_counter()
    nodelay(writer)
    if tls_ctx is not None:
        await writer.start_tls(tls_ctx, server_hostname=server_hostname)
    t2 = time.perf_counter()
    return reader, writer, (t1 - t0) * 1000, (t2 - t1) * 1000


def parse_cache_control(value):
    out = {}
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower()] = v.strip().strip('"')
        else:
            out[part.lower()] = True
    return out


def peer_ip(writer):
    peer = writer.get_extra_info("peername")
    return peer[0] if peer else "?"
