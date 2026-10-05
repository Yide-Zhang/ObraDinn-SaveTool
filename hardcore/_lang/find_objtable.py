#!/usr/bin/env python3
"""在元数据区里暴力搜「对象表」。

不解析 TypeTree（跳过长度不好猜），直接用数值自洽找表：
某个位置 q 处的 u32 恰好是条目数 n，随后 n 条 20 字节的
(pathID, byteStart, byteSize, typeID) 全部合法，就算候选。

合法性：byteStart >= 0、0 < byteSize、byteStart+byteSize <= file_size、
        0 <= typeID < 类型数、pathID > 0、byteSize 不为 0。

用法：
    python hardcore/_lang/find_objtable.py hardcore/_lang/lang-en
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from hardcore.lang_bundle import Bundle  # noqa: E402

KEYS = (b"welldone_3_first", b"welldone_3_more",
        b"help_faceclear_fates0", b"help_faceclear_fates1")


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "hardcore/_lang/lang-en")
    data = Bundle(path).data()

    meta_size, = struct.unpack_from(">I", data, 0)
    file_size, = struct.unpack_from(">I", data, 4)
    data_offset, = struct.unpack_from(">I", data, 12)
    meta = data[:meta_size]

    print("metadata_size=%d file_size=%d data_offset=%d" % (meta_size, file_size, data_offset))
    print()

    hits = []
    for q in range(0, len(meta) - 24):
        n, = struct.unpack_from("<I", meta, q)
        if not 1 <= n <= 16:
            continue
        p = q + 4
        entries = []
        ok = True
        for _ in range(n):
            if p + 20 > len(meta):
                ok = False
                break
            pid, = struct.unpack_from("<q", meta, p)
            bs, = struct.unpack_from("<I", meta, p + 8)
            sz, = struct.unpack_from("<I", meta, p + 12)
            tid, = struct.unpack_from("<i", meta, p + 16)
            if not (pid > 0 and 0 <= bs and 0 < sz
                    and bs + sz <= file_size and 0 <= tid < 8):
                ok = False
                break
            entries.append((p, pid, bs, sz, tid))
            p += 20
        if not ok or not entries:
            continue
        ends = [bs + sz for _o, _p, bs, sz, _t in entries]
        starts = [bs for _o, _p, bs, sz, _t in entries]
        contiguous = (ends == sorted(ends)) and (starts == sorted(starts))
        hits.append((q, entries, p, contiguous))

    print("候选 %d 处：" % len(hits))
    for q, entries, p, contig in hits:
        print("-" * 72)
        print("  计数字段 @%d = %d 条   %s" % (q, len(entries),
                                            "byteStart 递增且首尾相接" if contig else ""))
        for off, pid, bs, sz, tid in entries:
            marks = []
            if bs == 0:
                marks.append("byteStart 相对数据区起点")
            if bs == data_offset:
                marks.append("byteStart 绝对值")
            for k in KEYS:
                ko = data.find(k)
                if bs <= ko < bs + sz:
                    marks.append("含 %s" % k.decode())
                    break
            print("     @%-6d pathID=%-22d start=%-8d size=%-8d typeID=%-3d %s"
                  % (off, pid, bs, sz, tid, " ".join(marks)))
        print("    表后 24 字节: " + " ".join("%02x" % c for c in meta[p:p + 24]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
