"""读 PE 的 TimeDateStamp / 链接器版本，判断哪个 build 更新。"""
import datetime
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = [
    ("originalDLLWin",      ROOT / "originalDLLWin" / "Assembly-CSharp.dll"),
    ("我们的原版 .orig",     ROOT / "hardcore" / "_backup" / "Assembly-CSharp.dll.orig"),
]

for tag, p in FILES:
    b = p.read_bytes()
    e_lfanew = struct.unpack_from("<I", b, 0x3C)[0]
    sig = b[e_lfanew:e_lfanew + 4]
    if sig != b"PE\0\0":
        print("%s: 不是 PE" % tag)
        continue
    coff = e_lfanew + 4
    machine, nsec, tds = struct.unpack_from("<HHI", b, coff)
    opt = coff + 20
    magic = struct.unpack_from("<H", b, opt)[0]
    # 可选头里 linker 版本
    major, minor = struct.unpack_from("<BB", b, opt + 2)
    # Debug 目录（PE32: opt+96+6*8；PE32+: opt+112+6*8）里的 TimeDateStamp
    dd = opt + (96 if magic == 0x10B else 112)
    dbg_rva, dbg_sz = struct.unpack_from("<II", b, dd + 6 * 8)
    dbg_ts = None
    if dbg_rva and dbg_sz >= 28:
        # 需要 RVA->offset；对 .rdata 常见映射，做个简单查表
        nsec_off = coff + 20 + struct.unpack_from("<H", b, coff + 16)[0]
        for i in range(nsec):
            s = nsec_off + i * 40
            va, vsz = struct.unpack_from("<II", b, s + 12)
            praw, rsz = struct.unpack_from("<II", b, s + 20)
            if va <= dbg_rva < va + max(vsz, rsz):
                off = dbg_rva - va + praw
                dbg_ts = struct.unpack_from("<I", b, off + 4)[0]
                break
    print("=== %s ===" % tag)
    print("  size        %d" % len(b))
    print("  COFF 时间戳 0x%08X = %s" % (tds, datetime.datetime.utcfromtimestamp(tds) if tds else "0（不可用）"))
    print("  链接器版本  %d.%d" % (major, minor))
    if dbg_ts is not None:
        print("  Debug 时间戳 0x%08X = %s" % (dbg_ts, datetime.datetime.utcfromtimestamp(dbg_ts)))
    else:
        print("  Debug 目录  无")
    print("  sections    %d" % nsec)
