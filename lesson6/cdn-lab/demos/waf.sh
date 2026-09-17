#!/usr/bin/env bash
# waf.sh - a WAF is a denylist of spellings. The bug lives in the origin.
source "$(dirname "$0")/lib.sh"
origin 9220
edge 8220 --origin 127.0.0.1:9220 --waf decode
edge 8221 --origin 127.0.0.1:9220 --waf full
q() { curl -s -G -H 'Host: news.example' "localhost:$1/search" --data-urlencode "q=$2"; }

say "a normal search"
run q 8220 "'cable'"
say "the textbook injection: blocked at the edge"
run q 8220 "\"' OR 1=1 --\""
say "same attack, SQL comments instead of spaces: the regex never matches"
run q 8220 "\"'/**/OR/**/1=1--\""
say "a WAF that normalises (strips comments) catches that one..."
run q 8221 "\"'/**/OR/**/1=1--\""
say "...but not this: no OR, no UNION, no digits. Just close the quote and comment out the rest"
run q 8221 "\"' --\""
say "the actual fix is in the origin: bind parameters"
kill "${PIDS[0]}"; wait "${PIDS[0]}" 2>/dev/null
origin 9220 --safe
run q 8221 "\"' --\""
run q 8220 "\"'/**/OR/**/1=1--\""
