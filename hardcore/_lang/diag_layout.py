#!/usr/bin/env python3
"""逐语言诊断对象表扫描结果（只输出 ASCII，免得被控制台编码吃掉）。

用法：
    python hardcore/_lang/diag_layout.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from hardcore import langpatch as LP   # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> int:
    langs = sorted(p.name[5:] for p in HERE.glob("lang-*")
                   if not p.name.endswith(".manifest"))
    for code in langs:
        path = HERE / ("lang-" + code)
        try:
            b = LP.Bundle(path)
            data = b.data()
            r = LP.scan(data)
        except Exception as exc:                      # noqa: BLE001
            print("%-6s ERROR %s: %s" % (code, type(exc).__name__, exc))
            continue

        print("%-6s meta=%d file=%d data_off=%d obj=%d types=%d keys_at=%s cands=%d"
              % (code, r["meta_size"], r["file_size"], r["data_offset"],
                 r["obj_data_size"], r["type_count"], r["key_rels"], len(r["cands"])))
        shown = 0
        for c in r["cands"]:
            tag = []
            if c["covers"]:
                tag.append("COVERS")
            if c["gap_ok"]:
                tag.append("gapOK")
            if c["sorted_ok"]:
                tag.append("sortedOK")
            if 0 <= c["lead"] <= LP.MAX_LEAD and 0 <= c["tail"] <= LP.MAX_TAIL:
                tag.append("rangeOK")
            starts = [(e["byte_start"], e["byte_size"], e["type_id"])
                      for e in c["entries"]]
            print("   @%-6d n=%-2d lead=%-7d tail=%-7d gaps=%s  %s"
                  % (c["count_off"], len(c["entries"]), c["lead"], c["tail"],
                     c["gaps"][:6], " ".join(tag)))
            print("      entries=%s" % (starts[:6],))
            shown += 1
            if shown >= 5:
                print("      ... 共 %d 张" % len(r["cands"]))
                break
        # 再用真实门槛走一遍
        try:
            lay = LP.parse_layout(data)
            print("   -> parse_layout OK: table@%d n=%d lead=%d tail=%d"
                  % (lay["count_off"], len(lay["entries"]), lay["lead"], lay["tail"]))
        except Exception as exc:                      # noqa: BLE001
            print("   -> parse_layout REJECTED")
            for line in str(exc).splitlines():
                print("      " + line)
        # 原始字节：对象表附近（元数据尾部）。ASCII-only，免得被编码吃掉
        meta = data[:r["meta_size"]]
        lo = max(0, r["meta_size"] - 180)
        print("   meta tail [%d..%d) hex:" % (lo, r["meta_size"]))
        for o in range(lo, r["meta_size"], 16):
            chunk = meta[o:o + 16]
            print("      %-6d %s  %s"
                  % (o, " ".join("%02x" % c for c in chunk),
                     "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
