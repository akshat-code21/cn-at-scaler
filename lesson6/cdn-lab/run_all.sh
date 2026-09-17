#!/usr/bin/env bash
# run_all.sh - reproduce every number on every slide. ~90 s, no network.
set -euo pipefail
cd "$(dirname "$0")"
[ -f certs/ca.pem ] || ./setup.sh
for b in bench/0*.py; do
  printf '\n\033[1;32m==== %s\033[0m\n' "$b"
  python3 "$b"
done
for d in cache esi waf gateway poison failover; do
  printf '\n\033[1;32m==== demos/%s.sh\033[0m\n' "$d"
  bash "demos/$d.sh"
done
