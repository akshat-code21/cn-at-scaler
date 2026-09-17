#!/usr/bin/env python3
"""echo_server.py - see what a CDN does to the requests it forwards to you.

    python3 tools/echo_server.py 8000
    cloudflared tunnel --url http://localhost:8000      # prints https://<random>.trycloudflare.com

Then ask the whole class to open that URL. This terminal prints one line per
request and, at the end of each TCP connection, how many requests rode on it.
Watch how few connections cloudflared needs for thirty people.
"""
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SHOW = ("Host", "CF-Connecting-IP", "CF-IPCountry", "CF-Ray", "CF-Visitor", "CDN-Loop",
        "X-Forwarded-For", "X-Forwarded-Proto", "Accept-Encoding", "Cf-Warp-Tag-Id")
lock = threading.Lock()
conns = {"open": 0, "total": 0}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # keep-alive, so reuse is visible

    def setup(self):
        super().setup()
        self.served = 0
        with lock:
            conns["open"] += 1
            conns["total"] += 1
            self.conn_id = conns["total"]

    def finish(self):
        super().finish()
        with lock:
            conns["open"] -= 1
        print(f"  conn #{self.conn_id} from {self.client_address[0]}:{self.client_address[1]} "
              f"closed after {self.served} requests  (open now: {conns['open']})", flush=True)

    def do_GET(self):
        self.served += 1
        seen = {k: self.headers[k] for k in SHOW if self.headers[k]}
        print(f"conn #{self.conn_id} req {self.served}: {self.command} {self.path}  {seen}", flush=True)
        body = ("You reached a laptop through the edge.\n\n" +
                "".join(f"{k}: {v}\n" for k, v in seen.items()) +
                f"\nTCP peer: {self.client_address[0]}  (that is cloudflared, not you)\n"
                f"this TCP connection has carried {self.served} request(s)\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    print(f"echo server on http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()
