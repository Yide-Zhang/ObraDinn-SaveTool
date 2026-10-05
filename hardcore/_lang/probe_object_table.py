#!/usr/bin/env python3
"""用已知值精确搜索对象表。

第一个对象的 byteStart 必然等于 SerializedFile 的 data_offset(9264)，
byteSize 必然是 file_size - data_offset(61336)。所以直接在元数据区里
搜这个 8 字节组合（大端和小端都试），命中处前后打印上下文。

用法：
    python hardcore/_lang/probe_object_table.py hardcore/_lang/lang-en
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from hardcore.lang_bundle import Bundle  # noqa: E402


def find_all(hay: bytes, needle: bytes) -> list[int]:
    out, i = [], hay.find(needle)
    while i >= 0:
        out.append(i)
        i = hay.find(needle, i + 1)
    return out


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "hardcore/_lang/lang-en")
    b = Bundle(path)
    data = b.data()

    meta_size, = struct.unpack_from(">I", data, 0)
    file_size, = struct.unpack_from(">I", data, 4)
    data_offset, = struct.unpack_from(">I", data, 12)
    obj_size = file_size - data_offset
    meta = data[:meta_size]

    print("metadata_size=%d file_size=%d data_offset=%d obj_size=%d"
          % (meta_size, file_size, data_offset, obj_size))
    print("搜索第一个对象条目的 (byteStart, byteSize) = (%d, %d)" % (data_offset, obj_size))
    print()

    for tag, needle in (("大端", struct.pack(">II", data_offset, obj_size)),
                        ("小端", struct.pack("<II", data_offset, obj_size))):
        hits = find_all(meta, needle)
        print("%s 组合 %s -> 命中 %d 处 %s"
              % (tag, needle.hex(), len(hits), hits[:8]))
        for h in hits[:3]:
            lo = max(0, h - 24)
            hi = min(len(meta), h + 28)
            print("   @%d 上下文:" % h)
            print("     " + " ".join("%02x" % c for c in meta[lo:hi]))
            # 表前 4 字节 = 条目数？
            if h - 8 >= 0:
                before, = struct.unpack_from(">I", meta, h - 8)
                path_id, = struct.unpack_from(">q", meta, h - 8)
                print("     往前 8 字节当 pathID = %d" % path_id)
            cnt_off = h - 12
            if cnt_off >= 0:
                cnt, = struct.unpack_from(">I", meta, cnt_off)
                print("     再往前 4 字节 = %d  %s"
                      % (cnt, "像个条目数" if 0 < cnt < 64 else ""))
        print()

    # 反向验证：如果表就在命中处，那么从该处起按 20 字节步进，
    # 每条的 byteStart 都应递增且合法
    for tag, fmt in (("大端", ">"), ("小端", "<")):
        needle = struct.pack(fmt + "II", data_offset, obj_size)
        for h in find_all(meta, needle)[:1]:
            base = h - 8                       # 回到条目的起始（pathID 起点）
            print("按 %s 假设，表起点 @%d，往后步进：" % (tag, base))
            for k in range(6):
                off = base + k * 20
                if off + 20 > len(meta):
                    break
                pid, = struct.unpack_from(fmt + "q", meta, off)
                bs, = struct.unpack_from(fmt + "I", meta, off + 8)
                sz, = struct.unpack_from(fmt + "I", meta, off + 12)
                tid, = struct.unpack_from(fmt + "I", meta, off + 16)
                ok = (data_offset <= bs and bs + sz <= file_size and 0 < tid < 4096)
                print("   [%d] @%-6d pathID=%-22d byteStart=%-7d byteSize=%-7d "
                      "typeID=%-4d %s" % (k, off, pid, bs, sz, tid,
                                          "合理" if ok else "不合理 <- 表到此为止"))
                if not ok:
                    break
            print()

    print("元数据区最后 64 字节：")
    print("  " + " ".join("%02x" % c for c in meta[-64:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
