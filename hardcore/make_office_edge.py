#!/usr/bin/env python3
"""造「办公室终局」验证存档 —— 58 人已登记，办公室只剩 d070 那 2 个。

底档用 **ObraDinnSave-P3.txt**（真实的 60/60 通关档）：
它本来就是 era=3 + 全部看过 + 所有 helped* 教程都已看过，是「终态」的权威样本。
在此基础上只做必要改动：

    1. d070 那 2 人（mate3 / stewcap）恢复成未答：nameId/fateId = unknown、markedCorrect=false
    2. officeEndedOnce -> false       （否则不会走 CheckVictory，好结局不出来）
    3. 所有 moment 的 unlocked / revealedGhosts / revealedPageInBook 置 true
       所有 disaster 的两个 revealed* 置 true        （对应「所有页面、场景均看过已解锁」）
    4. 删掉 zone-complete-office 统计（办公室还没完成）

于是船上区 58 人全部 markedCorrect=true，办公室区 2 人未登记：
    进办公室后把 d070 两人填对 -> U=2 -> num=2（原版尾巴 U==2 -> 2）
    -> 登记 2 个 -> 文案走 welldone_2_*（「Two fates correct」）
    -> 60/60 -> CheckVictory -> 好结局

用法：
    python hardcore/make_office_edge.py [--out 路径]
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
from make_hardcore_edge import set_face                                      # noqa: E402
from make_test_save import crew_fates, face_attr, pending_list               # noqa: E402

SRC = ROOT / "ObraDinnSave-P3.txt"
DEFAULT_OUT = HERE / "_saves" / "office-58of60.txt"

GENERAL = "<general"
UNKNOWN = "unknown"
OFFICE_LEFTOVER_STAT = "zone-complete-office"


def set_all_tags(xml: str, tagname: str, **kv: str) -> tuple[str, int]:
    """给所有该名字的自闭合标签设置属性（不存在就补上）。"""
    pat = re.compile(r"<%s\b[^>]*?/>" % tagname)
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        n += 1
        tag = m.group(0)
        for k, v in kv.items():
            if re.search(r"\b%s\s*=" % k, tag):
                tag = re.sub(r'(\b%s\s*=\s*")[^"]*(")' % k,
                             lambda mm, v=v: mm.group(1) + v + mm.group(2), tag)
            else:
                cut = tag.rfind("/>")
                tag = tag[:cut] + ' %s="%s" ' % (k, v) + "/>"
        return tag

    return pat.sub(repl, xml), n


def remove_stat(xml: str, sid: str) -> tuple[str, int]:
    pat = re.compile(r"\s*<stat>\s*<id>%s</id>\s*<val>[^<]*</val>\s*</stat>"
                     % re.escape(sid))
    return pat.subn("", xml)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()

    text, xml = load_save(SRC)
    fates = crew_fates()
    _crew, ship, office = build_zones()

    era = re.search(r"<general\b[^>]*?\bera=\"(\d+)\"", xml)
    print("底档     : %s   era=%s" % (SRC.name, era.group(1) if era else "?"))
    print("船上区   : %d 人" % len(ship))
    print("办公室区 : %d 人  %s" % (len(office), ", ".join(office)))

    # ---------------------------------------------------------- 1. 清空 d070 两人
    for cid in office:
        xml, hit = set_face(xml, cid, nameId=UNKNOWN, fateId=UNKNOWN,
                            markedCorrect="false")
        if hit != 1:
            print("[X] %s 的 <face> 命中 %d 次（应为 1）" % (cid, hit))
            return 1

    # ---------------------------------------------------------- 2. 结局标志复位
    xml = set_general(xml, "officeEndedOnce", "false")

    # ---------------------------------------------------------- 3. 页面/场景全解锁
    xml, n_m = set_all_tags(xml, "moment", unlocked="true", revealedGhosts="true",
                            revealedPageInBook="true")
    xml, n_d = set_all_tags(xml, "disaster", revealedChartInBook="true",
                            revealedDisappearancesInBook="true")
    print("已置解锁 : moment %d 个, disaster %d 个" % (n_m, n_d))

    # ---------------------------------------------------------- 4. 办公室尚未完成
    xml, n_s = remove_stat(xml, OFFICE_LEFTOVER_STAT)
    print("已移除统计 : %s x%d" % (OFFICE_LEFTOVER_STAT, n_s))

    dst = Path(a.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    save_save(text, xml, dst)

    # ---------------------------------------------------------- 读回自验证
    _t, x2 = load_save(dst)
    era2 = int(re.search(r"<general\b[^>]*?\bera=\"(\d+)\"", x2).group(1))
    ended = re.search(r'\bofficeEndedOnce="([^"]*)"', x2).group(1)
    ship_marked = sum(1 for c in ship if face_attr(x2, c, "markedCorrect") == "true")
    office_marked = sum(1 for c in office if face_attr(x2, c, "markedCorrect") == "true")
    pend = pending_list(x2, fates)
    total_marked = ship_marked + office_marked
    mom_unlocked = sum(1 for m in re.findall(r"<moment\b[^>]*?/>", x2)
                       if 'unlocked="true"' in m)
    mom_total = len(re.findall(r"<moment\b[^>]*?/>", x2))

    print()
    print("era                        = %d（应为 3）" % era2)
    print("officeEndedOnce            = %s（应为 false）" % ended)
    print("船上区 markedCorrect=true   = %d / %d" % (ship_marked, len(ship)))
    print("办公室 markedCorrect=true   = %d / %d" % (office_marked, len(office)))
    print("GetNumFatesCorrect         = %d / 60" % total_marked)
    print("pending                    = %s（应为 0：这俩是「空着」而不是「已答对未登记」）"
          % (", ".join(pend) or "无"))
    print("moment unlocked=true       = %d / %d" % (mom_unlocked, mom_total))
    print("zone-complete-office 还在?  = %s"
          % ("是 [X]" if OFFICE_LEFTOVER_STAT in x2 else "否 [OK]"))
    for cid in office:
        print("  %-10s nameId=%r fateId=%r markedCorrect=%r"
              % (cid, face_attr(x2, cid, "nameId"), face_attr(x2, cid, "fateId"),
                 face_attr(x2, cid, "markedCorrect")))

    size = dst.stat().st_size
    print()
    print("写出 %s  %d bytes  sha256_16 %s"
          % (dst, size, hashlib.sha256(dst.read_bytes()).hexdigest()[:16]))

    ok = (era2 == 3 and ended == "false"
          and ship_marked == len(ship) and office_marked == 0
          and pend == []
          and mom_unlocked == mom_total
          and OFFICE_LEFTOVER_STAT not in x2)
    print("自验证 %s" % ("通过" if ok else "失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
