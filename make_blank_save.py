"""生成「全空白」存档：书的所有页面已解锁，但 60 人的身份与下落全部未填。

「空白」在存档里的规范表示（全部有源码依据）:
  * FaceData() 构造      => nameId = "unknown", fateId = "unknown"   (SaveData.cs:1030 区域)
  * FaceData.isTotallyUnknown => nameId 为 null/空/"unknown" 且 fateId 同理
  * FateEditor.ApplyFaceChosen => 取消归属时把旧持有者置回 "unknown"
  * BookContent.cs:324   => 只有 nameId != "unknown" 才显示姓名（游戏自己按此渲染）
  => 「未填」= nameId="unknown" 且 fateId="unknown"，clueWarning=0，markedCorrect=false

「页面已解锁」对应的字段:
  * moments[].visitCount > 0 / unlocked / revealedGhosts / revealedPageInBook
  * disasters[].revealedChartInBook / revealedDisappearancesInBook
  * general.bookVisitedLastPage = true
  * stat zone-complete-ship = 1
  （P2.original 已经是「所有 Ship 区 moment 都看过、章节全揭示」的状态，直接沿用）

可玩性约束:
  * markedCorrect 全 false => 解对数 0（可达链起点）
  * era=1（zone-complete-ship 驱动的 0->1），此时 Office 进度必须全为 false
  * nameId 全为 "unknown" 不构成排列冲突（My inspectors 只对非 unknown 查重）
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from make_envelope_save import (DISASTER_RE, FACE_RE, MOMENT_RE, OFFICE_DISASTER,
                                _patch_element, build_office_moments, build_zones,
                                get_correct_ids, get_stat, load_save, patch_disaster,
                                patch_moment, remove_stat, remove_stats_prefix,
                                save_save, set_general, ship_correct_chain)
from make_killer_captain_save import ATTR_RE, GENERAL_RE, get_general, read_faces

BLANK = "unknown"


def blank_face(xml, crew_id):
    """把一张脸置为「完全未填」"""
    return _patch_element(xml, FACE_RE, crew_id,
                          nameId=BLANK, fateId=BLANK,
                          markedCorrect="false", clueWarning="0")


def verify(path: Path, crew, ship, office):
    _, xml = load_save(path)
    faces = read_faces(xml)
    moments = {a["id"]: a for a in (dict(ATTR_RE.findall(m.group(0)))
                                    for m in MOMENT_RE.finditer(xml))}
    disasters = {a["id"]: a for a in (dict(ATTR_RE.findall(m.group(0)))
                                      for m in DISASTER_RE.finditer(xml))}

    filled_name = [c for c, f in faces.items() if f.get("nameId") != BLANK]
    filled_fate = [c for c, f in faces.items() if f.get("fateId") != BLANK]
    marked = [c for c, f in faces.items() if f.get("markedCorrect") == "true"]

    vis = [m for m, a in moments.items() if int(a.get("visitCount", 0)) > 0]
    rev_page = [m for m, a in moments.items() if a.get("revealedPageInBook") == "true"]
    unl = [m for m, a in moments.items() if a.get("unlocked") == "true"]
    ghost = [m for m, a in moments.items() if a.get("revealedGhosts") == "true"]
    chart = [d for d, a in disasters.items() if a.get("revealedChartInBook") == "true"]
    disappear = [d for d, a in disasters.items() if a.get("revealedDisappearancesInBook") == "true"]

    print(f"=== 验证 {path.name} ===")
    print(f"  era={get_general(xml, 'era')}   zone-complete-ship={get_stat(xml, 'zone-complete-ship')}"
          f"   bookVisitedLastPage={get_general(xml, 'bookVisitedLastPage')}")
    print(f"  解对数 = {len(get_correct_ids(xml))}/{len(crew)}")
    print(f"\n  --- 空白度（faces 共 {len(faces)}）---")
    print(f"    nameId 已填 = {len(filled_name)}   fateId 已填 = {len(filled_fate)}"
          f"   markedCorrect = {len(marked)}")
    if filled_name:
        print(f"      nameId 非空的人: {filled_name[:10]}")
    if filled_fate:
        print(f"      fateId 非空的人: {filled_fate[:10]}")
    print(f"    nameId 取值分布: {Counter(f.get('nameId') for f in faces.values()).most_common(3)}")
    print(f"\n  --- 页面解锁度（moments 共 {len(moments)}）---")
    print(f"    visited={len(vis)}  revealedPageInBook={len(rev_page)}"
          f"  unlocked={len(unl)}  revealedGhosts={len(ghost)}")
    print(f"    未访问的 moment: {sorted(set(moments) - set(vis))}")
    print(f"  --- 章节揭示（disasters 共 {len(disasters)}）---")
    print(f"    revealedChartInBook={len(chart)}  revealedDisappearancesInBook={len(disappear)}")
    print(f"    未揭示的 disaster: {sorted(set(disasters) - set(disappear))}")

    ok = (not filled_name and not filled_fate and not marked
          and len(vis) == len(moments) - len([m for m in moments if m.startswith(OFFICE_DISASTER)]))
    print(f"\n  空白 + 已解锁 预期 = {ok}  {'[OK]' if ok else '[X]'}")
    return ok


def main():
    ap = argparse.ArgumentParser(description="生成全空白存档（页面全解锁 / 全员未填）")
    ap.add_argument("--src", default="ObraDinnSave-P2.original.txt")
    ap.add_argument("--dst", default="ObraDinnSave-BLANK.txt")
    ap.add_argument("--verify", metavar="FILE", help="只验证，不写文件")
    args = ap.parse_args()

    crew, ship, office = build_zones()

    if args.verify:
        sys.exit(0 if verify(Path(args.verify), crew, ship, office) else 1)

    src = Path(args.src)
    if not src.exists():
        sys.exit(f"[-] 找不到基础存档: {src}")
    container, xml = load_save(src)

    faces0 = read_faces(xml)
    unvisited = [m for m in re.findall(r'<moment\b[^>]*?/>', xml)
                 if 'visitCount="0"' in m]
    unlocked_moments = len(re.findall(r'<moment\b[^>]*?/>', xml)) - len(unvisited)
    if unlocked_moments < 40:
        sys.exit(f"[-] 基础存档只解锁了 {unlocked_moments} 个 moment，"
                 f"不是「全看完」的状态。请用 ObraDinnSave-P2.original.txt")
    print(f"[i] 基础存档 {src.name}: {len(faces0)} 个 face，"
          f"{unlocked_moments} 个 moment 已访问")

    # ---- 1) 全员置空
    print(f"\n[i] 清空全部 {len(crew)} 人的身份与下落（nameId/fateId -> \"{BLANK}\"）...")
    for c in crew:
        xml = blank_face(xml, c)
    print(f"    faces 全部置为 nameId={BLANK} fateId={BLANK} "
          f"markedCorrect=false clueWarning=0")

    # ---- 2) Office 区域复位（与其它存档保持一致的处理）
    office_moments = build_office_moments()
    for mid in office_moments:
        xml = patch_moment(xml, mid, visitCount="0", unlocked="false",
                           revealedGhosts="false", revealedPageInBook="false")
    xml = patch_disaster(xml, OFFICE_DISASTER,
                         revealedChartInBook="false", revealedDisappearancesInBook="false")
    xml = remove_stats_prefix(xml, f"#dia-{OFFICE_DISASTER}-")
    xml = remove_stats_prefix(xml, "#dia-office-")
    xml = remove_stat(xml, "zone-complete-office")

    # ---- 3) 阶段标志
    print(f"\n[i] 设置阶段标志 ...")
    xml = set_general(xml, "era", "1")
    xml = set_general(xml, "bookVisitedLastPage", "true")   # 最后一页也看过
    for k in ("officePackageReady", "officePawReady",
              "officeHaveRevealedBook", "officeEndedOnce"):
        xml = set_general(xml, k, "false")
    for sid in ("#dia-ship-end-leave-1", "#dia-ship-end-leave-3",
                "#dia-ship-end-done", "#dia-tally-intro"):
        xml = remove_stat(xml, sid)

    # ---- 结果
    print("\n" + "=" * 64)
    dst = Path(args.dst)
    if dst.exists():
        dst.with_suffix(dst.suffix + ".bak").write_text(
            dst.read_text(encoding="iso-8859-1"), encoding="iso-8859-1")
    save_save(container, xml, dst)
    print(f"\n[+] 已写出: {dst}")
    _, back = load_save(dst)
    print(f"[i] 回读验证: {'明文完全一致 [OK]' if back == xml else '不一致 [X]'}")
    print()
    verify(dst, crew, ship, office)

    print("\n玩法: 载入后你在船上，书里所有页面（含各章图表/失踪名单）都已揭示，")
    print("      但 60 人全是「unknown」—— 从零开始填。")
    print("      安装: 复制到 C:\\Users\\<用户名>\\AppData\\LocalLow\\3909\\ObraDinn\\")
    print("            并重命名为 ObraDinnSave-P1.txt / -P2.txt / -P3.txt 之一")


if __name__ == "__main__":
    main()
