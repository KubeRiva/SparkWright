"""One glob matcher for every SparkWright rule (D009, S2.6 "Globs").

Python `fnmatch`, where `*` and `**` match any characters including `/`, plus two rules people expect:
`/**/` also matches a single `/` (so `tests/**/*` matches `tests/a.py`) and a leading `**/` also matches
nothing (so `**/test_*.py` matches `test_a.py` at the root). `dir/**` also matches `dir` itself.
"""
from __future__ import annotations

import fnmatch


def variants(glob: str) -> set[str]:
    out = {glob}
    changed = True
    while changed:
        changed = False
        for g in list(out):
            for v in ([g.replace("/**/", "/", 1)] if "/**/" in g else []) + ([g[3:]] if g.startswith("**/") else []):
                if v not in out:
                    out.add(v)
                    changed = True
    return out


def match(path: str, globs) -> bool:
    for g in globs or []:
        g = str(g)
        if g.endswith("/**") and (path == g[:-3] or path.startswith(g[:-2])):
            return True
        if any(fnmatch.fnmatch(path, v) for v in variants(g)):
            return True
    return False
