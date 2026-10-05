"""生成「刚收到回复」的三档结局存档（包裹 / 信封）。

结局分叉全部在 OfficeLogic.cs 的 Start() 里，且是**即时计算**、不存在存档字段里：
    SaveData.it.general.era = 3;                                  // office 场景
    completedShipZoneCorrectly = SaveData.it.GetZoneIsSolved(Story.Zone.Ship);
    if (completedShipZoneCorrectly)      -> office_letter_win  / shelf_objects_good / 包裹
    else if (GetNumFatesCorrect() >= 30) -> office_letter_mid  / shelf_objects_mid  / 信封
    else                                 -> office_letter_fail / shelf_objects_bad  / 信封

  GetZoneIsSolved(zone) = GetZoneUnsolvedCount(zone) == 0   // 只看本 zone 船的 markedCorrect
  d070(Bargain/VIII) 属于 Office zone => Ship 58 人 / Office 2 人(stewcap, mate3)

三档（Ship 区解对数都取"可达链"上的值，链 = [0,3,...,54,56,58]）:
  win  : Ship 58 全解对 -> 总 58/60 -> 包裹 + win 信
  mid  : Ship 解对 56   -> 总 56/60 -> 信封 + mid 信   (max_reachable_envelope)
  fail : Ship 解对 27   -> 总 27/60 -> 信封 + fail 信  (max_reachable_below(58,30))

存档点 = OfficeLogic.State.Package 的 ENTER（OfficeLogic.cs:145 `Game.SaveActive`），
也就是"包裹/信封已经递到桌上、还没拆"的那一刻——游戏自己就会在这里写盘。

Office 区两人保持「只填身份不填下落」：
  nameId = 自己的 id      （P1 实测：era=0/42 对时就已是 nameId=mate3 / nameId=stewcap）
  fateId = "unknown"      （他们的死亡在未解锁的第八章）
  markedCorrect = false
  代码依据：SaveData.Rewind() 重置 Office 区时只写 fateId/markedCorrect，**不动 nameId**。
"""
import argparse
import re
import sys
from pathlib import Path

from make_envelope_save import (FACE_RE, MID_THRESHOLD, MOMENT_RE, OFFICE_DISASTER,
                                _patch_element, build_office_moments, build_zones,
                                get_correct_ids, get_stat, load_save,
                                max_reachable_below, max_reachable_envelope,
                                patch_disaster, patch_face, patch_moment,
                                remove_stat, remove_stats_prefix, save_save,
                                set_general, set_stat, ship_correct_chain)
from make_killer_captain_save import get_general

ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def elements(xml, regex):
    out = {}
    for m in regex.finditer(xml):
        a = dict(ATTR_RE.findall(m.group(0)))
        if a.get("id"):
            out[a["id"]] = a
    return out


TIERS = ("win", "mid", "fail")
DEFAULT_DST = {"win": "ObraDinnSave-END-WIN.txt",
               "mid": "ObraDinnSave-END-MID.txt",
               "fail": "ObraDinnSave-END-FAIL.txt"}


def target_ship_correct(ship_total, tier):
    """该档位下 Ship 区应解对的人数（全部落在可达链上）"""
    if tier == "win":
        return ship_total                                   # 58
    if tier == "mid":
        return max_reachable_envelope(ship_total)            # 56
    return max_reachable_below(ship_total, MID_THRESHOLD)    # <30 的最大可达值 = 27


