#!/usr/bin/env bash
# gateway.sh - the edge as an API gateway, and why the origin must not be reachable.
source "$(dirname "$0")/lib.sh"
cd "$ROOT"
SECRET=session6
origin 9230
edge 8230 --origin 127.0.0.1:9230 --jwt-secret $SECRET
TOKEN=$(python3 "$ROOT/tools/mint_jwt.py" $SECRET alice)
OLD=$(python3 "$ROOT/tools/mint_jwt.py" $SECRET alice -10)

say "no token: refused at the edge (the origin never sees it)"
run "$CURL localhost:8230/api/orders"
say "a valid token: the edge checks it, strips it, and tells the origin who you are"
run 'echo "$TOKEN" | cut -c1-72'
run "$CURL -H \"Authorization: Bearer \$TOKEN\" localhost:8230/api/orders"
say "an expired token"
run "$CURL -H \"Authorization: Bearer \$OLD\" localhost:8230/api/orders"
say "a token that claims alg=none"
NONE="$(printf '{"alg":"none"}' | base64 | tr -d '=' ).$(printf '{"sub":"admin","exp":9999999999}' | base64 | tr -d '=')."
run "$CURL -H \"Authorization: Bearer \$NONE\" localhost:8230/api/orders"
say "a client trying to set the identity header itself"
run "$CURL -H \"Authorization: Bearer \$TOKEN\" -H 'X-User: admin' localhost:8230/api/orders"
say "header hygiene: the origin leaks its PHP version, the edge removes it"
run "curl -s -D - -o /dev/null localhost:9230/api/orders | grep -i powered"
run "curl -s -D - -o /dev/null localhost:8230/api/orders | grep -i powered || echo '(gone)'"

say "BUT: find the origin's address and skip the edge entirely"
run "curl -s -H 'X-User: admin' localhost:9230/api/orders"

say "fix: the origin only talks to clients holding the edge's certificate (mTLS)"
kill "${PIDS[0]}"; wait "${PIDS[0]}" 2>/dev/null
origin 9230 --client-ca "$ROOT/certs/ca.pem"
edge 8231 --origin 127.0.0.1:9230 --origin-tls --client-cert --jwt-secret $SECRET
run "curl -sS --cacert certs/ca.pem -H 'X-User: admin' https://localhost:9230/api/orders 2>&1 | cut -c1-90"
run "$CURL -H \"Authorization: Bearer \$TOKEN\" localhost:8231/api/orders"
