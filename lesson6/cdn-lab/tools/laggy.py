#!/usr/bin/env python3
"""laggy.py - a TCP proxy that adds distance.

Every chunk is held for RTT/2 in each direction, in order. That is what a
long fibre does to a TCP stream when nothing is lost: it does not slow the
bytes down, it makes them late. Bandwidth and loss are not modelled - this is
the physics floor, not a network emulator (use tc netem on Linux for that).

    laggy.py --listen 7000 --to 127.0.0.1:8443 --rtt 10
"""
import argparse
import asyncio
import time


async def pump(reader, writer, delay):
    queue = asyncio.Queue()

    async def recv():
        try:
            while True:
                data = await reader.read(65536)
                await queue.put((time.monotonic() + delay, data))
                if not data:
                    return
        except (ConnectionError, OSError):
            await queue.put((time.monotonic() + delay, b""))

    async def send():
        try:
            while True:
                due, data = await queue.get()
                wait = due - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                if not data:
                    if writer.can_write_eof():
                        writer.write_eof()
                    return
                writer.write(data)
                await writer.drain()
        except (ConnectionError, OSError):
            pass

    await asyncio.gather(recv(), send())


async def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--listen", type=int, required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--rtt", type=float, required=True, help="round-trip time to add, in ms")
    args = p.parse_args()
    host, port = args.to.split(":")
    half = args.rtt / 2000.0

    async def handle(cr, cw):
        try:
            ur, uw = await asyncio.open_connection(host, int(port))
        except OSError:
            cw.close()
            return
        for w in (cw, uw):
            sock = w.get_extra_info("socket")
            if sock is not None:
                import socket
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # the SYN/SYN-ACK round trip happened instantly above; charge it now
        await asyncio.sleep(2 * half)
        await asyncio.gather(pump(cr, uw, half), pump(ur, cw, half), return_exceptions=True)
        cw.close()
        uw.close()

    server = await asyncio.start_server(handle, "127.0.0.1", args.listen, backlog=1024)
    print(f"laggy :{args.listen} -> {args.to}  (+{args.rtt:g} ms RTT)", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