def verify(path: Path, crew, ship, office, tier, unknown_all=False):
    _, xml = load_save(path)
    correct = get_correct_ids(xml)
    n = len(correct)
    ship_ok = [c for c in ship if c in correct]
    office_ok = [c for c in office if c in correct]

    era = get_general(xml, "era")
    pkg = get_general(xml, "officePackageReady")
    paw = get_general(xml, "officePawReady")
    rev = get_general(xml, "officeHaveRevealedBook")
    end = get_general(xml, "officeEndedOnce")

    faces = elements(xml, FACE_RE)
    moments = elements(xml, MOMENT_RE)
    if unknown_all:
        office_form = all(faces[c].get("nameId") == "unknown"
                          and faces[c].get("fateId") == "unknown"
                          and faces[c].get("markedCorrect") == "false" for c in crew)
    else:
        office_form = all(faces[c].get("nameId") == c
                          and faces[c].get("fateId") == "unknown"
                          and faces[c].get("markedCorrect") == "false" for c in office)
    d070_clean = all(int(moments[m].get("visitCount", 0)) == 0
                     and moments[m].get("revealedPageInBook") == "false"
                     and moments[m].get("revealedGhosts") == "false"
                     for m in moments if m.startswith(OFFICE_DISASTER))
    leave1 = get_stat(xml, "#dia-ship-end-leave-1")
    leave3 = get_stat(xml, "#dia-ship-end-leave-3")

    want = 0 if unknown_all else target_ship_correct(len(ship), tier)
    is_package = len(ship_ok) == len(ship)
    letter = "win" if is_package else ("mid" if n >= MID_THRESHOLD else "fail")

    print(f"=== 验证 {path.name}  (tier={tier}{', 全 unknown' if unknown_all else ''}) ===")
    print(f"  era={era}  officePackageReady={pkg}  pawReady={paw}"
          f"  revealedBook={rev}  endedOnce={end}")
    print(f"  Ship 区解对 {len(ship_ok)}/{len(ship)}   Office 区解对 {len(office_ok)}/{len(office)}"
          f"   ->  总解对数 {n}/{len(crew)}  (期望 {want})")
    print(f"  zone-complete-ship={get_stat(xml, 'zone-complete-ship')}"
          f"   zone-complete-office={get_stat(xml, 'zone-complete-office')}")
    print(f"  d070 全部「从未到过」= {d070_clean}")
    print("  Office 区: " + "   ".join(
        f"{c}[nameId={faces[c].get('nameId')}, fateId={faces[c].get('fateId')}, "
        f"markedCorrect={faces[c].get('markedCorrect')}]" for c in office))
    if unknown_all:
        blank = [c for c, f in faces.items()
                 if f.get("nameId") == "unknown" and f.get("fateId") == "unknown"]
        print(f"  全 unknown 的 face: {len(blank)}/{len(crew)}")
    print(f"  离船提示: leave-1={leave1}  leave-3={leave3}")
    print(f"  completedShipZoneCorrectly = {is_package}"
          f"  => {'包裹 PACKAGE' if is_package else '信封 ENVELOPE'}")
    print(f"  信件口吻 = {letter}  (期望 {tier})")

    ok = (era == "3" and pkg == "true" and paw == "false" and rev == "false" and end == "false"
          and n == want and len(ship_ok) == want
          and not office_ok and office_form and d070_clean and letter == tier)
    print(f"\n  预期 = {ok}  {'[OK]' if ok else '[X]'}")
    return ok


