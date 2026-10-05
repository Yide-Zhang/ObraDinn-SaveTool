#!/usr/bin/env python3
"""原地改写游戏语言包（`lang-*`）—— 纯 Python，不依赖 C# 工具。

目标
----
补丁器不该把 33 MB 的补丁语言包随程序发出去。玩家机器上本来就有原版语言包，
备份一份原件后，直接照着原版改出目标档位的版本即可。

能这么干的前提（都已实测确认，见 probe_assets.py / find_objtable.py）
------------------------------------------------------------------------
* 包内就是一个 SerializedFile，字符串按 Unity 老规矩存：
      int32 小端长度 + 内容 + 补齐到 4 字节
* 头 4 个 u32（metadata_size / file_size / version / data_offset）**恒为大端**，
  其余字段是文件自己的字节序（本游戏 14 个包都是小端）。
* 元数据区尾部有对象表：`u32 条目数` + 每条 20 字节
  `(int64 pathID, u32 byteStart, u32 byteSize, u32 typeID)`，
  其中 **byteStart 相对 data_offset**，且对象首尾相接。
* 要改的 4 个键全在同一个对象里，且它是**最后一个**对象。

于是改写只需要动三处：
    1. 对象数据里替换那 4 个字符串（整体位移）
    2. 该对象的 byteSize（一个 u32，原地改，长度不变）
    3. 头部的 file_size + 目录里的两条（SerializedFile 大小、.resS 偏移）

用法
----
    python hardcore/langpatch.py inspect  <包>
    python hardcore/langpatch.py patch    <输入包> <输出包> --level 58
    python hardcore/langpatch.py verify   <包>
    python hardcore/langpatch.py selftest          # 拿已知good产物对拍
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import lz4.block                                  # noqa: E402

from hardcore.lang_bundle import Bundle           # noqa: E402


def _utf8_stdout() -> None:
    """控制台默认是 GBK，印中文/✓ 之类的字符会直接抛异常。

    直接重定向时必须自己设成 UTF-8（和 langtool 里那句
    `Console.OutputEncoding = UTF8` 是同一个毛病）。
    """
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_utf8_stdout()

LEVELS = (3, 4, 6, 9, 14, 29, 58)
KEYS = ("welldone_3_first", "welldone_3_more",
        "help_faceclear_fates0", "help_faceclear_fates1")

MAX_LEAD = 1 << 16          # 对象数据区开头那段（类型/字段名字符串）最长允许多少
MAX_TAIL = 1 << 16          # 最后一个对象之后允许剩多少


def align4(n: int) -> int:
    return (n + 3) & ~3


# ==========================================================================
# 读：定位对象表
# ==========================================================================
def scan(data: bytes) -> dict:
    """扫出所有「条目数 + N 条各自合法」的候选对象表（不带任何其它门槛）。

    只做单条合法性判断，方便诊断；后续的连续性 / 范围 / 包得住字符串
    等门槛由 parse_layout 施加。
    """
    meta_size, = struct.unpack_from(">I", data, 0)
    file_size, = struct.unpack_from(">I", data, 4)
    version, = struct.unpack_from(">I", data, 8)
    data_offset, = struct.unpack_from(">I", data, 12)
    if not (0 < meta_size <= data_offset <= file_size <= len(data)):
        raise ValueError("头部字段不自洽: meta=%d data_offset=%d file_size=%d len=%d"
                         % (meta_size, data_offset, file_size, len(data)))
    if version != 17:
        raise ValueError("只认识 SerializedFile v17，实际 %d" % version)

    meta = data[:meta_size]
    obj_size_total = file_size - data_offset

    # 类型总数：头 20 字节 + unityVersion\0 + i32 平台 + u8 enableTypeTree
    p0 = data.index(b"\0", 20) + 1 + 4 + 1
    type_count, = struct.unpack_from("<I", data, p0)

    key_rels = []
    for key in KEYS:
        kpos = data.find(struct.pack("<I", len(key.encode())) + key.encode())
        if kpos >= 0:
            key_rels.append(kpos - data_offset)

    # 不用「计数字段」去认表：表头前面的数据经常凑出一个看着像计数的值，
    # 反而把真表截断。直接找**最长的连续条目段**——真表就是全部对象。
    runs: list[list[dict]] = []
    skip: set[int] = set()
    for q in range(0, len(meta) - 19):
        if q in skip:
            continue
        first = _entry_at(meta, q, type_count, obj_size_total)
        if first is None:
            continue
        run = [first]
        p = q + 20
        while True:
            nxt = _entry_at(meta, p, type_count, obj_size_total)
            if nxt is None:
                break
            # 对象按地址递增排列；首尾相接时可能夹 ≤4 字节对齐填充，
            # 也可能完全相等（空对象），所以只要求非递减。
            if nxt["byte_start"] < run[-1]["byte_start"]:
                break
            run.append(nxt)
            p += 20
        runs.append(run)
        if len(run) > 1:
            skip.update(range(q + 20, p))

    cands = []
    for run in runs:
        entries = run
        lead = entries[0]["byte_start"]
        tail = obj_size_total - (entries[-1]["byte_start"] + entries[-1]["byte_size"])
        covers = (len(key_rels) == len(KEYS) and all(
            any(e["byte_start"] <= r < e["byte_start"] + e["byte_size"]
                for e in entries) for r in key_rels))
        cands.append({"count_off": entries[0]["entry_off"], "entries": entries,
                      "table_end": entries[-1]["entry_off"] + 20,
                      "lead": lead, "tail": tail, "covers": covers})

    return {"meta_size": meta_size, "file_size": file_size, "version": version,
            "data_offset": data_offset, "obj_data_size": obj_size_total,
            "type_count": type_count, "key_rels": key_rels, "cands": cands}


def _entry_at(meta: bytes, off: int, type_count: int,
              obj_size_total: int) -> dict | None:
    """在 off 处试读一条对象条目；不合法返回 None。

    注意 `byte_size` 允许为 0：包里确实存在空的（被剥离的）对象，
    要是把它当非法，整段对象表就会在这里断开。
    """
    if off < 0 or off + 20 > len(meta):
        return None
    pid, = struct.unpack_from("<q", meta, off)
    bs, = struct.unpack_from("<I", meta, off + 8)
    sz, = struct.unpack_from("<I", meta, off + 12)
    tid, = struct.unpack_from("<i", meta, off + 16)
    if not (pid > 0 and 0 <= bs
            and bs + sz <= obj_size_total and 0 <= tid < max(1, type_count)):
        return None
    return {"entry_off": off, "path_id": pid, "byte_start": bs,
            "byte_size": sz, "type_id": tid}


def parse_layout(data: bytes) -> dict:
    """解析 SerializedFile 的头部与对象表。有任何不自洽就抛异常。"""
    r = scan(data)
    good = []
    for c in r["cands"]:
        if not c["covers"]:
            continue
        if not (0 <= c["lead"] <= MAX_LEAD and 0 <= c["tail"] <= MAX_TAIL):
            continue
        good.append(c)
    if not r["cands"]:
        raise ValueError("连一条候选条目都没有（元数据格式与预期不符）")
    if not good:
        lines = ["@%d n=%d lead=%d tail=%d covers=%s"
                 % (c["count_off"], len(c["entries"]), c["lead"], c["tail"], c["covers"])
                 for c in r["cands"][:8]]
        raise ValueError("%d 条候选条目段都被门槛刷掉了：\n    %s"
                         % (len(r["cands"]), "\n    ".join(lines)))
    # 真表是**最长**的那一段（假表只会截到真表的一部分）
    good.sort(key=lambda c: (-len(c["entries"]), c["count_off"]))
    best = good[0]

    return {"meta_size": r["meta_size"], "file_size": r["file_size"],
            "version": r["version"], "data_offset": r["data_offset"],
            "obj_data_size": r["obj_data_size"], "type_count": r["type_count"],
            "count_off": best["count_off"], "entries": best["entries"],
            "lead": best["lead"], "tail": best["tail"],
            "table_end": best["table_end"], "covers": best["covers"],
            "candidates": len(r["cands"])}


def find_string(data: bytes, s: str) -> int:
    """找 `int32 小端长度 + 内容` 出现的位置，返回长度字段的偏移。"""
    needle = struct.pack("<I", len(s.encode())) + s.encode()
    hits, i = [], data.find(needle)
    while i >= 0:
        hits.append(i)
        i = data.find(needle, i + 1)
    if not hits:
        raise ValueError("找不到字符串 %r" % s)
    if len(hits) > 1:
        raise ValueError("字符串 %r 出现 %d 次，无法确定改哪一个" % (s, len(hits)))
    return hits[0]


def read_value(data: bytes, key: str) -> str:
    kpos = find_string(data, key)
    vstart = align4(kpos + 4 + len(key.encode()))
    vlen, = struct.unpack_from("<I", data, vstart)
    return data[vstart + 4:vstart + 4 + vlen].decode("utf-8", "replace")


def value_span(data: bytes, key: str) -> tuple[int, int]:
    """返回该键对应「值」那一段的 [起, 止)（含长度前缀与对齐填充）。"""
    kpos = find_string(data, key)
    vstart = align4(kpos + 4 + len(key.encode()))
    vlen, = struct.unpack_from("<I", data, vstart)
    return vstart, align4(vstart + 4 + vlen)


# ==========================================================================
# 改：替换字符串
# ==========================================================================
def _encode_field(value: str) -> bytes:
    raw = value.encode("utf-8")
    out = struct.pack("<I", len(raw)) + raw
    return out + b"\0" * (align4(len(out)) - len(out))


def patch_serialized(data: bytes, edits: dict[str, str]) -> tuple[bytes, dict]:
    """在一份 SerializedFile 里替换若干字符串，返回 (新数据, 报告)。

    做法：把「全部对象 + 尾部缓冲」当成一整段来重建。
    改了里面几个字符串后整段变长，于是：
      * 该对象的 byteSize 加上位移
      * 它后面每个对象的 byteStart 都加上位移
      * 头部 file_size、目录里的两条跟着改
    对象数据区前面那段（类型/字段名字符串缓冲）按索引寻址，原地不动。
    """
    lay = parse_layout(data)
    entries = lay["entries"]
    region_abs = lay["data_offset"] + entries[0]["byte_start"]
    region = data[region_abs:lay["file_size"]]

    spans: list[tuple[int, int, str, str]] = []
    for key, new_val in edits.items():
        s, e = value_span(region, key)
        old_val = read_value(region, key)
        if old_val == new_val:
            continue
        spans.append((s, e, old_val, new_val))
    if not spans:
        raise ValueError("没有需要改的字符串")
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if a[1] > b[0]:
            raise ValueError("要改的两段重叠，无法处理")

    # 找出这些字符串属于哪一个对象（相对 region 起点算）
    owner = None
    for i, e in enumerate(entries):
        lo = e["byte_start"] - entries[0]["byte_start"]
        hi = lo + e["byte_size"]
        if all(lo <= s and e2 <= hi for s, e2, _o, _n in spans):
            owner = i
            break
    if owner is None:
        raise ValueError("找不到包含这些字符串的对象")

    # 重建 region
    out = bytearray()
    prev = 0
    changes = []
    for s, e, old_val, new_val in spans:
        out += region[prev:s]
        enc = _encode_field(new_val)
        out += enc
        changes.append((old_val, new_val, e - s, len(enc)))
        prev = e
    out += region[prev:]
    new_region = bytes(out)
    delta = len(new_region) - len(region)
    if delta == 0:
        raise ValueError("长度没变，不该走到这里")

    new_data = bytearray(data[:region_abs] + new_region + data[lay["file_size"]:])

    # 该对象的 byteSize
    struct.pack_into("<I", new_data, entries[owner]["entry_off"] + 12,
                     entries[owner]["byte_size"] + delta)
    # 它后面每个对象的 byteStart
    for e in entries[owner + 1:]:
        struct.pack_into("<I", new_data, e["entry_off"] + 8, e["byte_start"] + delta)
    # 头部 file_size（那四个 u32 恒为大端）
    struct.pack_into(">I", new_data, 4, lay["file_size"] + delta)

    # 安全检查：被改对象之后的尾部里不该出现「某个对象的 byteStart」这类绝对偏移
    tail_blob = new_region[entries[owner]["byte_start"] - entries[0]["byte_start"]
                           + entries[owner]["byte_size"] + delta:]
    warns = []
    for e in entries:
        if struct.pack("<I", e["byte_start"] + delta) in tail_blob:
            warns.append("尾部出现了对象偏移 %d，可能是绝对偏移，需人工确认"
                         % (e["byte_start"] + delta))

    report = {"delta": delta, "new_file_size": lay["file_size"] + delta,
              "owner_index": owner, "owner_id": entries[owner]["path_id"],
              "moved": len(entries) - owner - 1,
              "region_abs": region_abs, "changes": changes, "warnings": warns,
              "layout": lay}
    return bytes(new_data), report


# ==========================================================================
# 打包成 UnityFS
# ==========================================================================
def _lzma_params(stream: bytes) -> tuple[int, int]:
    props = stream[0]
    dict_size = int.from_bytes(stream[1:5], "little")
    return props, dict_size


def _pack_lzma(raw: bytes, props: int, dict_size: int) -> bytes:
    import lzma
    lc = props % 9
    lp = (props // 9) % 5
    pb = props // 45
    filters = [{"id": lzma.FILTER_LZMA1, "lc": lc, "lp": lp, "pb": pb,
                "dict_size": dict_size}]
    body = lzma.compress(raw, format=lzma.FORMAT_RAW, filters=filters)
    return bytes([props]) + dict_size.to_bytes(4, "little") + body \
        + len(raw).to_bytes(8, "little")


def _pack_lz4hc(raw: bytes) -> bytes:
    return lz4.block.compress(raw, mode="high_compression", compression=9,
                              store_size=False)


def build_bundle(src: Bundle, payload: bytes) -> bytes:
    """把新的解压数据按原包的形状重新打包（单块 LZMA + blocksInfo LZ4HC）。"""
    if len(src.blocks) != 1:
        raise ValueError("原包有 %d 个数据块，本工具只会写单块" % len(src.blocks))
    _u, csize, bflags = src.blocks[0]
    block_kind = bflags & 0x3F
    if block_kind != 1:
        raise ValueError("原包数据块不是 LZMA（是 %d），本工具只会写 LZMA" % block_kind)
    if src.compression != 3:
        raise ValueError("原包 blocksInfo 不是 LZ4HC（是 %d）" % src.compression)

    orig_block = src.raw[src.data_offset:src.data_offset + csize]
    props, dict_size = _lzma_params(orig_block)
    comp = _pack_lzma(payload, props, dict_size)

    # 目录：第 0 条是 SerializedFile，其余（.resS）偏移跟着位移
    n_serial = len(payload) - _ress_size(src)
    shift = n_serial - src.directory[0]["size"]
    dirs = []
    for i, e in enumerate(src.directory):
        if i == 0:
            dirs.append((e["name"], e["offset"], n_serial, e["flags"]))
        else:
            dirs.append((e["name"], e["offset"] + shift, e["size"], e["flags"]))

    bi = bytearray()
    if src.version >= 6:
        bi += src.blocks_info_hash
    bi += struct.pack(">I", 1)
    bi += struct.pack(">IIH", len(payload), len(comp), bflags)
    bi += struct.pack(">I", len(dirs))
    for name, off, size, fl in dirs:
        bi += struct.pack(">qqI", off, size, fl)
        bi += name.encode("utf-8") + b"\0"
    comp_bi = _pack_lz4hc(bytes(bi))

    header = (b"UnityFS\0" + struct.pack(">I", src.version)
              + src.unity.encode("utf-8") + b"\0"
              + src.revision.encode("utf-8") + b"\0"
              + struct.pack(">qIII", 0, len(comp_bi), len(bi), src.flags))
    out = bytearray(header + comp_bi + comp)
    struct.pack_into(">q", out, len(header) - 20, len(out))
    return bytes(out)


def _ress_size(src: Bundle) -> int:
    return sum(e["size"] for e in src.directory[1:])


# ==========================================================================
# 对外：给补丁器用
# ==========================================================================
class _RawBundle(Bundle):
    """直接在内存里的字节上构造，不落盘。"""

    def __init__(self, raw: bytes):             # noqa: D107
        self.path = Path("<memory>")
        self.raw = raw
        self._parse()


def patch_bundle_bytes(raw: bytes, edits: dict[str, str]) -> tuple[bytes, dict]:
    """输入整包字节，输出改写后的整包字节。"""
    b = _RawBundle(raw)
    data = b.data()
    new_data, rep = patch_serialized(data, edits)
    return build_bundle(b, new_data), rep


def patch_file(src: Path, dst: Path, edits: dict[str, str]) -> dict:
    out, rep = patch_bundle_bytes(src.read_bytes(), edits)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    rep["out"] = str(dst)
    rep["out_size"] = len(out)
    return rep


# ==========================================================================
# CLI
# ==========================================================================
def _lang_code(path: Path) -> str:
    return path.name[5:] if path.name.startswith("lang-") else path.stem


def _numbers():
    """按文件路径加载 hardcore/_lang/numbers.py。

    不能直接 `import numbers`：那是标准库的同名模块；把 `_lang/` 塞进
    sys.path 又会遮蔽标准库，影响别的依赖。所以按路径加载。
    """
    import importlib.util
    p = HERE / "_lang" / "numbers.py"
    spec = importlib.util.spec_from_file_location("obradinn_lang_numbers", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="原地改写语言包")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect")
    p.add_argument("bundle")

    p = sub.add_parser("verify")
    p.add_argument("bundle")

    p = sub.add_parser("patch")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--level", type=int, required=True)

    sub.add_parser("selftest")

    a = ap.parse_args(argv)

    if a.cmd == "inspect":
        b = Bundle(Path(a.bundle))
        data = b.data()
        lay = parse_layout(data)
        print(b.describe())
        print("SerializedFile: meta=%d file=%d data_offset=%d 对象数据=%d"
              % (lay["meta_size"], lay["file_size"], lay["data_offset"],
                 lay["obj_data_size"]))
        print("对象表 @%d，%d 条（候选 %d 张表，取最靠前且包得住字符串的那张）"
              % (lay["count_off"], len(lay["entries"]), lay["candidates"]))
        for e in lay["entries"]:
            print("   pathID=%-22d start=%-8d size=%-8d typeID=%d"
                  % (e["path_id"], e["byte_start"], e["byte_size"], e["type_id"]))
        print("对象数据区开头占位 %d 字节，末尾余 %d 字节" % (lay["lead"], lay["tail"]))
        print()
        for k in KEYS:
            print("   %-24s = %r" % (k, read_value(data, k)))
        return 0

    if a.cmd == "verify":
        b = Bundle(Path(a.bundle))
        data = b.data()
        print("%s  %d 字节  %s" % (a.bundle, len(b.raw), b.describe()))
        for k in KEYS:
            print("   %-24s = %r" % (k, read_value(data, k)))
        return 0

    if a.cmd == "patch":
        NUM = _numbers()
        src = Path(a.src)
        code = _lang_code(src)
        b = Bundle(src)
        data = b.data()
        edits = {k: NUM.make_value(code, k, a.level, read_value(data, k))
                 for k in KEYS}
        print("语言 %s -> 档位 %d" % (code, a.level))
        for k, v in edits.items():
            print("   %-24s %r" % (k, v))
        rep = patch_file(src, Path(a.dst), edits)
        print()
        print("写出 %s  %d 字节（原 %d，位移 %+d）"
              % (rep["out"], rep["out_size"], src.stat().st_size, rep["delta"]))
        for old, new, was, now in rep["changes"]:
            print("   %r -> %r  (%d -> %d 字节)" % (old, new, was, now))
        for w in rep["warnings"]:
            print("   [!] %s" % w)
        # 自证：读回来
        b2 = Bundle(Path(a.dst))
        d2 = b2.data()
        bad = [k for k in KEYS if read_value(d2, k) != edits[k]]
        print("复读自证：%s" % ("全部对得上 ✓" if not bad else "**对不上** %s" % bad))
        return 0 if not bad else 1

    if a.cmd == "selftest":
        return selftest()
    return 2


def selftest() -> int:
    """拿已知good产物对拍：用原版包改出各档位，和 hardcore/_lang/out/ 里的比。"""
    NUM = _numbers()

    src_dir = HERE / "_lang"
    out_dir = src_dir / "out"
    langs = sorted(p.name[5:] for p in src_dir.glob("lang-*")
                   if not p.name.endswith(".manifest"))
    if not langs:
        print("[X] %s 里没有原版语言包" % src_dir)
        return 1

    fails = 0
    checked = 0
    for code in langs:
        src = src_dir / ("lang-" + code)
        b = Bundle(src)
        data = b.data()
        for lv in (4, 58):
            good = out_dir / ("lv%d" % lv) / ("lang-" + code)
            if not good.is_file():
                continue
            edits = {k: NUM.make_value(code, k, lv, read_value(data, k)) for k in KEYS}
            mine, _rep = patch_bundle_bytes(src.read_bytes(), edits)
            theirs = good.read_bytes()
            same = mine == theirs
            checked += 1
            if not same:
                fails += 1
                print("[!] %-6s lv%-3d 与已知good不一致：我 %d 字节 / 它 %d 字节"
                      % (code, lv, len(mine), len(theirs)))
            else:
                print("[OK] %-6s lv%-3d 与已知good逐字节相同" % (code, lv))

    print()
    print("对拍 %d 例，%d 例不一致" % (checked, fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
