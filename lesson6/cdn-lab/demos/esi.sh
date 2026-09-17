#!/usr/bin/env bash
# esi.sh - one cached shell, two private holes, filled at the edge.
source "$(dirname "$0")/lib.sh"
origin 9210
edge 8210 --origin 127.0.0.1:9210 --esi --cache-prefix /page/

say "what the origin sends: a shell anyone may cache, with holes"
run "$CURL localhost:9210/page/home | head -c 190; echo"
run "curl -s -D - -o /dev/null localhost:9210/page/home | grep -iE 'cache-control|surrogate'"

curl -s localhost:9210/__origin/reset
say "what two different users get from the edge"
run "$CURL -H 'Cookie: user=asha' localhost:8210/page/home | head -c 190; echo"
run "$CURL -H 'Cookie: user=ravi' localhost:8210/page/home | head -c 190; echo"
run hdrs -H "'Cookie: user=ravi'" localhost:8210/page/home

run "$CURL -H 'Cookie: user=meera' localhost:8210/page/home >/dev/null"
say "four page views: who did the work?"
run "curl -s localhost:9210/__origin/stats | python3 -c 'import json,sys; s=json.load(sys.stdin); print(s[\"by_path\"], s[\"bytes_out\"], \"bytes\")'"
