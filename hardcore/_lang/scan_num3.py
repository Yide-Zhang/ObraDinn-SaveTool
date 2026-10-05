#!/usr/bin/env python3
"""扫描语言包里所有与「批次人数」相关的文案。

判定依据：
  1) key 落在 fate / face / book / help / tut 家族里，且值里出现阿拉伯数字 3
  2) 或者值里出现各语言的「三」数词（人工维护的小词表）

输出写到文件（控制台是 GBK，阿拉伯语/特殊字符会编不出来）。

用法：
    python hardcore/_lang/scan_num3.py [导出目录] [输出文件] [key过滤正则]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "hardcore/_lang/export")
out = Path(sys.argv[2] if len(sys.argv) > 2 else "hardcore/_dump/scan_num3.txt")

# 各语言的「三」——用于兜底发现漏掉的键
THREE_WORDS = {
    "ar": ["ثلاثة", "ثلاث"],
    "de": ["drei", "Drei"],
    "en": ["three", "Three"],
    "es": ["tres", "Tres"],
    "fr": ["trois", "Trois"],
    "it": ["tre", "Tre"],
    "ja": ["3"],
    "ko": ["3"],
    "pl": ["trzech", "trzy", "trójk"],
    "pt": ["três", "Três"],
    "ru": ["трёх", "трех", "троих", "три"],
    "uk": ["три", "трьох"],
    "zh-s": ["三"],
    "zh-t": ["三"],
}

KEY_RE = re.compile(
    sys.argv[3] if len(sys.argv) > 3
    else r"fate|face|book|help|tut|correct|deck|journal|welldone|num|count|group|set",
    re.IGNORECASE)
NUM3_RE = re.compile(r"(?<![0-9])3(?![0-9])")

def unesc(s: str) -> str:
    """反转义 TSV 里的 \\n \\t \\r \\\\（否则 \b 词边界会被字面 \\n 里的 n 破坏）。"""
    out: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n in "ntr":
                out.append({"n": "\n", "t": "\t", "r": "\r"}[n])
                i += 2
                continue
            if n == "\\":
                out.append("\\")
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


data: dict[str, dict[str, str]] = {}
for p in sorted(root.glob("*.tsv")):
    d: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("\t")
        d[k] = unesc(v)
    data[p.stem] = d

langs = sorted(data)
all_keys = list(data[langs[0]].keys())

hits: list[tuple[str, list[str]]] = []
for k in all_keys:
    if not KEY_RE.search(k):
        continue
    reasons: list[str] = []
    for lg in langs:
        v = data[lg].get(k, "")
        if NUM3_RE.search(v):
            reasons.append(lg + ":数字3")
            continue
        for w in THREE_WORDS.get(lg, []):
            # 中日韩没有词边界（汉字本身就是 word 字符），只能用子串
            hit = (w in v) if lg.startswith("zh") else bool(
                re.search(r"\b" + re.escape(w) + r"\b", v, re.IGNORECASE))
            if hit:
                reasons.append(lg + ":" + w)
                break
    if reasons:
        hits.append((k, sorted(set(reasons))))

lines: list[str] = []
lines.append("命中 %d 个键（key 家族 + 值含「三」）" % len(hits))
lines.append("=" * 92)
for k, why in hits:
    lines.append("")
    lines.append("KEY: %s        [%s]" % (k, ",".join(why)))
    for lg in langs:
        v = data[lg].get(k, "").replace("\n", "\\\\n")
        if len(v) > 100:
            v = v[:100] + "..."
        lines.append("   %-6s %s" % (lg, v))

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(lines) + "\n", encoding="utf-8")

print("命中 %d 个键 -> %s" % (len(hits), out))
for k, _ in hits:
    print("  " + k)
