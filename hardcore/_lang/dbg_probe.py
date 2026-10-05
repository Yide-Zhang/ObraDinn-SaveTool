#!/usr/bin/env python3
"""决定性探针：未压缩的 lang-zh-s 里，ASCII 字符串 ID 落在哪个区间。

前端假设: blocksInfo = [50, 203)，数据块 = [203, EOF)
末端假设: 数据块 = [50, 3504842)，blocksInfo = [3504842, EOF)
看哪个区间里能找到 "welldone_3_first" 这类字符串 ID。
"""
import struct
import sys
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else "hardcore/_lang/lang-zh-s")
buf = p.read_bytes()
print("file=%s  len=%d" % (p, len(buf)))

# 头部字段
size, cbis, ubis, flags = struct.unpack_from(">qIII", buf, 30)
hdr = 50
front_data = hdr + cbis                     # 203
end_blocks = len(buf) - cbis                # 3504842
print("size=%d cbis=%d ubis=%d flags=0x%02x" % (size, cbis, ubis, flags))
print("前端假设: blocksInfo=[%d,%d)  数据块=[%d,%d)" % (hdr, front_data, front_data, len(buf)))
print("末端假设: 数据块=[%d,%d)  blocksInfo=[%d,%d)" % (hdr, end_blocks, end_blocks, len(buf)))
print()

needles = [b"welldone_3_first", b"welldone_2_first", b"correct1", b"CAB-", b"LangPack"]
for needle in needles:
    hits = []
    i = buf.find(needle)
    while i >= 0 and len(hits) < 8:
        hits.append(i)
        i = buf.find(needle, i + 1)
    where = []
    for h in hits:
        if h < front_data:
            where.append("blocksInfo区")
        elif h >= end_blocks:
            where.append("末端区")
        else:
            where.append("公共数据区")
    print("%-18s 命中 %d 处 @ %s  %s"
          % (needle.decode(), len(hits), hits, where))
print()

print("=== blocksInfo(153B) 全文 ===")
bi = buf[hdr:hdr + cbis]
for i in range(0, len(bi), 16):
    chunk = bi[i:i + 16]
    print("  +%03d  %-47s |%s|" % (i, chunk.hex(" "),
                                   "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)))
print()

print("=== 前端假设的数据块开头 48 字节 (=偏移 %d) ===" % front_data)
d = buf[front_data:front_data + 48]
print("  " + d.hex(" "))
print("  |%s|" % "".join(chr(c) if 32 <= c < 127 else "." for c in d))
print()
print("=== 末端假设的数据块开头 48 字节 (=偏移 %d) ===" % hdr)
d = buf[hdr:hdr + 48]
print("  " + d.hex(" "))
print("  |%s|" % "".join(chr(c) if 32 <= c < 127 else "." for c in d))
print()
print("=== 数据块末尾 32 字节 ===")
print("  " + buf[len(buf) - 32:].hex(" "))
