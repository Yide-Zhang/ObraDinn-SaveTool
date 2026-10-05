#!/usr/bin/env python3
"""存档难度对齐 —— 换档后保证玩家仍然能通关。

问题
----
补丁只把常量改成 B，**保留原版尾巴** `if (U == 4 || U == 2) num = 2;`。于是：

    同一档位内：U 只会按 num(U) 递减 -> U 永远落在该档的可达链上 -> 一定能解完
    中途换档  ：U 可能落在新档链外 -> 凑不齐一批 -> **永远登记不了**（卡死）

例：U=7（简单链上）换成硬核(58) -> 需要 58 人才登记一次，永远凑不齐。

对齐规则（用户定义）
------------------
    高难 -> 低难：找出玩家**当前所有填对的**人，取「≤ 该数目的、低难可达的最大值」，
                 把这些人置 markedCorrect。
    低难 -> 高难：同理取高难可达的最大值；**其余恢复为未验证（markedCorrect=false）**。

两者可以统一成一句话：

    target = 新档可达值中 ≤ 填对数 的最大者
    恰好 target 个人 markedCorrect = true，其余 false

为了尽量少动玩家进度，选人时**优先保留原本已经 marked 的**。
注意只改 `markedCorrect`，**不动玩家填的下落**（nameId / fateId），所以推理信息不丢。

对齐之后 U = 区域人数 − target 必然落在新档可达链上，脚本会**模拟验证**。

用法
----
    python hardcore/align_save.py <存档> --level 6                    # 预览（不改文件）
    python hardcore/align_save.py <存档> --level 6 --out 新存档        # 写出新档
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from make_envelope_save import build_zones, load_save, save_save      # noqa: E402
from make_hardcore_edge import set_face                              # noqa: E402
from make_test_save import crew_fates, face_attr                     # noqa: E402
from sim_difficulty import chain, num_const                          # noqa: E402

LEVEL_NAMES = {3: "简单（原版）", 4: "容易", 6: "中等", 9: "偏高",
               14: "较难", 29: "困难", 58: "硬核"}
ZONES = (("船上区", "Ship"), ("办公室区", "Office"))


def reachable_marked(zone_size: int, level: int) -> set[int] | None:
    """该档在该区域里「已登记人数」的所有可达值。认不出返回 None。"""
    us, _steps, err = chain(zone_size, num_const(level))
    if err:
        return None
    return {zone_size - u for u in us}


def zone_marked(xml: str, zone) -> int:
    """这个区域里当前「已登记」的人数。"""
    return sum(1 for c in zone if face_attr(xml, c, "markedCorrect") == "true")


def compatible_levels(xml: str) -> set[int]:
    """这份存档在哪些档位下**还能通关**。

    判据和「对齐」用的是同一套链：每个区域的「已登记人数」都要落在该档的可达值里 ——
    落在链外就意味着永远凑不齐一批、登记不了（卡死）。
    刚开局的存档 0 登记对每一档都可达，所以不会误报。
    """
    _crew, ship, office = build_zones()
    out: set[int] = set()
    for lv in LEVEL_NAMES:
        ok = True
        for zone in (ship, office):
            reach = reachable_marked(len(zone), lv)
            if reach is None or zone_marked(xml, zone) not in reach:
                ok = False
                break
        if ok:
            out.add(lv)
    return out


def is_correct(xml: str, cid: str, fates: dict) -> bool:
    """复刻游戏判定：身份填对 + 下落填对（不看 markedCorrect）"""
    return (face_attr(xml, cid, "nameId") == cid
            and face_attr(xml, cid, "fateId") in fates.get(cid, []))


def align(xml: str, level: int, fates: dict, dry: bool) -> tuple[str, bool]:
    _crew, ship, office = build_zones()
    ok = True

    for label, zone in (("船上区", ship), ("办公室区", office)):
        correct = [c for c in zone if is_correct(xml, c, fates)]
        marked = [c for c in zone if face_attr(xml, c, "markedCorrect") == "true"]

        reach = reachable_marked(len(zone), level)
        if reach is None:
            print("  [X] %s：算不出该档可达链" % label)
            return xml, False

        cands = sorted(r for r in reach if r <= len(correct))
        target = cands[-1] if cands else 0

        # 优先保留原本已 marked 的（少改动玩家进度）
        pool = ([c for c in correct if c in marked]
                + [c for c in correct if c not in marked])
        chosen = set(pool[:target])

        # 对齐后能不能解完：U = 人数 - target 必须在可达链上
        u_after = len(zone) - target
        _us, _st, err = chain(u_after, num_const(level))
        completable = err is None

        print("  %s（%d 人）" % (label, len(zone)))
        print("    填对 %d 人 / 当前已登记 %d 人" % (len(correct), len(marked)))
        print("    该档可达的「已登记人数」: %s"
              % ", ".join(str(x) for x in sorted(reach, reverse=True)))
        print("    -> target = %d（≤ 填对数 %d 的最大可达值）" % (target, len(correct)))
        print("    登记后剩余 U = %d  ->  %s"
              % (u_after, "能解完 [OK]" if completable else "解不完 [X]"))
        if not completable:
            ok = False

        if not dry:
            for c in zone:
                want = "true" if c in chosen else "false"
                if face_attr(xml, c, "markedCorrect") != want:
                    xml, hit = set_face(xml, c, markedCorrect=want)
                    if hit != 1:
                        print("    [X] %s 的 <face> 命中 %d 次" % (c, hit))
                        return xml, False
        print("    将置 true: %d 人；置 false: %d 人"
              % (len(chosen), len(zone) - len(chosen)))
        print()

    return xml, ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("save")
    ap.add_argument("--level", type=int, required=True, help="换到的档位（3/4/6/9/14/29/58）")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.level not in LEVEL_NAMES:
        print("[X] 不是标准档位: %d" % a.level)
        return 2

    src = Path(a.save)
    text, xml = load_save(src)
    fates = crew_fates()

    era = re.search(r"<general\b[^>]*?\bera=\"(\d+)\"", xml)
    era = int(era.group(1)) if era else -1
    marked_before = sum(1 for c in re.findall(r"<face\b[^>]*?/>", xml)
                        if 'markedCorrect="true"' in c)

    print("=" * 78)
    print("存档   : %s" % src)
    print("era    : %d   （%s）" % (era, "办公室" if era == 3 else "船上"))
    print("目标档 : %d = %s" % (a.level, LEVEL_NAMES[a.level]))
    print("当前已登记：%d 人" % marked_before)
    print("=" * 78)
    print()

    xml2, ok = align(xml, a.level, fates, dry=a.out is None)

    if a.out is None:
        print("（预览模式：未写文件。加 --out 才会写出）")
        return 0 if ok else 1

    dst = Path(a.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    save_save(text, xml2, dst)

    _t, x3 = load_save(dst)
    marked_after = sum(1 for c in re.findall(r"<face\b[^>]*?/>", x3)
                       if 'markedCorrect="true"' in c)
    print("写出 %s  %d bytes  sha256_16 %s"
          % (dst, dst.stat().st_size, hashlib.sha256(dst.read_bytes()).hexdigest()[:16]))
    print("复查已登记：%d -> %d 人" % (marked_before, marked_after))
    print("结论：%s" % ("对齐后可以通关" if ok else "有问题，需要人工看"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
