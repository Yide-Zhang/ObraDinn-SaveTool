#!/usr/bin/env python3
"""模拟 FateEditor.UpdateFateGuesses 的「批次登记」规则，验证各难度的批次序列、
可达链、卡死状态，以及切换难度后存档会不会变成玩不出来的状态。

规则出处：css/Assembly-CSharp/FateEditor.cs:5486 起

    list = 已答对(nameId == id) 且 IsCorrectFate 为真、但 markedCorrect 仍为 false 的船员
    num  = 本难度设定的批大小
    if (list.Count >= num) list = list.GetRange(0, num);
    if (list.Count == num) { 这 num 个人的 markedCorrect 置 true; ...成就判定... }

-> 每当「已答对但未登记」的人数达到 num，游戏就**恰好登记 num 个人**。
   num 越大，玩家越久得不到「这几个我答对了」的反馈 -> 越难。

状态量只需要一个：区域内「未登记」人数 U（= GetZoneUnsolvedCount）。
    登记一次 -> U -= num(U)
所以从 U=0 往前推，每个难度的轨迹都是确定的 —— 这就是它的「可达链」。

用法：
    python hardcore/sim_difficulty.py
"""
from __future__ import annotations

import sys

SHIP_TOTAL = 58          # 船上区人数（60 人去掉办公室那 2 个）
OFFICE_TOTAL = 2         # 办公室区人数（d070 章：mate3 / stewcap）

# ------------------------------------------------------------------ 规则
def num_vanilla(u: int) -> int:
    """原版：默认 3，区域内只剩 4 或 2 人未解时改成 2"""
    return 2 if u in (4, 2) else 3


def num_batch(b: int):
    """自定难度：num = min(B, U)

    U < B 时 num 跟着 U 收缩，保证「剩下的人永远能一次性收尾」，
    所以不会出现卡死。B=58 时 U 必须全部答对才登记一次（零反馈）。
    """
    def f(u: int) -> int:
        return min(b, u)
    return f


def num_const(b: int):
    """★ 补丁真正采用的形式：只把常量改成 B，**保留原版那条尾巴**

        num = B;  if (U == 4 || U == 2) num = 2;

    这比 min(B,U) 好补得多 —— 只动一个常量，不需要重写方法体。
    代价是 U < B 且 U ∉ {4,2} 时会凑不齐这一批（例如 B=7 时 U=6），
    这种情况靠「存档向下对齐」来避免，不靠 IL。
    """
    def f(u: int) -> int:
        return 2 if u in (4, 2) else b
    return f


# ★ 实际补丁用的是「只把常量改成 B，保留原版尾巴 U==4||U==2 -> 2」（num_const），
#   不是理想化的 min(B,U)。两者在 4/14/29/58 上恰好等价，但在 6/9 上**不等价**
#   （min 会在 U=4 时直接收尾成 4 人批，常量形式则是 2+2），所以这里以**真实形式**为准。
DIFFICULTIES = [
    ("简单（原难度）", num_vanilla, None),
    ("容易", num_const(4), [4] * 14 + [2]),
    ("中等", num_const(6), [6] * 9 + [2] * 2),
    ("偏高", num_const(9), [9] * 6 + [2] * 2),
    ("较难", num_const(14), [14] * 4 + [2]),
    ("困难", num_const(29), [29] * 2),
    ("硬核", num_const(58), [58]),
]


# ------------------------------------------------------------------ 推演
def chain(start: int, fn, limit: int = 500):
    """从 U=start 出发，返回 (可达链, 每次登记的批大小, 错误信息)"""
    us, steps = [start], []
    u = start
    while u > 0:
        n = fn(u)
        steps.append(n)
        if n <= 0:
            return us, steps, "num=0 但 U=%d 还没解完 -> 永远轮不到登记" % u
        if n > u:
            return us, steps, "num=%d > U=%d -> 人数不够，永远凑不齐这一批" % (n, u)
        u -= n
        us.append(u)
        if len(us) > limit:
            return us, steps, "超过 %d 步仍未收敛" % limit
    return us, steps, None


def summarize(steps) -> str:
    """把批大小列表压成 14 x 4 + 1 x 2 这种形式"""
    out = []
    for n in steps:
        if out and out[-1][0] == n:
            out[-1][1] += 1
        else:
            out.append([n, 1])
    return " + ".join("%d x %d" % (n, c) for n, c in out)


