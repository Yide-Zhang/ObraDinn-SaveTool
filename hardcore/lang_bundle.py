#!/usr/bin/env python3
"""读取 UnityFS AssetBundle（游戏的语言包 `lang-*`）。

格式（**所有多字节整数都是大端**）：

    char[8]  signature                    "UnityFS\\0"
    int32    version                      6
    string   unityVersion                 \\0 结尾（"5.x.x"）
    string   unityRevision                \\0 结尾（"2017.4.37f1"）
    int64    size                         整个文件大小
    uint32   compressedBlocksInfoSize
    uint32   uncompressedBlocksInfoSize
    uint32   flags                        bits0-5 = 压缩方式；0x40 = blocksInfo 排在数据块之后

    flags & 0x3F: 0=none  1=LZMA  2=LZ4  3=LZ4HC
    ★ LZ4HC 与 LZ4 的**解压**完全相同（HC 只是压得更狠的编码器），所以解码不需要额外支持。

文件布局（实测：本游戏 14 个包的 blocksInfo **紧跟头部**）：

    [头] [blocksInfo] [数据块...]
    blocksInfo 本身也按 flags 里的压缩方式压过

★ 不要相信 `flags & 0x40`（BlocksInfoAtTheEnd）：这 14 个包的 flags 都是 0x43 / 0x40，
  按该位应该是「在尾部」，但实测 blocksInfo 就在头部（偏移 50 = 头部长度）。
  判据是硬证据：lang-zh-s 在偏移 `50 + cbis = 203` 处正好是数据块里
  SerializedFile 的头（`... 32 30 31 37 2e 34 2e 33 37 66 31 00` = "2017.4.37f1"）。
  所以本脚本**两个位置都试**，取「块表能解析且块长度合计与文件长度对得上」的那个。

blocksInfo 解压后的内容：

    version >= 6 时先 16 字节 Hash128
    uint32 blockCount
    每块 10 字节：uint32 uncompressedSize, uint32 compressedSize, uint16 flags
    之后是「目录信息」：uint32 条目数；每条 int64 offset + int64 size + uint32 flags + \0 结尾名字
    （名字合计指向 SerializedFile 与 `.resS` 资源流）

用法：
    python hardcore/lang_bundle.py [目录或单个文件]
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import lz4.block

COMPRESSION = {0: "none", 1: "LZMA", 2: "LZ4", 3: "LZ4HC"}


def _cstr(buf: bytes, off: int) -> tuple[str, int]:
    end = buf.index(b"\0", off)
    return buf[off:end].decode("utf-8", "replace"), end + 1


def _decompress(kind: int, data: bytes, usize: int) -> bytes:
    """按压缩方式解压。`usize` 是解压后的长度（LZ4 block 格式必须显式给出）。"""
    if kind == 0:
        return data[:usize]
    if kind in (2, 3):
        return lz4.block.decompress(data, uncompressed_size=usize)
    if kind == 1:
        import lzma
        # Unity 的 LZMA 是 raw 流：头 5 字节是属性，原始长度写在尾部
        props = data[0]
        lc = props % 9
        lp = (props // 9) % 5
        pb = props // 45
        filters = [{"id": lzma.FILTER_LZMA1,
                    "lc": lc, "lp": lp, "pb": pb,
                    "dict_size": int.from_bytes(data[1:5], "little")}]
        return lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=filters).decompress(data[5:], usize)
    raise ValueError("未知压缩方式 %d" % kind)


def _parse_block_table(bi: bytes, version: int):
    """解析块表。返回 (blocks, 尾巴起始偏移)，认不出来返回 None。

    布局：version>=6 先 16 字节 Hash128，然后 uint32 块数，然后每块 10 字节。
    """
    p = 16 if version >= 6 else 0
    if len(bi) < p + 4:
        return None
    count, = struct.unpack_from(">I", bi, p)
    p += 4
    if not 0 < count <= 4096:
        return None
    if p + count * 10 > len(bi):
        return None
    blocks = []
    for _ in range(count):
        usize, csize, bflags = struct.unpack_from(">IIH", bi, p)
        p += 10
        if usize > 1 << 31 or csize > 1 << 31:
            return None
        blocks.append((usize, csize, bflags))
    return blocks, p


def _parse_directory(tail: bytes) -> list:
    """解析 blocksInfo 尾部的「目录信息」。认不出来就返回空表（不影响解数据块）。

    uint32 条目数；每条：int64 offset, int64 size, uint32 flags, \0 结尾名字（名字后无对齐填充）
    指向包内的 SerializedFile 与其资源流。
    自证（lang-zh-s）：得到 offset 0 / size 1793432 与 offset 1793432 / size 1711360，
    两者相加正好等于数据块总长 3504792。
    """
    if len(tail) < 4:
        return []
    count, = struct.unpack_from(">I", tail, 0)
    if not 0 < count <= 64:
        return []
    p, out = 4, []
    for _ in range(count):
        try:
            off, sz = struct.unpack_from(">qq", tail, p)
            p += 16
            fl, = struct.unpack_from(">I", tail, p)
            p += 4
            name, p = _cstr(tail, p)
        except Exception:                              # noqa: BLE001
            return out
        out.append({"offset": off, "size": sz, "flags": fl, "name": name})
    return out


class Bundle:
    """一个 UnityFS 包。只读，不做任何改写。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        self._parse()

    # ---------------------------------------------------------------- 解析
    def _parse(self) -> None:
        buf = self.raw
        if buf[:8] != b"UnityFS\0":
            raise ValueError("不是 UnityFS 包: %s" % self.path)

        self.version, = struct.unpack_from(">I", buf, 8)
        off = 12
        self.unity, off = _cstr(buf, off)
        self.revision, off = _cstr(buf, off)
        self.size, self.cbis, self.ubis, self.flags = struct.unpack_from(">qIII", buf, off)
        off += 20
        self.header_len = off
        self.compression = self.flags & 0x3F

        if self.flags & 0x80:
            raise NotImplementedError("blocksInfo 与数据块合并（flags=0x%02x），暂不支持" % self.flags)

        # 两个候选位置都试，取块表能解析、且块长度合计与文件长度对得上的那个。
        reasons = []
        for at_end in (False, True):
            pos = (len(buf) - self.cbis) if at_end else self.header_len
            label = "尾部" if at_end else "头部"
            if pos < 0:
                reasons.append("%s: 越界" % label)
                continue
            try:
                bi = _decompress(self.compression, buf[pos:pos + self.cbis], self.ubis)
            except Exception as exc:                   # noqa: BLE001
                reasons.append("%s: 解压失败 %s" % (label, exc))
                continue
            parsed = _parse_block_table(bi, self.version)
            if parsed is None:
                reasons.append("%s: 块表解析不出来" % label)
                continue
            blocks, tail_off = parsed
            data_off = self.header_len + (0 if at_end else self.cbis)
            need = data_off + sum(c for _u, c, _f in blocks) + (self.cbis if at_end else 0)
            if need != len(buf):
                reasons.append("%s: 块长度合计 %d 与文件长度 %d 对不上"
                               % (label, need, len(buf)))
                continue

            self.blocks_info_at_end = at_end
            self.blocks_info_off = pos
            self.blocks_info_hash = bi[:16] if self.version >= 6 else None
            self.blocks = blocks
            self.blocks_info_tail = bi[tail_off:]
            self.directory = _parse_directory(self.blocks_info_tail)
            return

        raise ValueError("无法定位 blocksInfo: " + "; ".join(reasons))

    # ---------------------------------------------------------------- 数据
    @property
    def data_offset(self) -> int:
        return self.header_len + (self.cbis if not self.blocks_info_at_end else 0)

    def data(self) -> bytes:
        """把所有数据块解压后拼起来 —— 这就是序列化文件本体。"""
        out = bytearray()
        pos = self.data_offset
        for usize, csize, bflags in self.blocks:
            out += _decompress(bflags & 0x3F, self.raw[pos:pos + csize], usize)
            pos += csize
        return bytes(out)

    # ---------------------------------------------------------------- 校验
    def layout_ok(self) -> bool:
        """[头] + blocksInfo + 各数据块压缩长度 == 文件长度"""
        return (self.data_offset + sum(c for _u, c, _f in self.blocks)
                + (self.cbis if self.blocks_info_at_end else 0)) == len(self.raw)

    def describe(self) -> str:
        total_u = sum(u for u, _c, _f in self.blocks)
        blk_comp = {COMPRESSION.get(f & 0x3F, "?") for _u, _c, f in self.blocks}
        return ("v%d unity=%s size=%d flags=0x%02x(%s) blocksInfo=%s blocks=%d "
                "解压后=%d 块压缩=%s layout=%s"
                % (self.version, self.unity, self.size, self.flags,
                   COMPRESSION.get(self.compression, "?"),
                   "尾部" if self.blocks_info_at_end else "头部",
                   len(self.blocks), total_u, ",".join(sorted(blk_comp)),
                   "OK" if self.layout_ok() else "对不上"))


