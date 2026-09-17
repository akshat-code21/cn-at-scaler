#!/usr/bin/env python3
"""07_ratelimit.py - "100 requests per 10 seconds", four ways.

(10 s is the only period Cloudflare's free plan allows.) Simulated time, so
the answer is identical on every machine. Three traffic patterns:
  boundary attack   100 requests in the last 0.5 s of a window, 100 in the
                    first 0.5 s of the next, then a flood at 50 req/s
  page loads        a real browser: 30 requests at once, every 10 s
  steady            9 req/s for a minute - under the limit, must all pass
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "edge"))
from ratelimit import (FixedWindow, SlidingLog, SlidingWindowCounter, TokenBucket,  # noqa: E402
                       LeakyBucket)

LIMIT, WINDOW = 100, 10.0


def limiters():
    return [FixedWindow(LIMIT, WINDOW), SlidingLog(LIMIT, WINDOW), SlidingWindowCounter(LIMIT, WINDOW),
            TokenBucket(LIMIT / WINDOW, LIMIT), LeakyBucket(LIMIT / WINDOW, 0),
            LeakyBucket(LIMIT / WINDOW, LIMIT)]


def label(lim):
    if isinstance(lim, LeakyBucket):
        return f"leaky bucket, burst={lim.burst:g}"
    return lim.name


def boundary_attack():
    t = [9.5 + i * 0.005 for i in range(100)] + [10.0 + i * 0.005 for i in range(100)]
    t += [10.5 + i * 0.02 for i in range(int(19.5 / 0.02))]         # 50 req/s until t=30
    return t


def page_loads():
    return [load * 10.0 + i * 0.001 for load in range(6) for i in range(30)]


def steady():
    return [i / 9 for i in range(9 * 60)]


def run(lim, times):
    return [t for t in times if lim.allow("client", t)]


def max_in(accepted, span):
    best, j = 0, 0
    for i, t in enumerate(accepted):
        while accepted[j] <= t - span:
            j += 1
        best = max(best, i - j + 1)
    return best


def main():
    print(f"limit: {LIMIT} requests per {WINDOW:g} s\n")
    head = f"{'algorithm':<30}{'attack: in 9.5-10.5 s':>23}{'max in any 10 s':>17}" \
           f"{'page loads refused':>20}{'steady refused':>16}"
    print(head)
    print("-" * len(head))
    for i in range(len(limiters())):
        a = run(limiters()[i], boundary_attack())
        p = page_loads()
        pa = run(limiters()[i], p)
        s = steady()
        sa = run(limiters()[i], s)
        straddle = sum(1 for t in a if 9.5 <= t < 10.5)
        print(f"{label(limiters()[i]):<30}{straddle:>23}{max_in(a, WINDOW):>17}"
              f"{1 - len(pa) / len(p):>20.0%}{1 - len(sa) / len(s):>16.0%}")
    print("\nA fixed window lets 2x the limit through in ONE second. The exact log is\n"
          "perfect and stores up to 100 timestamps per client; the sliding estimate\n"
          "(Cloudflare, 2017) stores two counters and gets fooled only when a client\n"
          "packs a whole window into its last instant. Buckets allow burst + rate by\n"
          "design. With burst=0, nginx's limit_req refuses a normal page load.")


if __name__ == "__main__":
    main()
