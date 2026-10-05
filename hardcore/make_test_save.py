#!/usr/bin/env python3
"""造「刚好卡在阈值上」的测试存档，以及检测任意存档的 pending 情况。

为什么需要它
------------
补丁改的就是「攒够多少人才一次性登记」。要验证就得让存档刚好卡在阈值上：

    pending = B       下一次进命定编辑器就**立刻登记 B 个**
    pending = B - 1   玩家只需再答对 1 个人就能触发（也是最有说服力的测法）

pending（= 已答对但还没登记）的判定，来自 FateEditor.cs:5486：

    !markedCorrect && nameId == id && IsCorrectFate(id, fateId)

注意 `num` 还跟「该区域还剩多少没解」有关，所以要测批大小就得用**船上区**
（era 0/1，U = 58），不能用办公室存档。本脚本会拒绝 era=3 的底档。

用法
----
    # 造一份：容易档(4)，pending = 4，进书就触发一次登记 4 个
    python hardcore/make_test_save.py --level 4 --out hardcore/_saves/t-lv4.txt

    # 造一份：中等档(7)，pending = 6，玩家再答对 1 个就触发登记 7 个
    python hardcore/make_test_save.py --level 7 --minus-one --out hardcore/_saves/t-lv7.txt

    # 检测任意存档
    python hardcore/make_test_save.py --verify hardcore/_saves/t-lv7.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from make_envelope_save import build_zones, load_save, save_save          # noqa: E402
from parse_assets import load_assets, parse_csv                           # noqa: E402

DEFAULT_SRC = ROOT / "ObraDinnSave-BLANK.txt"

FACE_ONE = re.compile(r"<face\b[^>]*?/>")
FACE_ID = re.compile(r'\bid\s*=\s*"([^"]*)"')
ERA_RE = re.compile(r"<general\b[^>]*?\bera=\"(\d+)\"")

LEVELS = {3: "简单（原难度）", 4: "容易", 7: "中等", 14: "较难", 29: "困难", 58: "硬核"}


# ------------------------------------------------------------------ 基础数据
def crew_fates() -> dict:
    """crew id -> 正确答案列表（Crew.csv 的 fate 列，逗号分隔，可能是多答案）"""
    _, rows = parse_csv(load_assets()["Crew"])
    out = {}
    for r in rows:
        f = [x.strip() for x in r["fate"].split(",") if x.strip()]
        if f:
            out[r["id"]] = f
    return out


def face_attr(xml: str, cid: str, attr: str) -> str | None:
    pat = re.compile(r'<face\b[^>]*?\bid\s*=\s*"%s"[^>]*?/>' % re.escape(cid))
    m = pat.search(xml)
    if not m:
        return None
    a = re.search(r'\b%s\s*=\s*"([^"]*)"' % attr, m.group(0))
    return a.group(1) if a else None


def patch_face(xml: str, cid: str, **kv) -> tuple[str, int]:
    """改一个 <face> 的若干属性，返回 (新 xml, 命中数)"""
    hit = 0

    def repl(m: re.Match) -> str:
        nonlocal hit
        tag = m.group(0)
        if FACE_ID.search(tag).group(1) != cid:
            return tag
        for k, v in kv.items():
            tag = re.sub(r'(\b%s\s*=\s*")[^"]*(")' % k,
                         lambda mm, v=v: mm.group(1) + str(v) + mm.group(2), tag)
        hit += 1
        return tag

    return FACE_ONE.sub(repl, xml), hit


# ------------------------------------------------------------------ pending
def pending_list(xml: str, fates: dict) -> list[str]:
    """复刻游戏的判定，列出「已答对但未登记」的人"""
    out = []
    for m in FACE_ONE.finditer(xml):
        tag = m.group(0)
        cid = FACE_ID.search(tag).group(1)
        name = re.search(r'\bnameId\s*=\s*"([^"]*)"', tag)
        fate = re.search(r'\bfateId\s*=\s*"([^"]*)"', tag)
        marked = re.search(r'\bmarkedCorrect\s*=\s*"([^"]*)"', tag)
        if not (name and fate and marked):
            continue
        if marked.group(1) == "true":
            continue
        if name.group(1) != cid:
            continue
        if fate.group(1) in fates.get(cid, []):
            out.append(cid)
    return out


def report(xml: str, fates: dict, src: str) -> int:
    era = ERA_RE.search(xml)
    era = int(era.group(1)) if era else -1
    crew, ship, office = build_zones()
    zone = office if era == 3 else ship
    marked = sum(1 for c in zone if face_attr(xml, c, "markedCorrect") == "true")
    unsolved = len(zone) - marked
    pend = pending_list(xml, fates)

    print("  来源      : " + src)
    print("  era       : %d  (%s)" % (era, "办公室" if era == 3 else "船上"))
    print("  区域人数  : %d   已登记 %d   未登记 %d" % (len(zone), marked, unsolved))
    print("  pending   : %d  %s" % (len(pend), pend[:8] + (["..."] if len(pend) > 8 else [])))
    print()
    if era == 3:
        print("  [!] 这是办公室存档，num 会由办公室区(2 人)决定，测不出批大小")
        return 0
    print("  各档位下一次登记会发生什么（该档 num 与当前 pending 比较）：")
    for b in (3, 4, 7, 14, 29, 58):
        if b == 3:
            n = 2 if unsolved in (4, 2) else 3        # 原版尾巴
        else:
            n = b
        if len(pend) >= n:
            print("     %-14s num=%-3d  pending %d >= %d  ->  立刻登记 %d 个"
                  % (LEVELS[b], n, len(pend), n, n))
        else:
            print("     %-14s num=%-3d  pending %d <  %d  ->  不触发（还差 %d 个）"
                  % (LEVELS[b], n, len(pend), n, n - len(pend)))
    return 0


# ------------------------------------------------------------------ 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, choices=sorted(LEVELS),
                    help="目标档位的批大小（4/7/14/29/58；3=原版）")
    ap.add_argument("--pending", type=int, help="直接指定 pending 人数（覆盖 --level 的默认）")
    ap.add_argument("--minus-one", action="store_true",
                    help="pending 取 B-1：玩家再答对 1 个才触发")
    ap.add_argument("--src", default=str(DEFAULT_SRC), help="底档（必须是 era 0/1 的船上存档）")
    ap.add_argument("--out", help="输出文件")
    ap.add_argument("--verify", help="只检测，不生成")
    a = ap.parse_args()

    fates = crew_fates()

    if a.verify:
        container, xml = load_save(Path(a.verify))
        print("=" * 70)
        print("存档待定情况：" + a.verify)
        print("=" * 70)
        return report(xml, fates, a.verify)

    if not a.level or not a.out:
        ap.error("要么给 --verify，要么给 --level 和 --out")

    target = a.pending if a.pending is not None else a.level - (1 if a.minus_one else 0)
    if target < 0:
        ap.error("pending 不能是负数")

    container, xml = load_save(Path(a.src))
    era = ERA_RE.search(xml)
    era = int(era.group(1)) if era else -1
    if era == 3:
        print("[X] 底档是办公室(era=3)，测不出批大小。换 era 0/1 的船上存档。")
        return 2

    _, ship, _ = build_zones()
    picked = []
    for cid in ship:
        if len(picked) >= target:
            break
        if cid in fates:
            picked.append(cid)
    if len(picked) < target:
        print("[X] 船员不够：需要 %d 个，只找到 %d 个有正确答案的" % (target, len(picked)))
        return 2

    for cid in picked:
        xml, n = patch_face(xml, cid, nameId=cid, fateId=fates[cid][0], markedCorrect="false")
        if n != 1:
            print("[X] 改写 %s 失败（命中 %d 次）" % (cid, n))
            return 2

    # 剩下的船上船员确保是「未答对」状态，免得混进 pending
    for cid in ship:
        if cid in picked:
            continue
        for attr, val in (("fateId", "unknown"), ("markedCorrect", "false")):
            xml, _ = patch_face(xml, cid, **{attr: val})

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save_save(container, xml, out)

    print("=" * 70)
    print("已生成：" + str(out))
    print("目标档位：%s   (num = %d)" % (LEVELS.get(a.level, "?"), a.level))
    print("设计 pending = %d%s" % (target, "（再答对 1 个就触发）" if a.minus_one else "（进书即触发）"))
    print("=" * 70)

    # 自检：把刚写出来的文件读回来重新数一遍
    _, back = load_save(out)
    print()
    print("回读自检：")
    return report(back, fates, str(out))


if __name__ == "__main__":
    sys.exit(main())
