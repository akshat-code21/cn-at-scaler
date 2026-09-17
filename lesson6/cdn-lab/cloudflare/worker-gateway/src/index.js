// worker-gateway - the edge as an API gateway.
//   1. rate limit per client IP       (Workers Rate Limiting binding)
//   2. verify an HS256 JWT on /api/*  (WebCrypto; the origin never sees tokens)
//   3. tell the origin who the user is, and prove the request came from us
//   4. primary origin, then backup    (a preview of Session 7)
//   5. scrub response headers

const enc = new TextEncoder();
const dec = new TextDecoder();

function b64urlBytes(s) {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

async function verifyJwt(token, secret) {
  const [h, p, sig] = token.split(".");
  if (!sig) throw new Error("malformed");
  const header = JSON.parse(dec.decode(b64urlBytes(h)));
  if (header.alg !== "HS256") throw new Error(`alg ${header.alg} refused`); // never trust the token's choice
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("HMAC", key, b64urlBytes(sig), enc.encode(`${h}.${p}`));
  if (!ok) throw new Error("bad signature");
  const claims = JSON.parse(dec.decode(b64urlBytes(p)));
  if ((claims.exp ?? 0) < Date.now() / 1000) throw new Error("expired");
  return claims;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (env.LIMITER) {
      const ip = request.headers.get("CF-Connecting-IP") || "unknown";
      const { success } = await env.LIMITER.limit({ key: ip }); // counted per Cloudflare location
      if (!success) return new Response("rate limited at the edge\n", { status: 429, headers: { "Retry-After": "10" } });
    }

    const headers = new Headers(request.headers);
    headers.delete("X-User"); // identity comes from us, never from the client
    if (url.pathname.startsWith("/api/")) {
      try {
        const auth = request.headers.get("Authorization") || "";
        if (!auth.startsWith("Bearer ")) throw new Error("missing bearer token");
        const claims = await verifyJwt(auth.slice(7), env.JWT_SECRET);
        headers.set("X-User", claims.sub);
        headers.delete("Authorization");
      } catch (e) {
        return new Response(`edge: ${e.message}\n`, {
          status: 401,
          headers: { "WWW-Authenticate": `Bearer error="${e.message}"` },
        });
      }
    }
    headers.set("X-Edge-Auth", env.EDGE_SECRET); // origin refuses requests without it

    const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();
    let resp;
    for (const base of [env.PRIMARY, env.BACKUP].filter(Boolean)) {
      try {
        resp = await fetch(new URL(url.pathname + url.search, base), {
          method: request.method, headers, body, redirect: "manual",
        });
        if (resp.status < 500) break;
      } catch {
        resp = undefined;
      }
    }
    if (!resp) return new Response("all origins are down\n", { status: 502 });

    const out = new Response(resp.body, resp);
    out.headers.delete("X-Powered-By");
    out.headers.set("Strict-Transport-Security", "max-age=31536000");
    return out;
  },
};
