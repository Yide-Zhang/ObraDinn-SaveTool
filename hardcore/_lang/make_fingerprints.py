#!/usr/bin/env python3
"""生成玩家侧要用的「语言包档位指纹」。

玩家侧补丁器需要在不依赖 C# 工具的前提下认出「当前语言包是哪个档位」。
最省事的办法：把每个语言、每个档位下那 4 个键的**期望文本**固化成一个 JSON，
之后只要在语言包解压后的数据里搜这串文本，就能反推档位。

（之所以能这样搜：那 4 个键的文本在整份 LangPack 里是唯一的，且原地未压缩存储，
  见 hardcore/lang_bundle.py 的说明。）

用法：
    python hardcore/_lang/make_fingerprints.py [输出路径]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numbers as NUM  # noqa: E402

ROOT = HERE
EXPORT = ROOT / "export"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else
           "patcher/data/lang_fingerprints.json")

KEYS = tuple(NUM.KEY_SHAPE)
LEVELS = (3, *NUM.LEVELS)


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


def main() -> int:
    originals: dict[str, dict[str, str]] = {}
    for p in sorted(EXPORT.glob("*.tsv")):
        d: dict[str, str] = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("\t")
            d[k] = unesc(v)
        originals[p.stem] = d

    languages: dict[str, dict[str, dict[str, str]]] = {}
    for lang, orig in originals.items():
        per_level: dict[str, dict[str, str]] = {}
        for lv in LEVELS:
            per_level[str(lv)] = {k: NUM.make_value(lang, k, lv, orig[k]) for k in KEYS}
        languages[lang] = per_level

    doc = {
        "note": "每个语言、每个档位下 4 个键的期望文本；用于从语言包反推档位",
        "levels": list(LEVELS),
        "keys": list(KEYS),
        "languages": languages,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8")

    total = sum(len(v) * len(KEYS) for v in languages.values())
    print("语言 %d 个，档位 %s" % (len(languages), ", ".join(map(str, LEVELS))))
    print("指纹条目 %d 条 -> %s  (%.1f KB)"
          % (total, OUT, OUT.stat().st_size / 1024))

    # 自检：同一语言不同档位之间必须两两不同，否则认不出来
    bad = []
    for lang, per in languages.items():
        seen: dict[tuple, int] = {}
        for lv, kv in per.items():
            sig = tuple(kv[k] for k in KEYS)
            if sig in seen:
                bad.append((lang, seen[sig], lv))
            seen[sig] = int(lv)
    if bad:
        print("[X] 有档位指纹重复，认不出: %s" % bad)
        return 1
    print("自检：所有语言的所有档位指纹两两不同 [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
