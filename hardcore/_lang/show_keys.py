#!/usr/bin/env python3
"""按 key 汇总各语言的文案，便于横向对照。

用法：
    python hardcore/_lang/show_keys.py [导出目录] [key ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "hardcore/_lang/export")
keys = sys.argv[2:] or [
    "welldone",
    "welldone_3_first", "welldone_3_more",
    "welldone_2_first", "welldone_2_more",
    "welldone_solvable", "welldone_last", "welldone_shipdone",
    "help_faceclear_fates_may", "help_faceclear_fates0", "help_faceclear_fates1",
]

data: dict[str, dict[str, str]] = {}
for p in sorted(root.glob("*.tsv")):
    d: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("\t")
        d[k] = v
    data[p.stem] = d

print("语言包: %s   （各 %d 条）" % (", ".join(sorted(data)),
                                    len(next(iter(data.values())))))
print()

for k in keys:
    print("=" * 84)
    print("KEY: " + k)
    print("-" * 84)
    for lang in sorted(data):
        v = data[lang].get(k)
        print("  %-6s %s" % (lang, "(缺失)" if v is None else v))
    print()
