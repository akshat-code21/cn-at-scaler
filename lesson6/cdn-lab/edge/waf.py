"""waf.py - a toy web application firewall.

A WAF is a denylist applied to text. Everything interesting about it is in
two questions: *which* text (how much decoding happens first), and *which*
list (how many ways there are to write the same attack).
"""
import re
from urllib.parse import unquote_plus

RULES = [
    ("sqli-union",     re.compile(r"\bunion\b[\s\S]*\bselect\b", re.I)),
    ("sqli-tautology", re.compile(r"'\s*or\s+\d+\s*=\s*\d+", re.I)),
    ("sqli-stacked",   re.compile(r";\s*(drop|delete|insert|update)\b", re.I)),
    ("path-traversal", re.compile(r"\.\./")),
    ("xss-script",     re.compile(r"<\s*script", re.I)),
]

SQL_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def normalise(text, level):
    """raw    - look at the bytes as they arrived (still %-encoded)
       decode - URL-decode once, the way every real WAF does at minimum
       full   - decode until stable, strip SQL comments, collapse whitespace"""
    if level == "raw":
        return text
    if level == "decode":
        return unquote_plus(text)
    prev = None
    while prev != text:                       # %2527 -> %27 -> '
        prev, text = text, unquote_plus(text)
    text = SQL_COMMENT.sub(" ", text)
    return re.sub(r"\s+", " ", text)


def inspect(target, body, level):
    """Return the id of the first rule that matches, or None."""
    if level == "off":
        return None
    for chunk in (target, body.decode("latin-1") if body else ""):
        seen = normalise(chunk, level)
        for rule_id, rx in RULES:
            if rx.search(seen):
                return rule_id
    return None
