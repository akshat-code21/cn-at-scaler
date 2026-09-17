#!/usr/bin/env bash
# cache.sh - MISS, HIT, REVALIDATED, DYNAMIC, BYPASS, purge, STALE - one of each.
source "$(dirname "$0")/lib.sh"
origin 9200 --css-ttl 3
edge 8200 --origin 127.0.0.1:9200 --stale-if-error 300

say "1. a static file: the first visitor pays, everyone after is free"
run hdrs localhost:8200/static/app.css
run hdrs localhost:8200/static/app.css

say "2. wait past max-age=3: the edge asks the origin 'If-None-Match?' and gets a 304"
sleep 3.2
run hdrs localhost:8200/static/app.css

say "3. HTML is not on the default list of cacheable extensions"
run hdrs localhost:8200/page/home

say "4. .png is on the list, but the origin said private"
run hdrs -H "'Cookie: user=jeet'" localhost:8200/me/avatar.png

say "5. deploy a new build: the edge keeps serving the old site.js (max-age=3600) until purged"
run "$CURL localhost:8200/static/site.js | head -1"
run "$CURL localhost:9200/__origin/bump"
run "$CURL localhost:8200/static/site.js | head -1"
run "$CURL -X POST 'localhost:8200/__edge/purge?path=/static/site.js'"; echo
run "$CURL localhost:8200/static/site.js | head -1"

say "6. the origin dies. app.css has expired, but stale-if-error keeps it alive"
kill "${PIDS[0]}"; sleep 3.2
run hdrs localhost:8200/static/app.css
say "   ...and the page that was never cached is simply gone"
run hdrs localhost:8200/page/home
