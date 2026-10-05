#!/usr/bin/env python3
"""校验：对全部 ar 文案做 NFKC -> reshape 能否逐字还原原串。

能还原 => 就可以放心地「规范化后替换、再整体 reshape 写回」。
不能还原 => 阿拉伯语必须另想办法（或交给母语者手工处理）。
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

try:
    import arabic_reshaper
except ImportError:
    print("需要 arabic-reshaper：pip install arabic-reshaper")
    sys.exit(2)

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


total = 0
bad: list[tuple[str, str, str]] = []
for line in (ROOT / "ar.tsv").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#"):
        continue
    k, _, v = line.partition("\t")
    v = unesc(v)
    total += 1
    got = arabic_reshaper.reshape(unicodedata.normalize("NFKC", v))
    if got != v:
        bad.append((k, v, got))

print("ar 共 %d 条，reshape 还原失败 %d 条" % (total, len(bad)))

lines = ["ar 共 %d 条，reshape 还原失败 %d 条" % (total, len(bad)), ""]
for k, v, g in bad[:40]:
    lines.append("KEY: " + k)
    lines.append("  orig cps: %s" % " ".join("U+%04X" % ord(c) for c in v))
    lines.append("  got  cps: %s" % " ".join("U+%04X" % ord(c) for c in g))
    lines.append("")

out = Path("hardcore/_dump/ar_reshaping.txt")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("-> " + str(out))
sys.exit(0 if not bad else 1)
