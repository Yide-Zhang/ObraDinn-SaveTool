#!/usr/bin/env python3
"""检查各语言「三」那个词的实际码位（判断是否用了阿拉伯语表现形）。"""
from __future__ import annotations

import unicodedata
from pathlib import Path

ROOT = Path("hardcore/_lang/export")


def unesc(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] in "ntr\\":
            out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}[s[i + 1]])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def get(lang: str, key: str) -> str:
    for line in (ROOT / (lang + ".tsv")).read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "\t"):
            return unesc(line.split("\t", 1)[1])
    return ""


lines: list[str] = []
for lang in ("ar", "ru", "pl", "ja", "ko", "zh-s"):
    for key in ("welldone_3_first", "help_faceclear_fates0", "help_faceclear_fates1"):
        v = get(lang, key)
        lines.append("[%s] %s" % (lang, key))
        lines.append("  repr : %r" % v)
        lines.append("  cps  : %s" % " ".join("U+%04X" % ord(c) for c in v))
        lines.append("  nfkc : %r" % unicodedata.normalize("NFKC", v))
        lines.append("")

out = Path("hardcore/_dump/codepoints.txt")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("-> " + str(out))
