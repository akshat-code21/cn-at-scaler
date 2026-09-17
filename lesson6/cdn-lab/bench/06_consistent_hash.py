#!/usr/bin/env python3
"""06_consistent_hash.py - the algorithm Akamai was founded on.

Karger, Lehman, Leighton, Levine, Lewin, Panigrahy - "Consistent Hashing and
Random Trees", STOC 1997. Which cache server holds which URL? When a server
is added, how many URLs suddenly live somewhere else (i.e. become misses)?
nginx ships the same idea: `hash $request_uri consistent;` (ketama).
"""
import bisect
import hashlib
import statistics

KEYS = [f"/video/{i}/seg-{j}.ts" for i in range(2000) for j in range(50)]   # 100,000 URLs


def h(s):
    return int.from_bytes(hashlib.md5(s.encode()).digest()[:8], "big")


def modulo(servers):
    return lambda k: servers[h(k) % len(servers)]


def ring(servers, vnodes):
    points = sorted((h(f"{s}#{v}"), s) for s in servers for v in range(vnodes))
    hashes = [p for p, _ in points]

    def lookup(k):
        i = bisect.bisect(hashes, h(k)) % len(points)
        return points[i][1]
    return lookup


def moved(before, after):
    return sum(before(k) != after(k) for k in KEYS) / len(KEYS)


def spread(fn, servers):
    counts = {s: 0 for s in servers}
    for k in KEYS:
        counts[fn(k)] += 1
    vals = list(counts.values())
    return max(vals) / statistics.mean(vals)


def main():
    ten = [f"cache{i:02d}" for i in range(10)]
    eleven = ten + ["cache10"]
    print(f"{len(KEYS):,} URLs, 10 cache servers -> add an 11th (ideal: 1/11 = {1 / 11:.1%} move)\n")
    print(f"{'scheme':<32}{'URLs that move':>16}{'busiest server vs mean':>26}")
    rows = [("hash(url) % N", modulo(ten), modulo(eleven)),
            ("consistent hash, 1 point/server", ring(ten, 1), ring(eleven, 1)),
            ("consistent hash, 160 points", ring(ten, 160), ring(eleven, 160))]
    for name, a, b in rows:
        print(f"{name:<32}{moved(a, b):>15.1%}{spread(b, eleven):>22.2f}x")
    print("\nModulo hashing turns a capacity upgrade into a cold cache for ~90% of URLs.\n"
          "Consistent hashing moves only the new server's share; virtual points fix the\n"
          "uneven load that a single point per server gives you.")


if __name__ == "__main__":
    main()
