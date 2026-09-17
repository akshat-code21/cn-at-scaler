#!/usr/bin/env python3
"""01_physics.py - how far away is your origin, in milliseconds?

No sockets. Great-circle distance, light in glass, and two published
measurements to keep the model honest.
"""
import math

C_VACUUM = 299_792.458            # km/s
GROUP_INDEX = 1.468               # single-mode fibre near 1550 nm
C_FIBRE = C_VACUUM / GROUP_INDEX  # ~204,000 km/s

CITIES = {
    "Mumbai": (19.0760, 72.8777), "Chennai": (13.0827, 80.2707), "New Delhi": (28.6139, 77.2090),
    "Singapore": (1.3521, 103.8198), "Tokyo": (35.6762, 139.6503), "London": (51.5074, -0.1278),
    "Frankfurt": (50.1109, 8.6821), "New York": (40.7128, -74.0060),
    "Washington DC": (38.9072, -77.0369), "Los Angeles": (34.0522, -118.2437),
}
# Average ping from a Mumbai host, WonderNetwork (wondernetwork.com/pings), 8-17 Sep 2026.
# One pair of machines per city: a sample of real routing, not a law.
MEASURED = {"Chennai": 23.44, "New Delhi": 26.93, "Singapore": 155.82, "Tokyo": 134.99,
            "London": 124.97, "Frankfurt": 132.66, "New York": 180.46,
            "Washington DC": 203.78, "Los Angeles": 229.31}


def km(a, b):
    (la1, lo1), (la2, lo2) = CITIES[a], CITIES[b]
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


def main():
    print(f"light in fibre: {C_FIBRE:,.0f} km/s  ->  {1000 / C_FIBRE * 1000:.2f} ms per 1000 km, one way")
    print(f"hollow-core fibre (index ~1.0003) would be {GROUP_INDEX / 1.0003 - 1:.0%} faster\n")
    rows = []
    for dst, ping in MEASURED.items():
        d = km("Mumbai", dst)
        floor = 2 * d / C_FIBRE * 1000
        rows.append((dst, f"{d:,.0f}", f"{floor:.0f}", f"{ping:.0f}", f"{ping / floor:.1f}x",
                     f"{3 * ping:.0f}"))
    w = [14, 7, 10, 10, 9, 15]
    head = ("Mumbai to", "km", "RTT floor", "measured", "stretch", "3 RTT (TLS 1.3)")
    print("  ".join(h.ljust(x) for h, x in zip(head, w)))
    print("  ".join("-" * x for x in w))
    for r in rows:
        print("  ".join(c.ljust(x) for c, x in zip(r, w)))
    print("\n'RTT floor' is straight fibre along the great circle. 'measured' is a real\n"
          "ping (WonderNetwork, Sep 2026). Singapore is 3.3x closer than Washington and\n"
          "only 1.3x faster: that gap is routing, not physics, and it is the part a CDN\n"
          "can buy back. Singla et al. (HotNets 2014) put the median at 3.2x c-latency.\n")

    # Nygren, Sitaraman, Sun - "The Akamai Network" (SIGOPS OSR, 2010), Table 1
    akamai = [("local, <100 mi", 1.6, 0.6, 44.0), ("regional, 500-1,000 mi", 16, 0.7, 4.0),
              ("cross-continent, ~3,000 mi", 48, 1.0, 1.0), ("multi-continent, ~6,000 mi", 96, 1.4, 0.4)]
    print("Akamai 2010, measured          RTT ms  loss %  Mbps   Mathis model (relative)")
    base = None
    for name, rtt, loss, mbps in akamai:
        model = 1.22 * 1460 * 8 / (rtt / 1000) / math.sqrt(loss / 100) / 1e6   # Mathis et al. 1997
        base = base or (mbps, model)
        print(f"  {name:<28} {rtt:>6} {loss:>7} {mbps:>6}   {model:6.1f}  "
              f"(x{base[1] / model:5.1f} slower; measured x{base[0] / mbps:5.1f})")
    print("\nThroughput ~ MSS / (RTT * sqrt(loss)). Distance costs you twice: once in RTT,\n"
          "and again because longer paths lose more. Both are why the edge exists.")


if __name__ == "__main__":
    main()
