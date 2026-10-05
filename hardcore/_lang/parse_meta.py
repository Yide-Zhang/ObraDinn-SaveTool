#!/usr/bin/env python3
"""结构化解析 SerializedFile 的元数据区（头 + 类型表 + 对象表 + 字符串缓冲）。

能不能安全改写语言包，取决于这张表能不能可靠地解出来。这个脚本用一条强自证
来确认：**按格式解完元数据后，算出的结束位置必须正好等于头部里的 data_offset**。
对不上就说明格式理解错了，绝不能拿它去改写文件。

已知的实测事实（见 probe_assets.py 的输出）：
  * 头部那 4 个 u32（metadata_size / file_size / version / data_offset）**恒为大端**，
    这是 Unity 的历史遗留：即使文件本身是小端，这四个也写成大端。
  * 其余字段用文件自己的字节序（实测本游戏 14 个包都是小端）
  * 对象数据区是小端（字符串 = int32 小端长度 + 内容 + 对齐到 4）

用法：
    python hardcore/_lang/parse_meta.py hardcore/_lang/lang-en
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from hardcore.lang_bundle import Bundle  # noqa: E402

CLASS_NAMES = {1: "GameObject", 4: "Transform", 28: "Texture2D", 43: "Mesh",
               48: "Shader", 49: "TextAsset", 83: "AudioClip", 114: "MonoBehaviour",
               128: "Font", 142: "AssetBundle", 213: "Sprite", 115: "MonoScript",
               21: "Material", 74: "AnimationClip", 156: "Prefab"}


class ParseError(Exception):
    pass


def parse(data: bytes, e: str = "<") -> dict:
    # 这四个恒为大端（Unity 的历史遗留），与文件字节序无关
    meta_size, = struct.unpack_from(">I", data, 0)
    file_size, = struct.unpack_from(">I", data, 4)
    version, = struct.unpack_from(">I", data, 8)
    data_offset, = struct.unpack_from(">I", data, 12)

    p = 16
    endian = data[p]
    p += 4                                   # endianness + 3 字节保留

    end = data.index(b"\0", p)
    unity_version = data[p:end].decode("ascii", "replace")
    p = end + 1

    target_platform, = struct.unpack_from(e + "i", data, p)
    p += 4
    enable_type_tree = data[p]
    p += 1

    type_count, = struct.unpack_from(e + "I", data, p)
    p += 4
    if not 0 < type_count < 4096:
        raise ParseError("类型数不合理: %d" % type_count)

    types = []
    for _ in range(type_count):
        class_id, = struct.unpack_from(e + "i", data, p)
        p += 4
        is_stripped = data[p]
        p += 1
        script_type_index, = struct.unpack_from(e + "h", data, p)
        p += 2
        script_id = None
        if class_id < 0:
            script_id = data[p:p + 16]
            p += 16
        old_type_hash = data[p:p + 16]
        p += 16
        node_count = 0
        tree_end = p
        if enable_type_tree and not is_stripped:
            node_count, = struct.unpack_from(e + "I", data, p)
            p += 4
            if node_count > 65536:
                raise ParseError("TypeTree 节点数不合理: %d" % node_count)
            tree_end = p + node_count * 24    # v17 每个节点 24 字节（无 refTypeHash）
            p = tree_end
        types.append({"class_id": class_id, "stripped": bool(is_stripped),
                      "script_type_index": script_type_index,
                      "nodes": node_count, "tree_start": tree_end - node_count * 24,
                      "tree_end": tree_end, "script_id": script_id,
                      "name": CLASS_NAMES.get(class_id, "?")})

    obj_count, = struct.unpack_from(e + "I", data, p)
    p += 4
    if not 0 < obj_count < 65536:
        raise ParseError("对象数不合理: %d" % obj_count)

    objects = []
    obj_table_start = p
    for _ in range(obj_count):
        path_id, = struct.unpack_from(e + "q", data, p)
        byte_start, = struct.unpack_from(e + "I", data, p + 8)
        byte_size, = struct.unpack_from(e + "I", data, p + 12)
        type_id, = struct.unpack_from(e + "i", data, p + 16)
        p += 20
        objects.append({"path_id": path_id, "byte_start": byte_start,
                        "byte_size": byte_size, "type_id": type_id,
                        "entry_off": p - 20})

    script_count, = struct.unpack_from(e + "I", data, p)
    p += 4
    if script_count:
        raise ParseError("有 %d 个 script type，尚未支持" % script_count)

    ext_count, = struct.unpack_from(e + "I", data, p)
    p += 4
    externals = []
    for _ in range(ext_count):
        tmp = data.index(b"\0", p)
        path = data[p:tmp].decode("utf-8", "replace")
        p = tmp + 1
        p = (p + 3) & ~3                       # 对齐
        guid = data[p:p + 16]
        p += 16
        etype, = struct.unpack_from(e + "i", data, p)
        p += 4
        externals.append({"path": path, "type": etype})

    ref_count, = struct.unpack_from(e + "I", data, p)
    p += 4
    p += ref_count * 20                        # refTypes：每条 20 字节

    # userInformation（v17 有）：cstr
    tmp = data.index(b"\0", p)
    user_info = data[p:tmp].decode("utf-8", "replace")
    p = tmp + 1

    meta_end_aligned = (p + 3) & ~3

    return {"metadata_size": meta_size, "file_size": file_size, "version": version,
            "data_offset": data_offset, "endian": endian, "unity_version": unity_version,
            "platform": target_platform, "type_tree": bool(enable_type_tree),
            "types": types, "objects": objects, "externals": externals,
            "user_info": user_info, "meta_end": p,
            "meta_end_aligned": meta_end_aligned, "obj_table_start": obj_table_start,
            "parsed_end": p}


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "hardcore/_lang/lang-en")
    data = Bundle(path).data()

    print("第 0~47 字节：")
    print("  " + " ".join("%02x" % c for c in data[:48]))
    print()

    r = None
    for cand_e, tag in ((">", "大端"), ("<", "小端")):
        try:
            cand = parse(data, cand_e)
        except (ParseError, ValueError, struct.error) as exc:
            print("  %s：解析失败 —— %s" % (tag, exc))
            continue
        ok = (cand["meta_end_aligned"] == cand["data_offset"])
        print("  %s：类型 %d 条 / 对象 %d 条 / 解完位置 %d vs data_offset %d -> %s"
              % (tag, len(cand["types"]), len(cand["objects"]),
                 cand["meta_end_aligned"], cand["data_offset"],
                 "自证通过 ✓" if ok else "对不上"))
        if ok and r is None:
            cand["used_e"] = cand_e
            r = cand
    print()
    if r is None:
        print("[X] 两种字节序都没能自证，格式理解有误，不再往下走。")
        return 1
    print("采用 %s 的那次解析继续。" % ("大端" if r["used_e"] == ">" else "小端"))

    print("=" * 76)
    print("头部")
    print("  metadata_size   : %d" % r["metadata_size"])
    print("  file_size       : %d" % r["file_size"])
    print("  version         : %d" % r["version"])
    print("  data_offset     : %d" % r["data_offset"])
    print("  endianness byte : %s" % r["endian"])
    print("  实际按哪种序解 : %s" % r["used_e"])
    print("  unity version   : %s" % r["unity_version"])
    print("  target platform : %d" % r["platform"])
    print("  enableTypeTree  : %s" % r["type_tree"])
    print()
    print("=" * 76)
    print("类型表 %d 条" % len(r["types"]))
    for i, t in enumerate(r["types"]):
        print("  [%d] classID=%-5d %-14s stripped=%-5s nodes=%-4d tree=[%d,%d)"
              % (i, t["class_id"], t["name"], t["stripped"], t["nodes"],
                 t["tree_start"], t["tree_end"]))
    print()
    print("=" * 76)
    print("对象表 %d 条（表起点 %d）" % (len(r["objects"]), r["obj_table_start"]))
    for i, o in enumerate(r["objects"]):
        line = ("  [%d] pathID=%-22d byteStart=%-8d byteSize=%-8d typeID=%d"
                % (i, o["path_id"], o["byte_start"], o["byte_size"], o["type_id"]))
        hits = 15692 <= o["byte_start"] and 15692 < o["byte_start"] + o["byte_size"]
        print(line + ("   <- 四个字符串落在这个对象里" if hits else ""))
    print()
    print("=" * 76)
    print("外部引用 %d 条" % len(r["externals"]))
    for e in r["externals"]:
        print("  %s (type=%d)" % (e["path"], e["type"]))
    print("userInformation : %r" % r["user_info"])
    print()
    print("=" * 76)
    print("自证：解完元数据后的位置 %d，对齐后 %d，头部里的 data_offset %d  ->  %s"
          % (r["meta_end"], r["meta_end_aligned"], r["data_offset"],
             "一致 ✓ 解析可信" if r["meta_end_aligned"] == r["data_offset"]
             else "**不一致 ✗ 解析不可信**"))

    # 对象数据区的范围与末尾字符串缓冲
    objs = r["objects"]
    if objs:
        first = min(o["byte_start"] for o in objs)
        last_end = max(o["byte_start"] + o["byte_size"] for o in objs)
        print()
        print("对象数据区 : 起点 %d（data_offset %d）  最末对象结束于 %d"
              % (first, r["data_offset"], last_end))
        print("文件长度 %d -> 末尾还剩 %d 字节（v17 的类型/字段名字符串缓冲就在这里）"
              % (r["file_size"], r["file_size"] - last_end))

    # 打印尾部字符串缓冲里的可读内容位置，便于确认
    tail = data[7168:r["file_size"]] if r["file_size"] > 7168 else b""
    print()
    print("对象数据区之后的可见 ASCII 串（前 20 个）：")
    runs = []
    i = 0
    while i < len(tail) and len(runs) < 20:
        if 32 <= tail[i] < 127:
            j = i
            while j < len(tail) and (32 <= tail[j] < 127):
                j += 1
            if j - i >= 4:
                runs.append((7168 + i, tail[i:j].decode("ascii")))
            i = j
        else:
            i += 1
    for off, s in runs:
        print("   @%-7d %r" % (off, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