def render_ascii(data: bytes, off: int, length: int) -> str:
    chunk = data[off:off + length]
    return "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "hardcore/_lang")
    files = [root] if root.is_file() else sorted(
        p for p in root.glob("lang-*") if p.suffix != ".manifest")
    if not files:
        print("没找到 lang-* 文件")
        return 1

    bad = 0
    for p in files:
        try:
            b = Bundle(p)
        except Exception as exc:                      # noqa: BLE001
            print("%-12s [X] %s" % (p.name, exc))
            bad += 1
            continue
        ok = b.layout_ok()
        if not ok:
            bad += 1
        print("%-12s [%s] %s" % (p.name, "OK" if ok else "XX", b.describe()))
        d = b.data()
        head = d[:24].hex(" ")
        print("%-12s      数据 @%d, %d 字节，头: %s" % ("", b.data_offset, len(d), head))
        dirsum = sum(e["size"] for e in b.directory)
        print("%-12s      包内文件: %s  合计=%d %s"
              % ("", ", ".join("%s(%d)" % (e["name"], e["size"]) for e in b.directory)
                 or "(未解析)", dirsum,
                 "[OK]" if dirsum == len(d) else "[对不上]"))
        for probe in (b"welldone_3_first", b"LangPack"):
            i = d.find(probe)
            print("%-12s      探针 %-16s %s"
                  % ("", probe.decode(), ("@%d" % i) if i >= 0 else "未命中"))

    print()
    print("=" * 78)
    print("结论：%s" % ("全部可解包，布局校验通过" if not bad else "有 %d 个包有问题" % bad))
    print("=" * 78)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
