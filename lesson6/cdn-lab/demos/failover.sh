#!/usr/bin/env bash
# failover.sh - two origins, one dies. A preview of Session 7.
source "$(dirname "$0")/lib.sh"
origin 9250 --name primary
origin 9251 --name backup
edge 8250 --origin 127.0.0.1:9250 --backup 127.0.0.1:9251 --fail-timeout 5

say "both up: primary answers"
run "$CURL -s -D - -o /dev/null localhost:8250/slow | grep -i x-origin"
say "primary dies"
kill "${PIDS[0]}"; wait "${PIDS[0]}" 2>/dev/null
run "$CURL -s -D - -o /dev/null localhost:8250/slow | grep -i x-origin"
run "$CURL -s -D - -o /dev/null localhost:8250/slow | grep -i x-origin"
run "$CURL localhost:8250/__edge/stats | python3 -c 'import json,sys; s=json.load(sys.stdin); print({k: s[k] for k in (\"failovers\", \"origin_new_connections\")})'"
