#!/usr/bin/env bash
# setup.sh - make a private CA and three certificates. Nothing leaves the machine.
#   certs/edge.pem          the edge's server certificate (what browsers would see)
#   certs/origin.pem        the origin's server certificate
#   certs/edge-client.pem   the edge's *client* certificate, for mTLS to the origin
set -euo pipefail
cd "$(dirname "$0")/certs"
command -v openssl >/dev/null || { echo "need openssl"; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 11), "need Python 3.11+"'

openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 365 \
  -keyout ca.key -out ca.pem -subj "/CN=cdn-lab private CA" 2>/dev/null

issue() {  # name  extendedKeyUsage
  openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
    -keyout "$1.key" -out "$1.csr" -subj "/CN=localhost" 2>/dev/null
  printf "subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=%s\n" "$2" > "$1.ext"
  openssl x509 -req -in "$1.csr" -CA ca.pem -CAkey ca.key -CAcreateserial -days 365 \
    -extfile "$1.ext" -out "$1.pem" 2>/dev/null
  rm -f "$1.csr" "$1.ext"
}
issue edge serverAuth
issue origin serverAuth
issue edge-client clientAuth
ls -1 *.pem | sed 's/^/  certs\//'
python3 -c 'import zstandard' 2>/dev/null && echo "  zstandard found (bench 05 will also test dcz)" \
  || echo "  optional: pip install zstandard   (bench 05 then also tests RFC 9842 dcz)"
echo "ok - now ./run_all.sh"
