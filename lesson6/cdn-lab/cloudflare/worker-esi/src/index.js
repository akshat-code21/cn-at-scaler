// worker-esi - Edge Side Includes on Cloudflare, which has no built-in ESI.
//
// Akamai and Oracle wrote ESI down in 2001 (W3C Note). Varnish supports three
// of its tags, Fastly supports three, Cloudflare supports none - but forty
// lines of Worker do it.
//
//   origin sends:   <header><esi:include src="/fragment/user"/> ...</header>
//                   Cache-Control: public, s-maxage=300
//                   Surrogate-Control: content="ESI/1.0"
//   visitor gets:   the shell from Cloudflare's cache, holes filled per visitor

const ESI_TAG = /<esi:include\s+src="([^"]+)"\s*\/>/g;
const proof = (env) => (env.EDGE_SECRET ? { "X-Edge-Auth": env.EDGE_SECRET } : {});

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const upstream = new URL(url.pathname + url.search, env.ORIGIN);

    // 1. The shell is the same for everyone: send no cookies, cache it at the edge.
    const shell = await fetch(upstream, {
      headers: { Accept: "text/html", ...proof(env) },
      cf: { cacheEverything: true, cacheTtl: 300 },
    });
    if (!(shell.headers.get("Surrogate-Control") || "").includes("ESI/1.0")) {
      return shell; // not an ESI page - pass it through untouched
    }

    // 2. The holes are personal: fetch them with this visitor's cookie, all at once
    //    (the same choice nginx's SSI module makes).
    const html = await shell.text();
    const cookie = request.headers.get("Cookie") || "";
    const srcs = [...new Set([...html.matchAll(ESI_TAG)].map((m) => m[1]))];
    const parts = Object.fromEntries(
      await Promise.all(
        srcs.map(async (src) => {
          try {
            const r = await fetch(new URL(src, env.ORIGIN), { headers: { Cookie: cookie, ...proof(env) } });
            return [src, r.ok ? await r.text() : ""];
          } catch {
            return [src, ""]; // a broken fragment must not break the page
          }
        }),
      ),
    );

    // 3. Fill the holes. Not with HTMLRewriter, although that is the obvious tool:
    //    HTML has no self-closing custom elements, so an HTML parser reads
    //    <esi:include .../> as an OPEN tag whose content runs to </header>.
    //    replace() then swallows the rest of the header. ESI is XML-ish markup
    //    living inside HTML, and the two grammars disagree about where it ends -
    //    Session 2's framing question again. The ESI tag is regular; use a regex.
    const page = html.replace(ESI_TAG, (_, src) => parts[src] ?? "");

    const headers = new Headers(shell.headers);
    headers.delete("Surrogate-Control");
    headers.delete("Content-Length");
    headers.delete("X-Powered-By");
    headers.set("Cache-Control", "private, no-store"); // the assembled page is personal
    headers.set("X-Shell-Cache", shell.headers.get("CF-Cache-Status") || "n/a");
    headers.set("X-ESI-Fragments", String(srcs.length));
    return new Response(page, { status: shell.status, headers });
  },
};
