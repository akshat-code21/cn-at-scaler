// test_workers.mjs - run both Workers locally in workerd (via Miniflare)
// against cdn-lab's origin. Usage: node test_workers.mjs  (origin on :9301)
import { Miniflare } from "miniflare";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const ORIGIN = "http://127.0.0.1:9301";
const mint = (sub, ttl) => execFileSync("python3", ["../tools/mint_jwt.py", "session6", sub, String(ttl)]).toString().trim();

const esi = new Miniflare({
  modules: true, compatibilityDate: "2026-08-01",
  script: readFileSync("worker-esi/src/index.js", "utf8"), bindings: { ORIGIN, EDGE_SECRET: "edge-only" },
});
const gw = new Miniflare({
  modules: true, compatibilityDate: "2026-08-01",
  script: readFileSync("worker-gateway/src/index.js", "utf8"),
  bindings: { PRIMARY: "http://127.0.0.1:9399", BACKUP: ORIGIN, JWT_SECRET: "session6", EDGE_SECRET: "edge-only" },
});

const show = async (label, p) => {
  const r = await p;
  const t = await r.text();
  console.log(`${label}\n  ${r.status} ${[...r.headers].filter(([k]) => /^x-|cache-control|powered|strict/i.test(k)).map(([k, v]) => `${k}: ${v}`).join(" | ")}\n  ${t.slice(0, 150).replace(/\n/g, " ")}`);
};

await show("ESI, user asha", esi.dispatchFetch("http://news.example/page/home", { headers: { Cookie: "user=asha" } }));
const a = await (await esi.dispatchFetch("http://news.example/page/home", { headers: { Cookie: "user=asha" } })).text();
const b = await (await fetch(`${ORIGIN}/page/home-full`, { headers: { Cookie: "user=asha", "X-Edge-Auth": "edge-only" } })).text();
console.log(`  worker page == origin-assembled page: ${a === b} (${a.length} B)`);
await show("gateway, no token", gw.dispatchFetch("http://api.example/api/orders"));
await show("gateway, valid token (primary is down -> backup)", gw.dispatchFetch("http://api.example/api/orders", { headers: { Authorization: `Bearer ${mint("alice", 600)}`, "X-User": "admin" } }));
await show("gateway, expired token", gw.dispatchFetch("http://api.example/api/orders", { headers: { Authorization: `Bearer ${mint("alice", -5)}` } }));
await show("direct to origin without the edge secret", fetch(`${ORIGIN}/api/orders`, { headers: { "X-User": "admin" } }));
await esi.dispose(); await gw.dispose();
