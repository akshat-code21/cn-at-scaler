#!/usr/bin/env python3
"""mint_jwt.py SECRET SUBJECT [TTL_SECONDS] - print an HS256 JWT."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "edge"))
import jwtlite  # noqa: E402

if len(sys.argv) < 3:
    sys.exit(__doc__)
print(jwtlite.mint(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 3600))
