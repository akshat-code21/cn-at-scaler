"""ratelimit.py - four ways to say "10 requests per second".

Every class takes explicit timestamps so bench/07_ratelimit.py can replay an
attack in simulated time and get the same answer on every machine.
"""
import math


class FixedWindow:
    name = "fixed window"

    def __init__(self, limit, window):
        self.limit, self.window, self.state = limit, window, {}

    def allow(self, key, now):
        win = math.floor(now / self.window)
        w, n = self.state.get(key, (win, 0))
        if w != win:
            w, n = win, 0
        if n >= self.limit:
            self.state[key] = (w, n)
            return False
        self.state[key] = (w, n + 1)
        return True


class SlidingLog:
    """Exact: remember every accepted timestamp. Correct, and costs up to
    `limit` numbers per client instead of two."""
    name = "sliding log (exact)"

    def __init__(self, limit, window):
        self.limit, self.window, self.state = limit, window, {}

    def allow(self, key, now):
        log = [t for t in self.state.get(key, []) if t > now - self.window]
        ok = len(log) < self.limit
        if ok:
            log.append(now)
        self.state[key] = log
        return ok


class SlidingWindowCounter:
    """The approximation Cloudflare described in 2017: weight the previous
    window's count by how much of it still overlaps the sliding window."""
    name = "sliding window (approx.)"

    def __init__(self, limit, window):
        self.limit, self.window, self.state = limit, window, {}

    def allow(self, key, now):
        win = math.floor(now / self.window)
        cur_w, cur, prev = self.state.get(key, (win, 0, 0))
        if win == cur_w + 1:
            prev, cur = cur, 0
        elif win != cur_w:
            prev, cur = 0, 0
        elapsed = now - win * self.window
        estimate = prev * (self.window - elapsed) / self.window + cur
        if estimate + 1 > self.limit:
            self.state[key] = (win, cur, prev)
            return False
        self.state[key] = (win, cur + 1, prev)
        return True


class TokenBucket:
    name = "token bucket"

    def __init__(self, rate, burst):
        self.rate, self.burst, self.state = rate, burst, {}

    def allow(self, key, now):
        tokens, last = self.state.get(key, (self.burst, now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens < 1:
            self.state[key] = (tokens, now)
            return False
        self.state[key] = (tokens - 1, now)
        return True


class LeakyBucket:
    """nginx limit_req (Session 4's self-study): track the 'excess' above the
    configured rate; refuse once excess exceeds burst. This is the nodelay
    variant - without nodelay nginx would queue instead of refusing."""
    name = "leaky bucket (nginx limit_req)"

    def __init__(self, rate, burst=0):
        self.rate, self.burst, self.state = rate, burst, {}

    def allow(self, key, now):
        if key not in self.state:
            self.state[key] = (0.0, now)
            return True
        excess, last = self.state[key]
        # ngx_http_limit_req_module.c: excess = lr->excess - rate * ms / 1000 + 1000
        excess = max(excess - self.rate * (now - last) + 1.0, 0.0)
        if excess > self.burst + 1e-9:
            return False                      # nginx does not store a refused request
        self.state[key] = (excess, now)
        return True
