"""jwtlite.py - HS256 JSON Web Tokens with nothing but the standard library.

Session 5 asked why a JWT is base64url and not base64: '+', '/' and '=' are
not token characters. Here is the whole format: three base64url strings.
"""
import base64
import hashlib
import hmac
import json
import time


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint(secret, sub, ttl=3600, now=None):
    now = int(now or time.time())
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = b64url(json.dumps({"sub": sub, "iat": now, "exp": now + ttl},
                               separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode()
    sig = b64url(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
    return f"{header}.{claims}.{sig}"


class InvalidToken(Exception):
    pass


def verify(secret, token, now=None):
    try:
        header_b64, claims_b64, sig_b64 = token.split(".")
        header = json.loads(unb64url(header_b64))
        claims = json.loads(unb64url(claims_b64))
    except Exception:
        raise InvalidToken("malformed")
    if header.get("alg") != "HS256":          # never let the token pick the algorithm
        raise InvalidToken(f"alg {header.get('alg')!r} refused")
    expected = hmac.new(secret.encode(), f"{header_b64}.{claims_b64}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, unb64url(sig_b64)):
        raise InvalidToken("bad signature")
    if claims.get("exp", 0) < (now or time.time()):
        raise InvalidToken("expired")
    return claims