def main():
    ap = argparse.ArgumentParser(description="生成三档结局存档（包裹 / 信封）")
    ap.add_argument("--tier", choices=TIERS, required=False, default="win")
    ap.add_argument("--src", default="ObraDinnSave-P2.original.txt",
                    help="基础存档，必须是 Ship 区全解对的原始档")
    ap.add_argument("--dst", default=None)
    ap.add_argument("--unknown-all", action="store_true",
                    help="只配合 --tier fail：不保留任何已解对，60 人全部 nameId/fateId=unknown（0/60）")
    ap.add_argument("--verify", metavar="FILE", help="只验证，不写文件")
    args = ap.parse_args()

    crew, ship, office = build_zones()
    if args.unknown_all and args.tier != "fail":
        sys.exit("[-] --unknown-all 只对 --tier fail 有意义")

    if args.verify:
        sys.exit(0 if verify(Path(args.verify), crew, ship, office, args.tier,
                             args.unknown_all) else 1)

    src = Path(args.src)
    if not src.exists():
        sys.exit(f"[-] 找不到基础存档: {src}")
    dst = Path(args.dst or DEFAULT_DST[args.tier])

    container, xml = load_save(src)
    correct = get_correct_ids(xml)
    if any(c not in correct for c in ship):
        sys.exit(f"[-] {src.name} 的 Ship 区并非全解对，不能当底（会叠加改动）。"
                 f"请用 ObraDinnSave-P2.original.txt")
    print(f"[i] 区域: Ship={len(ship)}  Office={len(office)} {office}  (共 {len(crew)})")
    print(f"[i] 基础存档 {src.name}: markedCorrect={len(correct)}/{len(crew)}  Ship 区全解对")

    # ---- 1) Office 区(d070) 复位：「从未到过」 + 两人只留身份
    office_moments = build_office_moments()
    print(f"\n[i] 复位 Office 区域 {OFFICE_DISASTER}（{len(office_moments)} 个 moment）...")
    for mid in office_moments:
        xml = patch_moment(xml, mid, visitCount="0", unlocked="false",
                           revealedGhosts="false", revealedPageInBook="false")
    xml = patch_disaster(xml, OFFICE_DISASTER, revealedChartInBook="false",
                         revealedDisappearancesInBook="false")
    for cid in office:
        if not args.unknown_all:
            xml = _patch_element(xml, FACE_RE, cid, nameId=cid)   # 身份保留
        xml = patch_face(xml, cid, marked=False, fate="unknown") # 下落清空
    xml = remove_stats_prefix(xml, f"#dia-{OFFICE_DISASTER}-")
    xml = remove_stat(xml, "zone-complete-office")

    # ---- 2) 办公室进度：停在 Package（包裹/信封已送达，未拆）
    print(f"\n[i] 办公室进度 -> State.Package（原生存档点 OfficeLogic.cs:145）...")
    xml = set_general(xml, "era", "3")
    xml = set_general(xml, "officePackageReady", "true")
    xml = set_general(xml, "officePawReady", "false")
    xml = set_general(xml, "officeHaveRevealedBook", "false")
    xml = set_general(xml, "officeEndedOnce", "false")
    xml = remove_stats_prefix(xml, "#dia-office-")
    xml = set_stat(xml, "#dia-office-intro", "1")

    # ---- 3) 结局流程对白计数
    #  leave-1 = 船未解完的离船提示(信封)；leave-3 = 船已解完的提示(包裹)
    #  notify 只在 era==0 时播 => 恒为 1
    print(f"\n[i] 归一结局流程对白计数 ...")
    for sid in ("#dia-ship-end-notify", "#dia-ship-end-done", "#dia-tally-intro"):
        if get_stat(xml, sid) is not None:
            xml = set_stat(xml, sid, "1")
    if args.tier == "win":
        xml = remove_stat(xml, "#dia-ship-end-leave-1")
        xml = set_stat(xml, "#dia-ship-end-leave-3", "1")
        xml = set_stat(xml, "#dia-office-delivery-package", "1")
    else:
        xml = set_stat(xml, "#dia-ship-end-leave-1", "1")
        xml = remove_stat(xml, "#dia-ship-end-leave-3")
        xml = set_stat(xml, "#dia-office-delivery-envelope", "1")

    # ---- 4) Ship 区解对数落到可达值
    chain = ship_correct_chain(len(ship))
    if args.unknown_all:
        print(f"\n[i] 目标 Ship 区解对数 = 0（全空档）")
        print(f"    把全部 {len(crew)} 人重置为 nameId=unknown fateId=unknown"
              f" markedCorrect=false clueWarning=0")
        for c in crew:
            xml = _patch_element(xml, FACE_RE, c, nameId="unknown", fateId="unknown",
                                 markedCorrect="false", clueWarning="0")
    else:
        target = target_ship_correct(len(ship), args.tier)
        n_unmark = len(ship) - target
        print(f"\n[i] 目标 Ship 区解对数 = {target}   可达链 = {chain}")
        if n_unmark:
            targets = [c for c in ship if c in correct][:n_unmark]
            print(f"    打回未解 {n_unmark} 人: {targets}")
            for cid in targets:
                xml = patch_face(xml, cid, marked=False, fate="unknown")
        else:
            print("    无需打回（包裹档 = Ship 区全解对）")

    # ---- 写出
    print("\n" + "=" * 64)
    if dst.exists():
        dst.with_suffix(dst.suffix + ".bak").write_text(
            dst.read_text(encoding="iso-8859-1"), encoding="iso-8859-1")
    save_save(container, xml, dst)
    print(f"[+] 已写出: {dst}")
    _, back = load_save(dst)
    print(f"[i] 回读验证: {'明文完全一致 [OK]' if back == xml else '不一致 [X]'}\n")
    ok = verify(Path(dst), crew, ship, office, args.tier, args.unknown_all)

    print("\n玩法: 载入后直接站在办公桌前，"
          + ("包裹" if args.tier == "win" else "信封") + "已送达但未拆。")
    if args.tier == "win":
        print("      拆包裹 -> 拿到猴爪 -> 用猴爪进第八章 -> 补齐 mate3 / stewcap -> 好结局。")
    elif args.unknown_all:
        print("      拆开读完信 -> 直接走结局流程（拿不到猴爪）。书里 60 人全是 unknown。")
    else:
        print("      拆开读完信 -> 结局流程（无猴爪）。")
    print("\n安装: 复制到 C:\\Users\\<用户名>\\AppData\\LocalLow\\3909\\ObraDinn\\")
    print("      并重命名为 ObraDinnSave-P1.txt / -P2.txt / -P3.txt 之一")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