def main() -> int:
    print("=" * 74)
    print("船上区（U 从 %d 出发）" % SHIP_TOTAL)
    print("=" * 74)
    print("%-16s %-28s %s" % ("难度", "批次", "登记后的解对人数（可达链）"))
    print("-" * 74)

    chain_of = {}
    bad = 0
    for name, fn, expect in DIFFICULTIES:
        us, steps, err = chain(SHIP_TOTAL, fn)
        chain_of[name] = us
        mark = ""
        if err:
            mark = "  [X] " + err
            bad += 1
        elif expect is not None:
            mark = "  [OK]" if steps == expect else "  [X] 与预期不符，预期 " + summarize(expect)
            if steps != expect:
                bad += 1
        print("%-16s %-28s %s%s" % (name, summarize(steps),
                                    ",".join(str(x) for x in us), mark))

    print()
    print("=" * 74)
    print("反过来看：每个难度「玩得出来」的解对人数")
    print("=" * 74)
    for name, _fn, _e in DIFFICULTIES:
        # 可达链是 58 -> ... -> 0，解对人数 = 58 - U
        solved = sorted(SHIP_TOTAL - u for u in chain_of[name])
        holes = [x for x in range(SHIP_TOTAL + 1) if x not in set(solved)]
        print("%-16s 可达 %2d 种" % (name, len(solved)))
        print("                 玩得出来: %s" % ",".join(str(x) for x in solved))
        if holes:
            print("                 [X] 玩不出来: %s" % ",".join(str(x) for x in holes))

    # ---------------------------------------------------------- 卡死
    print()
    print("=" * 74)
    print("卡死检查：存在 U 使 num(U) > U（人数凑不齐，这一批永远登记不了）")
    print("=" * 74)
    for name, fn, _e in DIFFICULTIES:
        suck = [u for u in range(1, SHIP_TOTAL + 1) if fn(u) > u]
        reachable = set(chain_of[name])
        fatal = [u for u in suck if u in reachable]
        if not suck:
            print("%-16s 无 [OK]" % name)
        elif not fatal:
            print("%-16s U = %s 凑不齐这一批，但本档可达链不经过 => 实际不会发生 [不影响]"
                  % (name, ",".join(map(str, suck))))
        else:
            print("%-16s [X] U = %s 可达且凑不齐 => 会真卡死"
                  % (name, ",".join(map(str, fatal))))
            bad += 1

    # ---------------------------------------------------------- 办公室
    print()
    print("=" * 74)
    print("办公室区（era=3 时 zone 变成 Office，U 从 %d 出发）" % OFFICE_TOTAL)
    print("=" * 74)
    for name, fn, _e in DIFFICULTIES:
        us, steps, err = chain(OFFICE_TOTAL, fn)
        print("%-16s %-12s %s%s" % (name, summarize(steps),
                                    ",".join(str(x) for x in us),
                                    "  [X] " + err if err else ""))

    # ---------------------------------------------------------- 切档
    print()
    print("=" * 74)
    print("切换难度：一份在 A 档玩到某处的存档，换成 B 档还能不能解完")
    print("=" * 74)
    problems = []
    for an, afn, _ae in DIFFICULTIES:
        for bn, bfn, _be in DIFFICULTIES:
            for u in chain_of[an]:
                if u == 0:
                    continue
                _us, _st, err = chain(u, bfn)
                if err:
                    problems.append((an, bn, u, err))
    if not problems:
        print("所有组合都能解完 [OK]")
    else:
        seen = set()
        for an, bn, u, err in problems:
            key = (an, bn)
            if key in seen:
                continue
            seen.add(key)
            us = [u for a, b, u, _e in problems if (a, b) == key]
            print("[!] %s -> %s: 这些剩余人数在新档凑不齐一批 -> %s" % (an, bn, us))
        print()
        print("★ 这是设计里已记录的「存档向下对齐」需求，**不算缺陷**：")
        print("  同一档位内 U 只会按批大小递减，永远落在该档可达链上；")
        print("  只有**中途切档**才会出现 U 不在新链上的情况，")
        print("  由玩家侧补丁器负责对齐（或提示玩家）。")

    # ---------------------------------------------------------- 补丁形式对比
    print()
    print("=" * 74)
    print("补丁形式对比：min(B,U) 与「只改常量 B + 保留原版尾巴」是否等价")
    print("=" * 74)
    print("%-16s %-24s %-24s %s" % ("难度", "min(B,U)", "常量 B + 原版尾巴", "判定"))
    print("-" * 74)
    batch_of = {"容易": 4, "中等": 6, "偏高": 9, "较难": 14, "困难": 29, "硬核": 58}
    same_all = True
    for name, _fn, _e in DIFFICULTIES:
        if name not in batch_of:
            continue
        b = batch_of[name]
        a_us, a_st, a_err = chain(SHIP_TOTAL, num_batch(b))
        c_us, c_st, c_err = chain(SHIP_TOTAL, num_const(b))
        ok = (not a_err) and (not c_err) and a_st == c_st and a_us == c_us
        same_all = same_all and ok
        print("%-16s %-24s %-24s %s" % (name, summarize(a_st), summarize(c_st),
                                        "[OK] 一致" if ok else "[X] 不一致"))
    print()
    if same_all:
        print("★ 两种形式在六个自定档位上完全等价 -> 补丁只需改一个常量，不必重写方法体")
    else:
        print("★ 不完全等价（上面标 [X] 的档位不同）——**以「常量 + 原版尾巴」为准**，"
              "补丁仍然只改一个常量；差异只是收尾批的切分方式，不影响能否解完。")

    print()
    print("=" * 74)
    print("结论：%s" % ("全部通过" if not bad else "有 %d 处问题" % bad))
    print("=" * 74)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
