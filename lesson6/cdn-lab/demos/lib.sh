# demos/lib.sh - shared helpers: start servers, print commands like a terminal.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done; wait 2>/dev/null; }
trap cleanup EXIT

wait_port() { for _ in $(seq 100); do (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && return; sleep 0.05; done; echo "port $1 never opened"; exit 1; }
origin() { local port=$1; shift; python3 "$ROOT/origin/origin.py" --port "$port" "$@" >/dev/null 2>&1 & PIDS+=($!); wait_port "$port"; }
edge()   { local port=$1; shift; python3 "$ROOT/edge/edge.py"     --port "$port" "$@" >/dev/null 2>&1 & PIDS+=($!); wait_port "$port"; }
say()    { printf '\n\033[1;33m# %s\033[0m\n' "$*"; }
run()    { printf '\033[36m$ %s\033[0m\n' "$*"; eval "$@"; }
# show only the headers that matter today
hdrs()   { curl -s -D - -o /dev/null -H 'Host: news.example' "$@" | tr -d '\r' \
             | grep -iE '^(HTTP/|x-cache|age|cache-control|etag|x-origin|x-edge-block|server-timing|www-authenticate|x-powered-by|strict-transport|x-esi)' ; }
CURL="curl -s -H Host:news.example"
