#!/usr/bin/env python3
"""造「硬核(58) 差一个」的验证存档 —— 最省事的 58 人一次开验证姿势。

原理（FateEditor.cs:5486 的判定）：

    list = 已答对(nameId == id 且 fateId 正确) 但 markedCorrect 仍为 false 的人
    num  = 档位值（硬核 = 58）；U=58 不在 {4,2}，所以 num 不会被改成 2
    if (list.Count >= num) list = list.GetRange(0, num);
    if (list.Count == num)  -> 这 num 个人一起登记

所以：

    pending = 57  ->  list.Count(57) != 58  ->  什么都不发生
    再答对 1 个   ->  list.Count(58) == 58  ->  **58 人一次全开**

这比手答 58 人快得多；也比 fire-lv58（pending=58，一进编辑器就触发）更接近
真实操作 —— 差的正好是「最后一次编辑」，能完整看到 58 连开的演出。

默认留空的是**船长**（captain）。
另外把 helpedBookFatesCheck 置 false，好让 FateCheck 教程重播
（Book.cs:1497 只在没看过时播，而那条教程显示的正是 help_faceclear_fates0/1）。

用法：
    python hardcore/make_hardcore_edge.py [--leave-out captain] [--out 路径]
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

from make_envelope_save import build_zones, load_save, save_save, set_general  # noqa: E402
from make_test_save import crew_fates, face_attr, pending_list                    # noqa: E402

SRC = ROOT / "ObraDinnSave-BLANK.txt"
DEFAULT_OUT = HERE / "_saves" / "hardcore-57of58.txt"

FACE_ONE = re.compile(r"<face\b[^>]*?/>")
FACE_ID_ATTR = re.compile(r'\bid\s*=\s*"([^"]*)"')


def set_face(xml: str, cid: str, **kv: str) -> tuple[str, int]:
    """改某个 <face> 的属性；属性不存在就补上（比 make_test_save 的版本宽容）。"""
    hit = 0

    def repl(m: re.Match) -> str:
        nonlocal hit
        tag = m.group(0)
        if FACE_ID_ATTR.search(tag).group(1) != cid:
            return tag
        hit += 1
        for k, v in kv.items():
            if re.search(r"\b%s\s*=" % k, tag):
                tag = re.sub(r'(\b%s\s*=\s*")[^"]*(")' % k,
                             lambda mm, v=v: mm.group(1) + v + mm.group(2), tag)
            else:
                cut = tag.rfind("/>")
                tag = tag[:cut] + ' %s="%s" ' % (k, v) + "/>"
        return tag

    return FACE_ONE.sub(repl, xml), hit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leave-out", default="captain", help="留空不填的那个人（默认船长）")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()

    text, xml = load_save(SRC)
    fates = crew_fates()
    _crew, ship, office = build_zones()

    print("源档     : %s" % SRC.name)
    print("船上区   : %d 人" % len(ship))
    print("办公室区 : %d 人（本档不动）%s" % (len(office), ", ".join(office)))
    print("留空     : %s" % a.leave_out)
    if a.leave_out not in ship:
        print("[X] %s 不在船上区" % a.leave_out)
        return 1

    xml = set_general(xml, "helpedBookFatesCheck", "false")

    filled = 0
    for cid in ship:
        if cid == a.leave_out:
            continue
        correct = fates.get(cid)
        if not correct:
            print("[X] %s 在 Crew.csv 里没有正确答案" % cid)
            return 1
        xml, hit = set_face(xml, cid, nameId=cid, fateId=correct[0],
                            markedCorrect="false")
        if hit != 1:
            print("[X] %s 的 <face> 命中 %d 次（应为 1）" % (cid, hit))
            return 1
        filled += 1

    dst = Path(a.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    save_save(text, xml, dst)

    # ---------------------------------------------------------- 读回自验证
    _t, xml2 = load_save(dst)
    pend = pending_list(xml2, fates)
    print()
    print("填充     : %d 人（全部 markedCorrect=false）" % filled)
    print("读回 pending = %d" % len(pend))
    print("  %-10s 在 pending 里? %s"
          % (a.leave_out, "是 [X]" if a.leave_out in pend else "否 [OK]"))

    marks = sum(1 for c in ship if face_attr(xml2, c, "markedCorrect") == "true")
    print("  船上区 markedCorrect=true 的人数 = %d（应为 0，即一次都没登记过）" % marks)
    print("  留空者 fateId = %r  nameId = %r"
          % (face_attr(xml2, a.leave_out, "fateId"),
             face_attr(xml2, a.leave_out, "nameId")))

    size = dst.stat().st_size
    print()
    print("写出 %s  %d bytes  sha256_16 %s"
          % (dst, size, hashlib.sha256(dst.read_bytes()).hexdigest()[:16]))

    ok = (len(pend) == len(ship) - 1 and a.leave_out not in pend and marks == 0)
    print("自验证 %s" % ("通过" if ok else "失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
