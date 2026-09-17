# Cloudflare demos that need an account (instructor only)

Free plan, one zone you own (call it `example.com`), one origin you control.
Everything here was written against Cloudflare's docs in September 2026; the two
Workers were run locally in workerd (Miniflare 4) against `origin/origin.py`
(`node test_workers.mjs`). The dashboard steps could not be run from the build
machine - **do a dry run before class.**

Free-plan limits that shape the demos (developers.cloudflare.com, Sep 2026):

| Product | Free plan |
|---|---|
| WAF custom rules | 5 rules, no regex |
| Managed rules | Cloudflare Free Managed Ruleset only (OWASP Core Ruleset needs Pro) |
| Rate limiting rules | 1 rule, counts by IP, period **10 s only**, mitigation 10 s |
| Cache Rules | 10 |
| Workers | 100,000 requests/day, 10 ms CPU per request |

## A. Orange cloud vs grey cloud (2 min)

1. DNS -> add `A demo -> <origin IP>`, proxy **off** (grey).
2. `dig +short demo.example.com` -> your origin's real IP. Anyone can attack it.
3. Toggle proxy **on** (orange). `dig +short demo.example.com` -> two Cloudflare anycast IPs.
4. `curl -sI https://demo.example.com | grep -i cf-ray` - the suffix is the PoP.

Say: *orange cloud hides nothing if the origin still accepts traffic from everyone.*
Old DNS history, MX records and certificate-transparency logs all leak origin IPs. Fixes: a
firewall that allows only Cloudflare's published IP ranges, **Authenticated Origin Pulls**
(mTLS - `demos/gateway.sh` shows the same idea), or **Cloudflare Tunnel** (no inbound port at all).

## B. Cache (5 min)

Run the origin: `python3 origin/origin.py --port 9000` behind the proxied hostname.

1. `curl -sI https://demo.example.com/static/app.css | grep -i cf-cache-status` twice -> `MISS`, `HIT`.
2. `curl -sI https://demo.example.com/page/home | grep -i cf-cache-status` -> `DYNAMIC`
   (HTML is not cached by default, even with `s-maxage=300`).
3. Caching -> Cache Rules -> create:
   - **If** `starts_with(http.request.uri.path, "/page/")`
   - **Then** Eligible for cache; Edge TTL: *Use cache-control header if present*.
4. Repeat step 2 -> `MISS`, then `HIT`, and an `age` header that counts up.
5. Caching -> Configuration -> **Custom Purge** -> URL -> the page. Next request: `MISS`.

## C. WAF custom rule (5 min)

Security -> WAF -> Custom rules -> create *Block naive SQLi*:

```
(http.request.uri.path eq "/search" and
 lower(url_decode(http.request.uri.query)) contains "union select")
```

Action: **Block**. Then:

```
curl -s -G https://demo.example.com/search --data-urlencode "q=x' union select 1--"   # 403
curl -s -G https://demo.example.com/search --data-urlencode "q=x' union/**/select 1--" # passes
curl -s -G https://demo.example.com/search --data-urlencode "q=' --"                   # passes
```

Same lesson as `demos/waf.sh`: a WAF is a list of spellings. Security -> Events shows each
block with its Ray ID.

## D. Rate limiting rule (3 min)

Security -> WAF -> Rate limiting rules -> create:

- **If** `starts_with(http.request.uri.path, "/api/")`
- characteristics: IP - **20 requests per 10 seconds** - action Block for 10 s

```
for i in $(seq 30); do curl -s -o /dev/null -w '%{http_code} ' https://demo.example.com/api/orders; done; echo
```

Expect ~20 `401`s (the origin wants a user) and then `429`s. Point out: counts are
**per data center** - a botnet spread across 300 cities gets 300 budgets.

## E. Transform rule: header hygiene (2 min)

Rules -> Transform Rules -> Modify Response Header:
- Remove `X-Powered-By`
- Set static `Strict-Transport-Security: max-age=31536000`

`curl -sI https://demo.example.com/api/orders | grep -iE 'powered|strict'`

## F. Workers (10 min)

```
cd cloudflare/worker-gateway
npx wrangler login
npx wrangler secret put JWT_SECRET      # e.g. session6
npx wrangler secret put EDGE_SECRET     # start the origin with --edge-secret <same>
# edit wrangler.toml: PRIMARY / BACKUP / routes
npx wrangler deploy
TOKEN=$(python3 ../../tools/mint_jwt.py session6 alice)
curl -s https://api.example.com/api/orders                                   # 401 at the edge
curl -s -H "Authorization: Bearer $TOKEN" https://api.example.com/api/orders # alice's orders
```

Kill PRIMARY and repeat: the response header `X-Origin: backup` shows the failover.

`worker-esi` works the same way (`ORIGIN` var, route `news.example.com/page/*`). Its
`X-Shell-Cache` header shows Cloudflare's cache status for the shell on the second visit,
while every visitor still gets their own name in the header.

## G. Cloudflare Tunnel, named (optional, 5 min)

```
cloudflared tunnel login
cloudflared tunnel create session6
cloudflared tunnel route dns session6 lab.example.com
cloudflared tunnel run --url http://localhost:9000 session6
```

The origin now has **no open inbound port**. There is nothing to find and nothing to scan.
This is the answer to section A.
