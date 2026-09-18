# HTTP/1.1 Calculator Server

A minimal HTTP/1.1 server implementing four calculator endpoints over raw TCP
sockets — no frameworks. Built for the CN & Scaler Session 5 assignment
(Early HTTP/1.1, due before Session 7).

The point of the exercise is **connection persistence**: the server answers many
requests over a single TCP connection (keep-alive), consuming exactly
`Content-Length` bytes per request so the stream never desynchronizes.

## Run

```bash
cd assignment
javac Server.java
java assignment.Server
```

Listens on **port 8080**.

## Endpoints

| Request | Response |
|---|---|
| `GET /add?a=2&b=3` | `200` — `5` |
| `GET /sub?a=10&b=4` | `200` — `6` |
| `GET /mul?a=6&b=7` | `200` — `42` |
| `GET /div?a=9&b=3` | `200` — `3` |
| `GET /div?a=1&b=0` | `400` (division by zero) |
| `GET /add?a=x&b=3` | `400` (non-numeric operand) |
| `GET /add?a=2` | `400` (missing parameter) |
| `GET /pow?a=2&b=8` | `404` (unknown route) |
| `POST /add` | `405` (method not allowed) |
| `GET /add` without `Host` header | `400` |

## Example session (one connection, six requests)

```python
import socket

s = socket.create_connection(("localhost", 8080))
for req in [b"GET /add?a=2&b=3 HTTP/1.1\r\nHost: localhost\r\n\r\n",
            b"GET /div?a=1&b=0 HTTP/1.1\r\nHost: localhost\r\n\r\n"]:
    s.sendall(req)
    print(s.recv(1024).decode())
# 1 TCP handshake, 2 responses, socket still open
```

## Notes

- Pure Java stdlib (`java.net.ServerSocket` / `Socket`), single-threaded,
  keep-alive loop per connection.
- POST bodies are drained by `Content-Length` so the next request parses
  correctly on the same socket.
- Pipelining works: requests sent back-to-back are answered in order.
- Stretch goals (optional, not implemented): `Connection: close`,
  idle timeout, chunked transfer encoding.
