"""生成「Killer Captain」成就存档。

成就条件（Awards.cs:857 CheckForKillerCaptain）：
  遍历 Manifest.it.IterateCrews()，只看 GetDeathOrDisappearZone(crew.id) == Ship 的 58 人：
      captain  -> SaveData.it.faceRo["captain"].fateId 必须 Contains("suicide")
      其他 57  -> Manifest.FateId_KillerId(faceRo[crew.id].fateId) == "captain"
  注意 faceRo[crew.id] 是按 <face id="..."> 取的（不是按 nameId）。

触发时机：TallyInsurance.State.Idle 的 ENTER（TallyInsurance.cs:18）
  也就是「离船 -> 结算(Tally) -> 保险页」。载入存档时 era != 3 只会进 Ship 场景
  （Game.cs:224 LoadExploringScene），所以存档必须放在「已看完所有 moment、可离船」的
  era=1 状态；玩家走到船尾的船夫处离船即可触发。

可玩性约束（必须遵守，否则是游戏里产生不了的状态）：
  * 只有 baseId 含 "-killer" 的命运才有「凶手」可选（Manifest.cs:28 fate.hasKiller，
    Manifest.cs:39 只有 hasKiller 才生成 $killer 句子片段 -> FateEditor 才有凶手列表）
    => 基名只能取那 13 个 *-killer
  * "captain" 必须是合法 ent（FateEntIds 里有），否则 GetFateSummary 会出问题
  * markedCorrect 只能由 FateEditor.cs:683 授予 => 若某人的 assign 恰好正确，
    他就处于「已猜对未登记」；一旦人数凑够 num 会被自动登记 => 解对数会跳变
    => 本脚本保证 pending != num，状态稳定且解对数 = 0（可达链起点）
  默认恶趣味方案：除船长外 57 人全写成 `eaten-killer:captain`（被船长吃掉），
    船长保持 `suicide-gun`（成就要求他的 fateId 含 "suicide"）。
    此时 pending = 1（只有船长恰好答对，因为那是他真实的命运），num = 3 => 不会自动登记。
"""
import argparse
import re
import sys
from pathlib import Path

from make_envelope_save import (OFFICE_DISASTER, build_fate_ids, build_office_moments,
                                build_zones, get_correct_ids, get_stat, load_save,
                                patch_disaster, patch_face, patch_moment,
                                remove_stat, remove_stats_prefix, save_save,
                                set_general, ship_correct_chain)
from parse_assets import load_assets

FACE_RE = re.compile(r"<face\b[^>]*?/>", re.S)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
GENERAL_RE = re.compile(r"<general\b[^>]*>")


def get_general(xml, name):
    return dict(ATTR_RE.findall(GENERAL_RE.search(xml).group(0))).get(name)


def read_faces(xml):
    return {a["id"]: a for a in (dict(ATTR_RE.findall(m.group(0))) for m in FACE_RE.finditer(xml))}


def fate_bases():
    """FateBaseIds 的全部基名"""
    text = load_assets()["FateBaseIds"]
    return [x.strip() for x in text.splitlines() if x.strip()]


def killer_bases(bases):
    return [b for b in bases if b.endswith("-killer")]


def suicide_bases(bases):
    return [b for b in bases if b.startswith("suicide")]


