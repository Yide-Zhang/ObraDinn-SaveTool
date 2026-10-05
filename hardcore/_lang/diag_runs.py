#!/usr/bin/env python3
"""诊断：逐语言列出「连续条目段」候选（纯 ASCII 输出）。

用法：
    python hardcore/_lang/diag_runs.py [语言...]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from hardcore import langpatch as LP   # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> int:
    want = sys.argv[1:]
    langs = sorted(p.name[5:] for p in HERE.glob("lang-*")
                   if not p.name.endswith(".manifest"))
    if want:
        langs = [c for c in langs if c in want]

    for code in langs:
        path = HERE / ("lang-" + code)
        try:
            data = LP.Bundle(path).data()
            r = LP.scan(data)
        except Exception as exc:                      # noqa: BLE001
            print("%-6s ERROR %s: %s" % (code, type(exc).__name__, exc))
            continue

        print("=" * 78)
        print("%-6s obj=%d types=%d keys_at=%s runs=%d"
              % (code, r["obj_data_size"], r["type_count"], r["key_rels"],
                 len(r["cands"])))
        # 按长度排序，看最长的几段
        for c in sorted(r["cands"], key=lambda x: -len(x["entries"]))[:4]:
            es = c["entries"]
            gaps = [b["byte_start"] - (a["byte_start"] + a["byte_size"])
                    for a, b in zip(es, es[1:])]
            print("   n=%-3d lead=%-7d tail=%-7d covers=%-5s gaps=%s"
                  % (len(es), c["lead"], c["tail"], c["covers"], gaps[:12]))
            print("       first=%s" % ([(e["byte_start"], e["byte_size"], e["type_id"])
                                        for e in es[:4]],))
            print("       last =%s" % ([(e["byte_start"], e["byte_size"], e["type_id"])
                                        for e in es[-3:]],))
    return 0


if __name__ == "__main__":
    sys.exit(main())
