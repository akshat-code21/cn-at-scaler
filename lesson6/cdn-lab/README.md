# cdn-lab — Session 6, (Ab)using CDNs

A CDN point of presence in one Python file, an origin that is naive in the usual ways,
a TCP proxy that adds distance, and the benchmarks behind every number in the deck.
Python 3.11+ and `openssl`. **No network needed** except for `cloudflare/`.

```
./setup.sh      # private CA + three certificates
./run_all.sh    # every bench and every demo, ~80 s
```

`pip install zstandard brotli` is optional; bench 05 then also measures `dcz` (RFC 9842) and `br`.

## What is in here

| Path | What it is |
|---|---|
| `origin/origin.py` | The app server. Trusts `X-User`, builds SQL with f-strings (unless `--safe`), reflects `X-Forwarded-Host`, leaks `X-Powered-By`. Counts everything at `/__origin/stats`. |
| `edge/edge.py` | The CDN: rate limit → WAF → gateway (JWT, header hygiene) → cache (MISS/HIT/REVALIDATED/STALE/UPDATING/DYNAMIC/BYPASS, request collapsing) → origin pool (shared or per-worker, failover) → ESI. `/cdn-cgi/trace`, `/__edge/stats`, `/__edge/purge`. |
| `edge/waf.py` | Five regex rules and three normalisation levels. |
| `edge/ratelimit.py` | Fixed window, sliding log, sliding-window estimate, token bucket, nginx's leaky bucket. |
| `edge/jwtlite.py` | HS256 JWTs with the standard library. Refuses `alg: none`. |
| `lib/httpmini.py` | Just enough HTTP/1.1. Length-framed only; `TCP_NODELAY` on, because of Session 5's 40 ms bug. |
| `tools/laggy.py` | TCP proxy that delays every chunk by RTT/2 each way. Physics floor only — no loss, no bandwidth. |
| `tools/echo_server.py` | Put it behind `cloudflared` and watch what arrives. |
| `tools/mint_jwt.py` | `mint_jwt.py SECRET SUBJECT [TTL]` |
| `bench/01_physics.py` | Great-circle distance, light in glass, measured pings from Mumbai, Akamai's 2010 distance-vs-throughput table against the Mathis model. |
| `bench/02_split_tcp.py` | Direct vs edge (no pool / warm pool / cache hit), all TLS 1.3, 10 + 194 ms. |
| `bench/03_pool.py` | Connection reuse: no pool, 32 worker pools, 8 worker pools, 1 shared pool. |
| `bench/04_esi_bytes.py` | 100 users, origin-assembled vs ESI. Asserts the pages are identical first. |
| `bench/05_delta.py` | Railgun's idea: compress a page against the previous minute's version. |
| `bench/06_consistent_hash.py` | Add an 11th cache server: modulo vs consistent hashing. |
| `bench/07_ratelimit.py` | "100 per 10 s", five algorithms, three traffic patterns, simulated time. |
| `demos/*.sh` | `cache`, `esi`, `waf`, `gateway` (JWT, origin bypass, mTLS), `poison`, `failover`. |
| `cloudflare/no-account.sh` | Real-Internet demos any student can run: trace, anycast, headers, physics, quick tunnel. |
| `cloudflare/INSTRUCTOR.md` | Free-plan dashboard demos: orange cloud, Cache Rules, WAF, rate limiting, Transform Rules, Workers, Tunnel. |
| `cloudflare/worker-esi`, `worker-gateway` | Two Workers. `node test_workers.mjs` runs both in workerd against the local origin (needs `npm i miniflare@4`). |

## The numbers (this build machine, Sep 2026)

```
02  direct, new connection 621 ms (3.0 RTT) · kept-alive 208 · edge no pool 625 ·
    edge warm pool 233 · warm + kept-alive 209 · cache HIT 34 · HIT kept-alive 11
03  reuse: no pool 0% · 32 worker pools 45.3% · 8 worker pools 82.7% · 1 shared pool 98.7%
04  origin bytes 3,984,200 -> 83,454 (-97.9%) · bytes to users +0.1% · origin requests 100 -> 201
05  24 KB page: gzip 4,276 B · deflate+dict 598 B · zstd+dict 436 B (1-minute-old dictionary)
06  add an 11th server: modulo moves 90.9% of URLs · consistent (160 points) 8.2%
07  fixed window lets 200 through in one second · sliding log 100 · estimate 104
```

## Things this lab does not model

- **Loss and bandwidth.** `laggy.py` delays; it never drops. BBR vs CUBIC needs `tc netem`
  on a real Linux box (homework 2).
- **HTTP/2 to the origin.** Every hop here is HTTP/1.1, as most CDN-to-origin hops still
  are by default (`cloudflared` too: `http2Origin` defaults to false).
- **Anycast and BGP.** One machine has one route. Use `cloudflare/no-account.sh`.
- **The worker-pool bench is a model.** A real nginx worker gets connections from the
  kernel's accept queue; here each visitor is assigned a random simulated worker.

## Why the ESI Worker does not use HTMLRewriter

It did at first, and it ate the page header. HTML has no self-closing custom elements, so
an HTML parser reads `<esi:include src="..."/>` as an *open* tag whose content runs to
`</header>`; `replace()` removed all of it, and `removeAndKeepContent()` took `</header>`
with it. ESI is XML-ish markup inside HTML, and the two grammars disagree about where an
element ends — Session 2's framing question, again. The Worker uses a regex, and
`test_workers.mjs` checks the result byte-for-byte against the origin's own assembly.
