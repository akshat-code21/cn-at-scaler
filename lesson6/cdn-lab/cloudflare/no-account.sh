#!/usr/bin/env bash
# no-account.sh - Cloudflare demos any student can run. No login, no domain.
# Needs: curl, dig (dnsutils/bind-tools), optionally cloudflared, mtr/traceroute.
# Everything below talks to the real Internet; your numbers will differ from your
# neighbour's - that is the point.
set -u
say() { printf '\n\033[1;33m# %s\033[0m\n' "$*"; }
run() { printf '\033[36m$ %s\033[0m\n' "$*"; eval "$@"; }

say "1. Which Cloudflare building answered you? (colo = IATA airport code)"
run "curl -s https://www.cloudflare.com/cdn-cgi/trace"
say "   any Cloudflare-proxied site answers the same path, from the same PoP"
run "curl -s https://one.one.one.one/cdn-cgi/trace | grep -E '^(colo|http|tls|kex)='"

say "2. Anycast: one address, announced from 330+ cities. Which one did you reach?"
run "dig +short CHAOS TXT id.server @1.1.1.1"
run "ping -c 3 1.1.1.1 | tail -1"
say "   ...and how many routers away is it? (try: mtr -rwc 5 1.1.1.1)"
run "traceroute -n -q 1 -w 1 -m 12 1.1.1.1 2>/dev/null | tail -4 || true"

say "3. The headers a CDN adds"
run "curl -sI https://www.cloudflare.com/ | grep -iE '^(server|cf-ray|cf-cache-status|age|alt-svc|cache-control):'"

say "4. Physics: the same handshake to Mumbai and to Virginia (not CDNs - regional AWS endpoints)"
fmt='tcp %{time_connect}s  tls %{time_appconnect}s  first byte %{time_starttransfer}s\n'
run "curl -so /dev/null -w '$fmt' https://dynamodb.ap-south-1.amazonaws.com/ping"
run "curl -so /dev/null -w '$fmt' https://dynamodb.us-east-1.amazonaws.com/ping"
say "   ...and to the nearest Cloudflare PoP"
run "curl -so /dev/null -w '$fmt' https://www.cloudflare.com/cdn-cgi/trace"

say "5. HTTP/3 (needs a curl built with HTTP/3; otherwise just read alt-svc above)"
run "curl --http3 -sI https://cloudflare-quic.com/ 2>&1 | head -1 || true"

say "6. Put YOUR laptop behind Cloudflare (install cloudflared first)"
cat <<'TXT'
   terminal 1:  python3 tools/echo_server.py 8000
   terminal 2:  cloudflared tunnel --url http://localhost:8000
                -> prints https://<random-words>.trycloudflare.com
   everyone:    open that URL. Terminal 1 shows CF-Connecting-IP, CF-Ray (with the
                colo each visitor hit), CDN-Loop - and how many TCP connections
                cloudflared used for the whole room.
   limits:      200 in-flight requests, no Server-Sent Events, testing only.
TXT

say "7. In a browser"
echo "   https://radar.cloudflare.com   traffic, attacks, HTTP/3 share, BGP - by country"
echo "   https://speed.cloudflare.com   latency and jitter to your PoP"
