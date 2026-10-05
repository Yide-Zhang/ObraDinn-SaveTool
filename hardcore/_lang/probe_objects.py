#!/usr/bin/env python3
"""在 SerializedFile 的元数据区里找「对象表」，确认能不能安全修偏移。

元数据区（大端）里有一张对象表，每条是：

    int64 pathID, uint32 byteStart, uint32 byteSize, uint32 typeID      （共 20 字节）

只要字符串长度一变，对象数据就整体位移，必须回头改这里的 byteStart / byteSize。
这个脚本用「数值自洽」的办法把表找出来：
  找连续的、byteStart 严格递增、且 byteStart+byteSize <= 数据总长的条目。

用法：
    python hardcore/_lang/probe_objects.py hardcore/_lang/lang-en
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from hardcore.lang_bundle import Bundle  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "hardcore/_lang/lang-en")
    b = Bundle(path)
    data = b.data()

    meta_size, = struct.unpack_from(">I", data, 0)
    file_size, = struct.unpack_from(">I", data, 4)
    version, = struct.unpack_from(">I", data, 8)
    data_offset, = struct.unpack_from(">I", data, 12)

    print("metadata_size=%d file_size=%d version=%d data_offset=%d" %
          (meta_size, file_size, version, data_offset))
    print("目录          : %s" % [(e.get("name"), e.get("offset"), e.get("size"))
                                for e in b.directory])
    print()

    meta = data[:meta_size]

    # 用数值自洽的老办法找对象表：byteStart 递增，且 byteStart+byteSize <= file_size
    hits: list[tuple[int, int, int, int, int]] = []
    for off in range(0, len(meta) - 20):
        path_id, = struct.unpack_from(">q", meta, off)
        bs, = struct.unpack_from(">I", meta, off + 8)
        sz, = struct.unpack_from(">I", meta, off + 12)
        tid, = struct.unpack_from(">I", meta, off + 16)
        if not (0 <= path_id < 1 << 62):
            continue
        if not (0 < sz <= file_size):
            continue
        if not (data_offset <= bs and bs + sz <= file_size):
            continue
        if not (0 < tid < 4096):
            continue
        hits.append((off, path_id, bs, sz, tid))

    print("数值自洽的候选条目 %d 条：" % len(hits))
    # 只保留「连续成表」的段：后一条的偏移正好 +20
    runs: list[list[tuple]] = []
    for h in hits:
        if runs and h[0] == runs[-1][-1][0] + 20:
            runs[-1].append(h)
        else:
            runs.append([h])
    runs.sort(key=len, reverse=True)
    for r in runs[:3]:
        print("  表段 @%d  长度 %d 条" % (r[0][0], len(r)))
        for off, pid, bs, sz, tid in r:
            print("     @%-7d pathID=%-22d byteStart=%-7d byteSize=%-7d typeID=%d%s"
                  % (off, pid, bs, sz, tid,
                     "   <- 字符串都在这个对象里" if bs <= 15692 < bs + sz else ""))
        # 表前面的 4 字节应当就是条目数
        cnt_off = r[0][0] - 4
        if cnt_off >= 0:
            cnt, = struct.unpack_from(">I", meta, cnt_off)
            print("     表前 4 字节(@%d) = %d  %s"
                  % (cnt_off, cnt, "== 条目数 ✓" if cnt == len(r) else "**不等于条目数**"))

    print()
    print("元数据区最后 48 字节：")
    print("  " + " ".join("%02x" % c for c in meta[-48:]))
    print()
    print("对象数据区开头 16 字节 (@data_offset)：")
    print("  " + " ".join("%02x" % c for c in data[data_offset:data_offset + 16]))
    print("对象数据区长度 = file_size - data_offset = %d" % (file_size - data_offset))
    return 0


if __name__ == "__main__":
    sys.exit(main())
