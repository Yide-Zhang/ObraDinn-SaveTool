#!/usr/bin/env python3
"""诊断 UnityFS 头部与 blocksInfo 的真实布局（拿未压缩的 lang-zh-s 看）。"""
import struct
import sys
from pathlib import Path


def cstr(b: bytes, o: int):
    e = b.index(b"\0", o)
    return b[o:e].decode("utf-8", "replace"), e + 1


p = Path(sys.argv[1] if len(sys.argv) > 1 else "hardcore/_lang/lang-zh-s")
buf = p.read_bytes()
print("file      : %s" % p)
print("len       : %d" % len(buf))
print("sig       : %r" % buf[:8])

off = 12
ver, = struct.unpack_from(">I", buf, 8)
print("version   : %d" % ver)
uv, off = cstr(buf, off)
rv, off = cstr(buf, off)
print("unity     : %r  rev: %r  (off=%d)" % (uv, rv, off))

size, cbis, ubis, flags = struct.unpack_from(">qIII", buf, off)
print("size      : %d  (file=%d)" % (size, len(buf)))
print("cbis      : %d" % cbis)
print("ubis      : %d" % ubis)
print("flags     : 0x%02x  压缩=%d  blocksInfoAtEnd=%s  combined=%s"
      % (flags, flags & 0x3F, bool(flags & 0x40), bool(flags & 0x80)))
hdr = off + 20
print("header_len: %d" % hdr)

print()
print("=== 头之后前 80 字节 ===")
print(buf[hdr:hdr + 80].hex(" "))

print()
print("=== 尾部 cbis 字节（%d）===" % cbis)
tail = buf[len(buf) - cbis:]
for i in range(0, len(tail), 16):
    chunk = tail[i:i + 16]
    print("  +%04d  %-47s |%s|" % (i, chunk.hex(" "),
                                   "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)))

print()
print("=== 按不同解释试算 blockCount ===")
for hlen, name in ((16, "含 16B 哈希"), (0, "不含哈希")):
    if len(tail) < hlen + 4:
        continue
    n, = struct.unpack_from(">I", tail, hlen)
    need = hlen + 4 + n * 10
    print("  %s: blockCount=%d  需要 %d 字节  实际 %d  剩余 %d"
          % (name, n, need, len(tail), len(tail) - need))
    if 0 < n < 64:
        for k in range(min(n, 6)):
            u, c, f = struct.unpack_from(">IIH", tail, hlen + 4 + k * 10)
            print("      block[%d] usize=%d csize=%d flags=0x%04x" % (k, u, c, f))

print()
print("=== 数据块区总长核算 ===")
print("  header + ? + cbis = %d ; 文件 = %d ; 差 = %d"
      % (hdr + cbis, len(buf), len(buf) - hdr - cbis))
