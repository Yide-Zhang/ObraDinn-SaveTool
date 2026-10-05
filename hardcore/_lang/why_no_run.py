#!/usr/bin/env python3
"""为什么连不成一条完整的对象表？逐字节试读，看断在哪里。

用法：
    python hardcore/_lang/why_no_run.py ar
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from hardcore import langpatch as LP   # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> int:
    code = sys.argv[1] if len(sys.argv) > 1 else "ar"
    path = HERE / ("lang-" + code)
    b = LP.Bundle(path)
    data = b.data()
    r = LP.scan(data)
    meta_size = r["meta_size"]
    meta = data[:meta_size]
    obj = r["obj_data_size"]
    tc = r["type_count"]

    print("%s: meta=%d obj=%d types=%d keys_at=%s" % (code, meta_size, obj, tc,
                                                      r["key_rels"]))
    print()
    print("候选段（按长度排序，前 8）：")
    for c in sorted(r["cands"], key=lambda x: -len(x["entries"]))[:8]:
        print("   start=%-6d n=%-2d lead=%-8d tail=%-8d covers=%s"
              % (c["count_off"], len(c["entries"]), c["lead"], c["tail"], c["covers"]))
        for e in c["entries"][:6]:
            print("        @%-6d pid=%-22d start=%-8d size=%-8d tid=%d"
                  % (e["entry_off"], e["path_id"], e["byte_start"],
                     e["byte_size"], e["type_id"]))

    print()
    print("元数据尾部 [%d..%d) 逐字节试读（只打印能读出合法条目的位置）：" % (meta_size - 260, meta_size))
    lo = meta_size - 260
    for q in range(lo, meta_size - 19):
        e = LP._entry_at(meta, q, tc, obj)          # noqa: SLF001
        marker = "  <== 连续" if (q > lo and LP._entry_at(meta, q - 20, tc, obj)  # noqa: SLF001
                                   and e and
                                   0 <= e["byte_start"] - (LP._entry_at(meta, q - 20, tc, obj)["byte_start"]  # noqa: SLF001
                                                           + LP._entry_at(meta, q - 20, tc, obj)["byte_size"]) <= 4) else ""  # noqa: SLF001
        if e:
            print("   @%-6d pid=%-22d start=%-8d size=%-8d tid=%d%s"
                  % (q, e["path_id"], e["byte_start"], e["byte_size"],
                     e["type_id"], marker))
        else:
            # 打印被判为非法的原因
            pid, = struct.unpack_from("<q", meta, q)
            bs, = struct.unpack_from("<I", meta, q + 8)
            sz, = struct.unpack_from("<I", meta, q + 12)
            tid, = struct.unpack_from("<i", meta, q + 16)
            why = []
            if pid <= 0:
                why.append("pathID<=0")
            if not 0 <= bs:
                why.append("start<0")
            if sz == 0:
                why.append("size=0")
            if bs + sz > obj:
                why.append("start+size>%d" % obj)
            if not 0 <= tid < tc:
                why.append("tid=%d 超出类型数 %d" % (tid, tc))
            if why:
                print("   @%-6d pid=%-22d start=%-8d size=%-8d tid=%-4d  非法: %s"
                      % (q, pid, bs, sz, tid, ",".join(why)))

    print()
    print("尾部原始 hex：")
    for o in range(lo, meta_size, 16):
        chunk = meta[o:o + 16]
        print("   %-6d %s  %s" % (o, " ".join("%02x" % c for c in chunk),
                                  "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
