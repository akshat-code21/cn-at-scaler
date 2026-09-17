#!/usr/bin/env python3
"""05_delta.py - Railgun's idea, and the standard that brought it back.

A news home page is regenerated every minute. Most of it does not change.
Railgun (Cloudflare, 2013-2024) kept the last version on both ends of the
origin<->edge link and sent only the difference. RFC 9842 (Sep 2025) does
the same between browser and server: the version you already have becomes
the compression dictionary for the new one ("dcz" = zstd, "dcb" = brotli).

No network. We generate 61 minutes of page versions and compress each one
(a) on its own and (b) against an older version used as a dictionary.
"""
import gzip
import random
import statistics
import zlib

try:
    import zstandard
except ImportError:
    zstandard = None
try:
    import brotli
except ImportError:
    brotli = None

WORDS = ("monsoon markets cricket budget startup metro election rupee court satellite "
         "launch weather traffic festival exam results policy airline railway startup "
         "semiconductor monsoon reservoir heatwave stadium ministry index quarterly").split()


def headline(rnd):
    return " ".join(rnd.choice(WORDS) for _ in range(8)).capitalize()


def story(sid):
    rnd = random.Random(sid)
    body = " ".join(rnd.choice(WORDS) for _ in range(28))
    return (f'<article id="s{sid}"><h2><a href="/story/{sid}">{headline(rnd)}</a></h2>'
            f'<p>{body}</p><span class="views">VIEWS</span></article>\n')


def page(minute):
    """New story every 5 minutes, view counters and ticker every minute."""
    rnd = random.Random(1000 + minute)
    newest = 500 + minute // 5
    stories = [story(sid).replace("VIEWS", f"{rnd.randint(1000, 99999):,} views")
               for sid in range(newest, newest - 60, -1)]
    ticker = " | ".join(f"SENSEX {72000 + rnd.randint(-500, 500)}" for _ in range(3))
    return (f"<!doctype html><html><head><title>The Daily Packet</title></head><body>"
            f"<header>Updated 10:{minute:02d} IST <marquee>{ticker}</marquee></header>\n"
            + "".join(stories) + "<footer>(c) 2026</footer></body></html>\n").encode()


def sizes(new, old):
    out = {"raw": len(new), "gzip -6": len(gzip.compress(new, 6))}
    if brotli:
        out["br"] = len(brotli.compress(new, quality=5))
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 9, zlib.Z_DEFAULT_STRATEGY, zdict=old)
    out["deflate + dict"] = len(c.compress(new) + c.flush())
    if zstandard:
        out["zstd"] = len(zstandard.ZstdCompressor(level=3).compress(new))
        d = zstandard.ZstdCompressionDict(old, dict_type=zstandard.DICT_TYPE_RAWCONTENT)
        out["zstd + dict (dcz)"] = len(zstandard.ZstdCompressor(level=3, dict_data=d).compress(new))
    return out


def check_roundtrip(new, old):
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 9, zlib.Z_DEFAULT_STRATEGY, zdict=old)
    blob = c.compress(new) + c.flush()
    d = zlib.decompressobj(-15, zdict=old)
    assert d.decompress(blob) == new
    if zstandard:
        zd = zstandard.ZstdCompressionDict(old, dict_type=zstandard.DICT_TYPE_RAWCONTENT)
        blob = zstandard.ZstdCompressor(level=3, dict_data=zd).compress(new)
        assert zstandard.ZstdDecompressor(dict_data=zd).decompress(blob) == new


def main():
    versions = [page(m) for m in range(61)]
    print(f"page size ~{statistics.mean(map(len, versions)) / 1024:.1f} KB "
          f"(deflate can only see the last 32 KB of a dictionary)\n")
    for age in (1, 10, 60):
        pairs = [(versions[m], versions[m - age]) for m in range(age, 61)]
        check_roundtrip(*pairs[0])
        rows = [sizes(n, o) for n, o in pairs]
        keys = rows[0].keys()
        means = {k: statistics.mean(r[k] for r in rows) for k in keys}
        label = f"dictionary = the page from {age} min ago"
        print(label)
        for k in keys:
            print(f"   {k:<20} {means[k]:>8,.0f} B   {means[k] / means['raw']:6.1%} of raw")
        print()
    print("A one-minute-old copy turns ~24 KB into a few hundred bytes - about 10x\n"
          "smaller than gzip. An hour-old copy is still ~3x better than gzip. The\n"
          "dictionary has to be recent and has to be the SAME on both ends, which is\n"
          "why Railgun kept versions on both sides and RFC 9842 names it by SHA-256.")


if __name__ == "__main__":
    main()
