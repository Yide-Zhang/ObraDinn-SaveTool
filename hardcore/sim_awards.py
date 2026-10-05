#!/usr/bin/env python3
"""验证：把批大小从 3 改成任意档位后，成就还能不能正常触发。

出处：css/Assembly-CSharp/FateEditor.cs:697-712

    int before = SaveData.it.GetNumFatesCorrect();        // 登记前
    foreach (id in list) SaveData.it.face[id].markedCorrect = true;   // 本批一起置位
    int after  = SaveData.it.GetNumFatesCorrect();        // 登记后
    if (before <  6 && after >=  6) Awards.Give(Awards.Id.Any6);      // Id 1
    if (before < 15 && after >= 15) Awards.Give(Awards.Id.Any15);     // Id 2
    if (before < 30 && after >= 30) Awards.Give(Awards.Id.Any30);     // Id 3
    if (before < 45 && after >= 45) Awards.Give(Awards.Id.Any45);     // Id 4

★ 关键点：`GetNumFatesCorrect()` 数的是 `markedCorrect`（SaveData.cs:131），
  也就是**已登记**的正确下落数 —— 每次登记后它精确 +num。

★ 判定形式是**跨阈值**（before < N <= after），不是「本次增量里包含 N」。
  因为累计数单调递增且每批都是连续的一段，所以只要最终 ≥ N，
  就必然**恰好有一批**满足 before < N <= after —— 与批大小无关。
  原版 3 能整除 6/15/30/45，只是恰好每批都踩在阈值上，看起来像「按 3 触发」。

另外两处成就与此无关：
  - 章回成就 ChapterSolved*：每个 disaster 各自 `!hadBefore && hasAfter`（FateEditor.cs:687-695），
    一批解完多章时会把它们**全部**发出去，不会漏。
  - 结局成就 GoodEnding/BadEnding/KillerCaptain：在 OfficeLogic / TallyInsurance 里，与批大小无关。

用法：
    python hardcore/sim_awards.py
"""
from __future__ import annotations

import sys

from sim_difficulty import OFFICE_TOTAL, SHIP_TOTAL, chain, num_const, summarize

TOTAL = SHIP_TOTAL + OFFICE_TOTAL          # 60，= Manifest.crewCount
THRESHOLDS = [(6, "Any6"), (15, "Any15"), (30, "Any30"), (45, "Any45")]

LEVELS = [
    ("简单（原版 3）", 3),
    ("容易（4）", 4),
    ("中等（6）", 6),
    ("偏高（9）", 9),
    ("较难（14）", 14),
    ("困难（29）", 29),
    ("硬核（58）", 58),
]

# 每档「船上区」的批次序列（sim_difficulty.py 已单独验证过）
EXPECT = {
    3: [3] * 18 + [2] * 2,
    4: [4] * 14 + [2],
    6: [6] * 9 + [2] * 2,
    9: [9] * 6 + [2] * 2,
    14: [14] * 4 + [2],
    29: [29] * 2,
    58: [58],
}


def walk(b: int):
    """走完两个区的完整批次链。

    返回 (每批 (before, after) 列表, 错误, 最终登记数)
    船上区（58 人）-> 办公室区（2 人），before 跨区连续累加。
    """
    pairs, err, before = [], None, 0
    for zone_total in (SHIP_TOTAL, OFFICE_TOTAL):
        _us, steps, e = chain(zone_total, num_const(b))
        if e:
            return pairs, e, before
        for n in steps:
            after = before + n
            pairs.append((before, after))
            before = after
    return pairs, None, before


def main() -> int:
    print("=" * 84)
    print("成就验证：Any6 / Any15 / Any30 / Any45（Awards.Id = 1 / 2 / 3 / 4）")
    print("判定出处 FateEditor.cs:697-712 —— 跨阈值 before < N <= after")
    print("=" * 84)
    print()

    bad = 0
    for name, b in LEVELS:
        pairs, err, final = walk(b)
        steps = [a - p for p, a in pairs]
        print("%-14s 批大小 %2d   批次 %s" % (name, b, summarize(steps)))

        if err:
            print("   [X] %s" % err)
            bad += 1
            print()
            continue

        ship = steps[:len(steps) - 1] if b != 58 else steps[:-1]
        want = EXPECT.get(b)
        if want is not None and ship != want:
            print("   [X] 船上区批次与规格不符，预期 %s" % summarize(want))
            bad += 1

        if final != TOTAL:
            print("   [X] 最终登记 %d != 总人数 %d"
                  " -> OfficeLogic.CheckVictory 的等号判定会失败" % (final, TOTAL))
            bad += 1
        else:
            print("   最终登记 %d / %d  [OK]" % (final, TOTAL))

        cells = []
        for th, nm in THRESHOLDS:
            hit = [(p, a) for p, a in pairs if p < th <= a]
            if len(hit) == 1:
                cells.append("%s %2d->%-2d OK" % (nm, hit[0][0], hit[0][1]))
            elif not hit:
                cells.append("%s [X] 从未跨过" % nm)
                bad += 1
            else:
                cells.append("%s [X] 跨过 %d 次" % (nm, len(hit)))
                bad += 1
        print("   " + " | ".join(cells))
        print()

    print("=" * 84)
    if bad:
        print("结论：有 %d 处问题" % bad)
    else:
        print("结论：四个成就全部能在六个档位下触发；最终登记数恒为 %d" % TOTAL)
    print("=" * 84)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
