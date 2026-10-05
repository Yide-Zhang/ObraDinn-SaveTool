#!/usr/bin/env python3
"""查看语言包里「三」数词出现位置的上下文 / 完整文案。

用法：
    python hardcore/_lang/inspect.py ctx  <key> [输出文件]
    python hardcore/_lang/inspect.py full <key> [输出文件]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path("hardcore/_lang/export")

WORDS = {
    "ar": ["ثلاثة", "ثلاث"], "de": ["drei"], "en": ["three"], "es": ["tres"],
    "fr": ["trois"], "it": ["tre"], "ja": [], "ko": [], "pl": ["trzech", "trzy"],
    "pt": ["três"], "ru": ["трёх", "трех", "троих", "три"], "uk": ["три", "трьох"],
    "zh-s": ["三"], "zh-t": ["三"],
}
NUM3 = re.compile(r"(?<![0-9])3(?![0-9])")


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


def load() -> dict[str, dict[str, str]]:
    data: dict[str, dict[str, str]] = {}
    for p in sorted(ROOT.glob("*.tsv")):
        d: dict[str, str] = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("\t")
            d[k] = unesc(v)
        data[p.stem] = d
    return data


def contexts(v: str, lang: str) -> list[str]:
    spans: list[tuple[int, int]] = []
    for m in NUM3.finditer(v):
        spans.append((m.start(), m.end()))
    for w in WORDS.get(lang, []):
        if lang.startswith("zh"):
            for m in re.finditer(re.escape(w), v):
                spans.append((m.start(), m.end()))
        else:
            for m in re.finditer(r"\b" + re.escape(w) + r"\b", v, re.IGNORECASE):
                spans.append((m.start(), m.end()))
    out = []
    for a, b in spans:
        lo = max(0, a - 70)
        hi = min(len(v), b + 70)
        out.append(("..." if lo else "") + v[lo:hi].replace("\n", "\\n")
                   + ("..." if hi < len(v) else ""))
    return out


def main() -> int:
    mode = sys.argv[1]
    key = sys.argv[2]
    outpath = Path(sys.argv[3] if len(sys.argv) > 3 else "hardcore/_dump/inspect.txt")
    data = load()

    lines: list[str] = []
    for lang in sorted(data):
        v = data[lang].get(key)
        lines.append("=" * 88)
        lines.append("[%s] %s" % (lang, key))
        lines.append("-" * 88)
        if v is None:
            lines.append("  (缺失)")
        elif mode == "full":
            lines.append(v.replace("\n", "\\n\n"))
        else:
            ctx = contexts(v, lang)
            lines.append("  命中 %d 处:" % len(ctx) if ctx else "  (未命中)")
            for c in ctx:
                lines.append("    " + c)
        lines.append("")

    outpath.parent.mkdir(parents=True, exist_ok=True)
    outpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("%s -> %s" % (key, outpath))
    return 0


if __name__ == "__main__":
    sys.exit(main())
