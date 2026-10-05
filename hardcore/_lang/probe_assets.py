#!/usr/bin/env python3
"""探「语言包解压后的 SerializedFile」结构，为原地改写做准备。

想知道的事：
  1. SerializedFile 头部的几个关键字段（元数据长度、文件长度、版本、数据偏移、字节序）
  2. `strings` 数组里的字符串是怎么存的 —— 是不是 Unity 的老规矩：
     `int32 长度 + 内容 + 对齐到 4 字节`
  3. 目录里的两条（SerializedFile / .resS）各占多少

用法：
    python hardcore/_lang/probe_assets.py hardcore/_lang/lang-en
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from hardcore.lang_bundle import Bundle  # noqa: E402

KEYS = ("welldone_3_first", "welldone_3_more",
        "help_faceclear_fates0", "help_faceclear_fates1")


def hx(b: bytes, off: int, n: int) -> str:
    return " ".join("%02x" % c for c in b[off:off + n])


def asc(b: bytes, off: int, n: int) -> str:
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b[off:off + n])


def align4(n: int) -> int:
    return (n + 3) & ~3


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "hardcore/_lang/lang-en")
    b = Bundle(path)
    data = b.data()
    print("=" * 76)
    print(b.describe())
    print("解压后数据长度 : %d (0x%X)" % (len(data), len(data)))
    print()
    print()

    # ---- SerializedFile 头部 ----
    print("-" * 76)
    print("SerializedFile 头部（大端）")
    p = 0
    meta_size, = struct.unpack_from(">I", data, p)
    p += 4
    file_size, = struct.unpack_from(">I", data, p)
    p += 4
    version, = struct.unpack_from(">I", data, p)
    p += 4
    data_offset, = struct.unpack_from(">I", data, p)
    p += 4
    endian = data[p]
    p += 1
    p += 3                                    # 3 字节保留
    print("  metadata_size : %d (0x%X)" % (meta_size, meta_size))
    print("  file_size     : %d (0x%X)   实际 %d  %s"
          % (file_size, file_size, len(data),
             "对得上" if file_size == len(data) else "**对不上**"))
    print("  version       : %d" % version)
    print("  data_offset   : %d   头部结束后的第一段数据" % data_offset)
    print("  endianness    : %d (%s)" % (endian, "小端" if endian else "大端"))
    s, p = _cstr(data, p)
    print("  unity version : %s" % s)
    s, p = _cstr(data, p)
    print("  unity revision: %s" % s)

    # ---- 目录 ----
    print()
    print("-" * 76)
    print("blocksInfo 里的目录（大端）")
    for i, e in enumerate(b.directory):
        print("  [%d] %-28s offset=%d size=%d flags=%s"
              % (i, e.get("name"), e.get("offset"), e.get("size"), e.get("flags")))
    print()

    # ---- 字符串存法 ----
    print("-" * 76)
    print("四个键及其取值附近的字节（小端 int32 长度 + 内容 + 对齐到 4）")
    for key in KEYS:
        kb = key.encode()
        off = data.find(kb)
        if off < 0:
            print("  %-24s **找不到**" % key)
            continue
        print()
        print("  键 %-22s 数据内偏移 %d (0x%X)" % (key, off, off))
        # 键之前 8 字节：应当是 int32 长度 + 上一段的对齐填充
        pre = off - 8
        print("    键前 8 字节 : %s" % hx(data, pre, 8))
        print("    键前 4 字节小端 = %d （键长度 %d）"
              % (struct.unpack_from("<I", data, pre + 4)[0], len(kb)))
        # 键之后：对齐填充，然后是值的长度 + 内容
        vstart = off + len(kb)
        pad = align4(vstart) - vstart
        vl, = struct.unpack_from("<I", data, vstart + pad)
        vbytes = data[vstart + pad + 4: vstart + pad + 4 + vl]
        print("    键后对齐填充 : %d 字节" % pad)
        print("    值长度 %d     : %r" % (vl, vbytes.decode("utf-8", "replace")))
        vafter = vstart + pad + 4 + vl
        print("    值后对齐填充 : %d 字节 -> 下一个字符串从 %d 开始"
              % (align4(vafter) - vafter, align4(vafter)))
        print("    下一串前 8 字节: %s" % hx(data, align4(vafter), 8))
        print("    下一串预览     : %r" % data[align4(vafter) + 4:
                                            align4(vafter) + 40].decode("utf-8", "replace"))

    # ---- 顺带看一眼最后一个对象之后有什么 ----
    print()
    print("-" * 76)
    print("数据末尾 64 字节")
    print("  " + hx(data, len(data) - 64, 64))
    print("  " + asc(data, len(data) - 64, 64))
    return 0


def _cstr(buf: bytes, off: int) -> tuple[str, int]:
    end = buf.index(b"\0", off)
    return buf[off:end].decode("utf-8", "replace"), end + 1


if __name__ == "__main__":
    sys.exit(main())
