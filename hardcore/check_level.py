#!/usr/bin/env python3
"""从 Assembly-CSharp.dll 里认出「当前游戏难度（组数量）」。

原理（`hardcore/DESIGN.md` 第 1 节）：
    FateEditor.UpdateFateGuesses 里那句 `int num = 3;`
    对应的 IL 就是一条 ldc.i4.3 —— 那一个字节就是批大小。
    把它改成别的值就等于换档。

定位方式：先用**锚点字节序列**找到那段代码，再从锚点往前解析出常量指令
（ldc.i4.X / ldc.i4.s / ldc.i4 三种形态长度不同，都要认）。
写死绝对偏移在游戏更新后会失效，锚点至少能保证「找错了就报错」，
而不是安静地读一个无关的数。

本脚本**只读**，不动 DLL。

用法：
    python hardcore/check_level.py                      # 用下面默认的游戏路径
    python hardcore/check_level.py <Assembly-CSharp.dll>
    python hardcore/check_level.py <dll> --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_DLL = Path(r"F:\AceAttorneySeries\gameFiles\steamapps\common\ObraDinn"
                   r"\ObraDinn_Data\Managed\Assembly-CSharp.dll")

# 常量所在位置的锚点（0x065BD6 起 12 字节，见 _dump 里的原始字节）。
#                                        ↓ 这个 1a 是「U == 4」的比较，不是批大小
ANCHOR = bytes.fromhex("11 06 1a 3b 08 00 00 00 11 06 18 40")

# 锚点前面紧挨着的是 `stloc.s V_7`（2 字节），所以常量指令的**结束**位置 = 锚点 - 2。
# 三种 ldc 形态长度不同，从结束位置往前试。
CONST_END_FROM_ANCHOR = 2

LEVELS = {
    3: "简单（原难度）",
    4: "容易",
    6: "中等",
    9: "偏高",
    14: "较难",
    29: "困难",
    58: "硬核",
}

# 动画补丁的两个观察点（Book.RevealCorrectGuesses）
ANIM_BRANCH_OFF = 0x05AB69      # 原版 0x40 (bne.un) -> 补丁后 0x38 (br)，让 2 元素数组变死代码
ANIM_INDEX_OFF = 0x05AE15       # ldelem.ref；补丁会在它前面插入 ldc.i4.3 / rem

# 盖章步进间隔（Book.RevealCorrectGuesses 末尾那个 for 循环里 MakeFunc 的时长）
#   原版  : ldc.r4 1.2 写死，循环 Count-1 次 ⇒ 总时长随人数线性增长（3 人 2.4s / 4 人 3.6s）
#   补丁后: ldc.r4 2.4 / ldarg.1 / callvirt get_Count / ldc.i4.1 / sub / conv.r4 / div
#           ⇒ 2.4f/(Count-1)，总时长恒定 2.4s
# 元数据 token 会被 Cecil 重排，所以 token 位用通配；前后用 newobj(Func::.ctor) 与
# ldnull+call 卡住，避免撞上别的方法里同值的 1.2f。
# ⚠ 字节备忘：`div` = 0x5B（**不是** 0x6C，0x6C 是 conv.r8）；`conv.r4` = 0x6B；
#   `sub` = 0x59；`ldc.i4.1` = 0x17；`ldnull` = 0x14；`ldarg.1` = 0x03。
_TOKEN4 = rb"[\x00-\xff]{4}"
SEAL_VANILLA_RE = re.compile(rb"\x73" + _TOKEN4 + rb"\x22\x9a\x99\x99\x3f\x14\x28")
SEAL_PATCHED_RE = re.compile(rb"\x73" + _TOKEN4 + rb"\x22\x9a\x99\x19\x40\x03\x6f"
                             + _TOKEN4 + rb"\x17\x59\x6b\x5b\x14\x28")


def parse_const(buf: bytes, anchor: int):
    """从锚点往前解析 ldc 常量。返回 (值, 指令长度, 形态)；认不出来返回 None。"""
    end = anchor - CONST_END_FROM_ANCHOR        # 常量指令的结束（不含）

    # ldc.i4 <int32>：5 字节，指令首字节是 0x20
    if end >= 5 and buf[end - 5] == 0x20:
        return int.from_bytes(buf[end - 4:end], "little", signed=True), 5, "ldc.i4"
    # ldc.i4.s <int8>：2 字节，首字节 0x1F
    if end >= 2 and buf[end - 2] == 0x1F:
        return int.from_bytes(buf[end - 1:end], "little", signed=True), 2, "ldc.i4.s"
    # ldc.i4.0 ~ ldc.i4.8：1 字节，0x16..0x1E
    if end >= 1 and 0x16 <= buf[end - 1] <= 0x1E:
        v = buf[end - 1] - 0x16
        return v, 1, "ldc.i4.%d" % v
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dll", nargs="?", default=str(DEFAULT_DLL))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    p = Path(a.dll)
    if not p.exists():
        print("[X] 找不到 " + str(p))
        return 2

    buf = p.read_bytes()
    report = {
        "file": str(p),
        "bytes": len(buf),
        "sha256": hashlib.sha256(buf).hexdigest(),
    }

    # ---------------------------------------------------------- 批大小
    hits = []
    start = 0
    while True:
        i = buf.find(ANCHOR, start)
        if i < 0:
            break
        hits.append(i)
        start = i + 1
    report["anchor_hits"] = hits

    if len(hits) != 1:
        print("[X] 锚点命中 %d 次（应为 1 次）" % len(hits))
        print("    这说明这份 DLL 不是已知版本，或者已经被别的工具改过。")
        print("    按设计（只认已验证版本），这种情况直接拒绝，不做猜测。")
        if hits:
            for h in hits[:5]:
                print("    命中于 0x%06X" % h)
        return 1

    anchor = hits[0]
    parsed = parse_const(buf, anchor)
    if parsed is None:
        print("[X] 锚点前不是可识别的 ldc 常量指令，拒绝判断")
        print("    锚点 0x%06X，前面 16 字节:" % anchor)
        print("    " + buf[anchor - 16:anchor].hex(" "))
        return 1

    num, ins_len, form = parsed
    const_off = anchor - CONST_END_FROM_ANCHOR - ins_len
    report["num"] = num
    report["num_form"] = form
    report["num_offset"] = const_off
    report["level"] = LEVELS.get(num, "未知（不是标准档位）")

    # ---------------------------------------------------------- 动画补丁
    # 不用绝对偏移：Cecil 重排后偏移会变，macOS 的 DLL 也不同。
    # B2 站点：ldelem.ref(0x9A) 前面是 ldarg.0/ldloc.2/ldloc.1 —— 补丁会在中间插
    #          ldc.i4.3(0x19) / rem(0x5D)。注意 ldc.i4.3 = 0x19（0x18 是 ldc.i4.2）。
    patched_sig = bytes.fromhex("02 08 07 19 5d 9a")
    vanilla_sig = bytes.fromhex("02 08 07 9a")

    def count_occurrences(needle: bytes) -> list:
        out, i = [], buf.find(needle)
        while i >= 0:
            out.append(i)
            i = buf.find(needle, i + 1)
        return out

    idx_state, idx_ldelem = "认不出", -1
    hits_p = count_occurrences(patched_sig)
    hits_v = count_occurrences(vanilla_sig) if not hits_p else []
    if len(hits_p) == 1:
        idx_state, idx_ldelem = "已补", hits_p[0] + 5
    elif len(hits_v) == 1:
        idx_state, idx_ldelem = "原版", hits_v[0] + 3
    elif hits_p or hits_v:
        idx_state = "认不出（命中多次）"

    # B1 站点标识：方法里「ldc.i4.2 + 条件分支」有三处（数组分支 + welldoneId 里两个
    # `Count != 2`），所以不能只靠「往前扫最近的匹配」。用**语义判别**：
    # 这个分支的**目标**必须是 `ldc.i4.3; newarr`（3 元素数组的构造处）。
    #   原版 = 0x40 (bne.un)，补丁后 = 0x38 (br)；两者都是 5 字节长形态，后面 4 字节是偏移。
    branch_off, branch_byte = -1, -1
    if idx_ldelem > 0:
        for k in range(idx_ldelem, max(8, idx_ldelem - 2048), -1):
            if buf[k] not in (0x38, 0x40) or buf[k - 1] != 0x18 or buf[k - 6] != 0x6F:
                continue
            offset = int.from_bytes(buf[k + 1:k + 5], "little", signed=True)
            target = k + 5 + offset
            if 0 <= target + 1 < len(buf) and buf[target] == 0x19 and buf[target + 1] == 0x8D:
                branch_off, branch_byte = k, buf[k]
                break

    anim = {
        "branch_offset": branch_off,
        "branch_byte": ("0x%02x" % branch_byte) if branch_byte >= 0 else "--",
        "branch_patched": branch_byte == 0x38,
        "index_state": idx_state,
        "index_ldelem_offset": idx_ldelem,
    }
    report["anim"] = anim

    # ---------------------------------------------------------- 盖章步进间隔（C）
    seal_patched_hits = SEAL_PATCHED_RE.findall(buf)
    seal_vanilla_hits = [] if seal_patched_hits else SEAL_VANILLA_RE.findall(buf)
    if seal_patched_hits:
        seal_state = "已补"
        seal_off = SEAL_PATCHED_RE.search(buf).start()
    elif len(seal_vanilla_hits) == 1:
        seal_state = "原版"
        seal_off = SEAL_VANILLA_RE.search(buf).start()
    else:
        seal_state = "认不出"
        seal_off = -1
    anim["seal_state"] = seal_state
    anim["seal_offset"] = seal_off
    anim["seal_vanilla_hits"] = len(seal_vanilla_hits) + (0 if seal_patched_hits else 0)
    anim["seal_patched_hits"] = len(seal_patched_hits)

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("=" * 70)
    print("文件   : " + report["file"])
    print("大小   : %d bytes" % report["bytes"])
    print("sha256 : " + report["sha256"])
    print("=" * 70)
    print("批大小常量 : %d   （%s，文件偏移 0x%06X）" % (num, form, const_off))
    print("当前难度   : %s" % report["level"])
    if num not in LEVELS:
        print("             ^ 不是六个标准档位之一，可能被别的工具改过")
    print()
    print("动画补丁状态（Book.RevealCorrectGuesses）：")
    if anim["branch_offset"] >= 0:
        print("  [%s] 2 元素数组分支  @0x%06X = %s（补丁后应为 0x38=br）"
              % ("OK" if anim["branch_patched"] else "--",
                 anim["branch_offset"], anim["branch_byte"]))
    else:
        print("  [X] 2 元素数组分支  找不到分支现场，无法判断")
    if anim["index_ldelem_offset"] >= 0:
        print("  [%s] 音效索引取模    ldelem.ref @0x%06X，状态：%s"
              % ("OK" if anim["index_state"] == "已补" else "--",
                 anim["index_ldelem_offset"], anim["index_state"]))
    else:
        print("  [X] 音效索引取模    找不到 ldelem.ref 现场，无法判断")
    if anim["seal_offset"] >= 0:
        print("  [%s] 盖章步进间隔    @0x%06X，状态：%s（补丁后 = 2.4f/(Count-1)，总时长恒定 2.4s）"
              % ("OK" if anim["seal_state"] == "已补" else "--",
                 anim["seal_offset"], anim["seal_state"]))
    else:
        print("  [X] 盖章步进间隔    认不出（原版命中 %d 次 / 补丁命中 %d 次）"
              % (anim["seal_vanilla_hits"], anim["seal_patched_hits"]))
    print()
    all_patched = (anim["branch_patched"] and anim["index_state"] == "已补"
                   and anim["seal_state"] == "已补")
    all_vanilla = (num == 3 and not anim["branch_patched"]
                   and anim["index_state"] != "已补" and anim["seal_state"] == "原版")
    if all_vanilla:
        print("=> 完全是原版（未打补丁）")
    elif num != 3 and all_patched:
        print("=> 已打补丁，难度 = %s" % report["level"])
    else:
        print("=> 状态不一致：常量与动画补丁对不上，需要人工核实")
    return 0


if __name__ == "__main__":
    sys.exit(main())