def main():
    ap = argparse.ArgumentParser(description="生成 Killer Captain 成就存档")
    ap.add_argument("--src", default="ObraDinnSave-P2.original.txt")
    ap.add_argument("--dst", default="ObraDinnSave-KILLERCAPTAIN.txt")
    ap.add_argument("--base-fate", default="eaten-killer",
                    help="非船长统一使用的命运基名（必须是 *-killer，默认 eaten-killer=被船长吃掉）")
    ap.add_argument("--captain-fate", default="suicide-gun",
                    help="船长的命运（必须含 suicide，默认 suicide-gun）")
    ap.add_argument("--report", action="store_true", help="只分析打印，不写文件")
    ap.add_argument("--verify", metavar="FILE",
                    help="只验证某个存档是否满足成就条件（不改文件）")
    args = ap.parse_args()

    crew, ship, office = build_zones()
    fate_ids = build_fate_ids()
    bases = fate_bases()
    kbases, sbases = killer_bases(bases), suicide_bases(bases)

    if args.verify:
        path = Path(args.verify)
        _, x = load_save(path)
        fs = read_faces(x)
        cap = fs.get("captain", {}).get("fateId", "")
        cap_ok = "suicide" in cap
        bad = [(c, fs.get(c, {}).get("fateId", "")) for c in ship
               if c != "captain" and fs.get(c, {}).get("fateId", "").partition(":")[2] != "captain"]
        print(f"=== 验证 {path.name} ===")
        print(f"  era={get_general(x, 'era')}  解对数={len(get_correct_ids(x))}/{len(crew)}")
        print(f"  Ship 区 {len(ship)} 人（含 captain）")
        print(f"  captain.fateId = {cap!r}   含 suicide = {cap_ok}")
        print(f"  凶手不是 captain 的 Ship 船员 = {len(bad)} {bad[:10]}")
        from collections import Counter
        dist = Counter(fs.get(c, {}).get("fateId", "<缺失>") for c in ship)
        print("  Ship 区(58 人) 的 fateId 分布:")
        for k, v in dist.most_common():
            print(f"    {k:30} x{v}")
        ok = cap_ok and not bad
        print(f"\n  CheckForKillerCaptain 预期 = {ok}  {'[OK]' if ok else '[X]'}")
        print("  触发点: 离船 -> Tally -> TallyInsurance.State.Idle")
        sys.exit(0 if ok else 1)

    print(f"[i] FateBaseIds 共 {len(bases)} 个；其中 *-killer = {len(kbases)} 个 {kbases}")
    print(f"     suicide-* = {sbases}")
    print(f"[i] Ship 区 {len(ship)} 人（含 captain），Office 区 {len(office)} 人")

    if args.base_fate not in kbases:
        sys.exit(f"[-] --base-fate 必须是 *-killer（有凶手槽位），可选: {kbases}")
    if "suicide" not in args.captain_fate:
        sys.exit("[-] --captain-fate 必须含 'suicide'")
    if args.captain_fate not in bases:
        sys.exit(f"[-] --captain-fate 不是合法 fate 基名")

    src = Path(args.src)
    container, xml = load_save(src)
    faces = read_faces(xml)
    if len(faces) != len(crew):
        sys.exit(f"[-] {src.name} 的 faces 数量 {len(faces)} != {len(crew)}")
    print(f"[i] 基础存档 {src.name}  解对数={len(get_correct_ids(xml))}/{len(crew)}")

    assign = {}
    assign["captain"] = args.captain_fate
    for c in ship:
        if c != "captain":
            assign[c] = f"{args.base_fate}:captain"

    # ---- 自检：谁恰好答对了（会成为 pending-correct）
    pending = [c for c, f in assign.items() if f in fate_ids.get(c, [])]
    print(f"\n[i] 分配方案: captain={assign['captain']}，其余 {len(ship)-1} 人 = {args.base_fate}:captain")
    print(f"    「恰好答对」的人（会成为 pending-correct）= {len(pending)} {pending}")
    if pending:
        print("    [!] 这些人会被计为已猜对；若人数恰好等于分组 num 会被自动登记。")
        print("        建议换一个 --base-fate 让 pending=0。")
        for c in pending:
            print(f"        {c}: 接受列表 = {fate_ids[c]}")

    num = 3   # 全部未登记时 Ship 未解 = 58 -> num = 3
    print(f"    Ship 未解 = {len(ship)} -> 分组 num = {num}")
    print(f"    pending 会不会触发自动登记: {'会 [X]' if len(pending) == num else '不会 [OK]'}")

    if args.report:
        print("\n[i] --report 模式，未写文件")
        return

    if len(pending) == num:
        sys.exit(f"[-] 拒绝生成：pending 人数 {len(pending)} 恰好等于分组 num {num}，"
                 f"玩家一翻书就会被自动登记，状态会跳变。请换 --base-fate。")

    # ---------------- 改写 ----------------
    print(f"\n[i] 改写 faces（58 人命运 + captain 自杀）...")
    for c in ship:
        xml = patch_face(xml, c, marked=False, fate=assign[c])

    # Office 区域复位为「从未到过」
    office_moments = build_office_moments()
    print(f"\n[i] 复位 Office 区域 {OFFICE_DISASTER}（{len(office_moments)} 个 moment）...")
    for mid in office_moments:
        xml = patch_moment(xml, mid, visitCount="0", unlocked="false",
                           revealedGhosts="false", revealedPageInBook="false")
    xml = patch_disaster(xml, OFFICE_DISASTER,
                         revealedChartInBook="false", revealedDisappearancesInBook="false")
    for c in office:
        xml = patch_face(xml, c, marked=False, fate="unknown")
    xml = remove_stats_prefix(xml, f"#dia-{OFFICE_DISASTER}-")
    xml = remove_stats_prefix(xml, "#dia-office-")
    xml = remove_stat(xml, "zone-complete-office")

    # era=1（已看完所有 moment，可离船）；办公室进度必须全是 false
    print(f"\n[i] 设置阶段标志 ...")
    xml = set_general(xml, "era", "1")
    for k in ("officePackageReady", "officePawReady",
              "officeHaveRevealedBook", "officeEndedOnce"):
        xml = set_general(xml, k, "false")

    # 还没离船 => 不能有离船/结算的对白计数（notify 例外：era 0->1 时就播过）
    print(f"\n[i] 清理「尚未离船」不该有的对白计数 ...")
    for sid in ("#dia-ship-end-leave-1", "#dia-ship-end-leave-3",
                "#dia-ship-end-done", "#dia-tally-intro"):
        xml = remove_stat(xml, sid)
    if get_stat(xml, "#dia-ship-end-notify") is None:
        print("    (基础存档无 #dia-ship-end-notify，跳过)")

    # ---------------- 结果 ----------------
    correct = get_correct_ids(xml)
    faces2 = read_faces(xml)
    ok_killer = [c for c in ship if c != "captain"
                 and faces2[c]["fateId"].partition(":")[2] == "captain"]
    cap_ok = "suicide" in faces2["captain"]["fateId"]
    print("\n" + "=" * 64)
    print(f"[结果] era={get_general(xml, 'era')}   解对数 = {len(correct)}/{len(crew)}"
          f"   可达链首项? {'是 [OK]' if len(correct) in ship_correct_chain(len(ship)) else '否 [X]'}")
    print(f"       非船长且凶手=captain 的 Ship 船员 = {len(ok_killer)}/{len(ship)-1}")
    print(f"       captain fateId 含 suicide = {cap_ok}  ({faces2['captain']['fateId']})")
    print(f"       CheckForKillerCaptain 预期 = "
          f"{'True [OK]' if cap_ok and len(ok_killer) == len(ship)-1 else 'False [X]'}")
    print("=" * 64)

    dst = Path(args.dst)
    if dst.exists():
        dst.with_suffix(dst.suffix + ".bak").write_text(
            dst.read_text(encoding="iso-8859-1"), encoding="iso-8859-1")
    save_save(container, xml, dst)
    print(f"\n[+] 已写出: {dst}")
    _, back = load_save(dst)
    print(f"[i] 回读验证: {'明文完全一致 [OK]' if back == xml else '不一致 [X]'}")

    print("\n玩法: 载入该存档后你会在船上（era=1，所有 moment 已看完）。")
    print("      走到船尾的船夫处，看他并交互离船 -> 结算(Tally) -> 保险页出现时成就触发。")
    print("      安装: 复制到 C:\\Users\\<用户名>\\AppData\\LocalLow\\3909\\ObraDinn\\")
    print("            并重命名为 ObraDinnSave-P1.txt / -P2.txt / -P3.txt 之一")


if __name__ == "__main__":
    main()
