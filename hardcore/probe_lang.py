#!/usr/bin/env python3
"""探测游戏 StreamingAssets 下各语言包的 AssetBundle 压缩格式。

UnityFS 头（全部多字节整数都是**大端**）：
    char[8]  signature      "UnityFS\\0"
    int32    version
    string   unityVersion   以 \\0 结尾
    string   unityRevision  以 \\0 结尾
    int64    size           整个文件大小
    uint32   compressedBlocksInfoSize
    uint32   uncompressedBlocksInfoSize
    uint32   flags          flags & 0x3F = 压缩方式, 0x80 = blocksInfo 在文件尾部

压缩方式：
    0 = 不压缩   1 = LZMA   2 = LZ4   3 = LZ4HC

用法：
    python hardcore/probe_lang.py "F:\\...\\ObraDinn\\ObraDinn_Data\\StreamingAssets"
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

COMPRESSION = {0: "none", 1: "LZMA", 2: "LZ4", 3: "LZ4HC"}


def read_cstr(buf: bytes, off: int) -> tuple[str, int]:
    end = buf.index(b"\0", off)
    return buf[off:end].decode("utf-8", "replace"), end + 1


def parse_header(buf: bytes) -> dict:
    if buf[:8] != b"UnityFS\0":
        return {"error": "不是 UnityFS 包（可能是旧格式或压缩流）"}
    version, = struct.unpack_from(">I", buf, 8)
    unity_version, off = read_cstr(buf, 12)
    unity_revision, off = read_cstr(buf, off)
    size, cbis, ubis, flags = struct.unpack_from(">qIII", buf, off)
    return {
        "version": version,
        "unity": unity_version,
        "revision": unity_revision,
        "size": size,
        "blocks_info_compressed": cbis,
        "blocks_info_uncompressed": ubis,
        "flags": flags,
        "compression": COMPRESSION.get(flags & 0x3F, "?%d" % (flags & 0x3F)),
        "blocks_info_at_end": bool(flags & 0x80),
        "header_len": off + 8 + 4 + 4 + 4 + 4 + 4,
    }


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    files = sorted(p for p in root.glob("lang-*") if p.suffix != ".manifest")
    if not files:
        return print("没找到 lang-* 文件") or 1

    print("%-12s %8s  %-7s %6s %-22s %s" %
          ("语言包", "KB", "压缩", "版本", "unity", "flags"))
    print("-" * 78)
    kinds: dict[str, int] = {}
    for p in files:
        h = parse_header(p.read_bytes()[:256])
        if "error" in h:
            print("%-12s %8.0f  %s" % (p.name, p.stat().st_size / 1024, h["error"]))
            continue
        kinds[h["compression"]] = kinds.get(h["compression"], 0) + 1
        print("%-12s %8.0f  %-7s %6d %-22s 0x%02x%s" %
              (p.name, p.stat().st_size / 1024, h["compression"], h["version"],
               h["unity"], h["flags"],
               "  (blocksInfo 在尾部)" if h["blocks_info_at_end"] else ""))

    print()
    print("压缩方式统计:", ", ".join("%s x%d" % (k, v) for k, v in sorted(kinds.items())))
    need_lz4 = any(k in ("LZ4", "LZ4HC") for k in kinds)
    print("是否需要自己实现 LZ4 解压:", "是" if need_lz4 else "否（只用标准库 lzma）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
