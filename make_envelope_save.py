"""生成「信封」存档。

原理（全部来自反编译源码，见 save_format.md）:
  OfficeLogic.cs:86   completedShipZoneCorrectly = SaveData.it.GetZoneIsSolved(Story.Zone.Ship)
  OfficeLogic.cs:134  !completedShipZoneCorrectly ? "office-delivery-envelope" : "office-delivery-package"
  SaveData.cs:319     GetZoneIsSolved(z) <=> GetZoneUnsolvedCount(z) == 0
  SaveData.cs:326     GetZoneUnsolvedCount(z) = 该 zone 中 markedCorrect==false 的船员数
  Story.cs:124        GetDisaster("d070").zone = Office   (唯一不是 Ship 的区域)
  OfficeLogic.cs:428  续玩入口: pawReady -> PawReady; packageReady -> Package; 否则 Intro
  OfficeLogic.cs:92,97 信件口吻: 船已解 -> win; 否则 >=30 对 -> mid; 否则 fail

所以「信封存档」= era=3 + Ship 区 58 人中至少 1 人 markedCorrect="false"

★ 但仅仅改这两处会产生**玩不出来的存档**。还必须把 Office 区域整体复位：
  不变量: 访问过 d070  <=  拿到过包裹  <=  Ship 区 58 人全解对
    - d070 章节在 era != 3 时被封存(BookContent.cs:227 withheld-button)
    - 进 d070 的 moment 只能从办公室 PawReady 支线(OfficeLogic.cs:199/599)
    - 只有 completedShipZoneCorrectly 才能进 Paw* 支线(OfficeLogic.cs:185-215)
  所以信封存档里 d070 必须是「从未到过」，和 P1(天然中途存档)的表示完全一致:
    moments[d070-*]  visitCount=0 unlocked=false revealedGhosts=false revealedPageInBook=false
    disasters[d070]  revealedChartInBook=false revealedDisappearancesInBook=false
    faces[stewcap/mate3]  fateId="unknown" markedCorrect="false"   (nameId 保持 = id，与 P1 一致)
    stat  zone-complete-office 不存在（该 stat 只在离开 d070 moment 时被创建）
  另外信封支线永远到不了 Paw*，所以 officePawReady / officeHaveRevealedBook / officeEndedOnce
  必须是 false（OpenBook 只在 Paw* 状态被调用，officeEndedOnce 只在 Victory 里置 true）。

两种天然存档点（见 Game.cs:170 「开暂停菜单就存档」 / Tally.cs:91 / OfficeLogic.cs:145）:
    desk     递送完毕、停在书桌前（officePackageReady=true，跳过 34s 开场）← 默认
    arrival  刚进办公室 / 停在 Tally→办公室切换点（会重播开场）

用法:
    python make_envelope_save.py                          # 默认: 拿 P2 改, 输出 ObraDinnSave-ENV.txt
    python make_envelope_save.py --flavor arrival         # 从刚进办公室的状态开始
    python make_envelope_save.py --unmark seag mate2      # 指定要"打错"的船员
    python make_envelope_save.py --letter fail            # 压到 <30 对, 拿 fail 信件
    python make_envelope_save.py --dst ObraDinnSave-P1.txt

生成后可用 python inspect_save.py <文件> 验证一致性。
"""
import argparse
import base64
import re
import sys
from pathlib import Path

from parse_assets import load_assets, parse_csv
from tea_decrypt import KEY, to_bytes, to_longs, xxtea_decrypt
from test_roundtrip import csharp_encrypt

# 注: 输出刻意只用 ASCII 符号 + 中文，避免 GBK 控制台/管道下 UnicodeEncodeError

# Story.cs:122-124 手写死的失踪名单 + Office 区域
DISAPPEAR_CREW = {
    "d030": ["sea5", "sea1"],
    "d060": ["top5", "sea2", "sead", "purser", "top8", "sea9", "bosunmate"],
    "d080": ["pass3", "pass4", "stewm4", "surgeon"],
}
OFFICE_DISASTER = "d070"

MID_THRESHOLD = 30          # OfficeLogic.cs:92  GetNumFatesCorrect() >= 30 -> office_letter_mid

DATA_RE = re.compile(r"<data>(.*?)</data>", re.S)
GENERAL_RE = re.compile(r"<general\b[^>]*>")
FACE_RE = re.compile(r"<face\b[^>]*?/>", re.S)
MOMENT_RE = re.compile(r"<moment\b[^>]*?/>", re.S)
DISASTER_RE = re.compile(r"<disaster\b[^>]*?/>", re.S)
STAT_RE = re.compile(r"<stat>\s*<id>(.*?)</id>\s*<val>(.*?)</val>\s*</stat>", re.S)
STATS_RE = re.compile(r"<stats\s*>(.*?)</stats>", re.S)


# ------------------------------------------------------------------ 区域计算
def build_zones():
    """复刻 Story.cs 的 climax 构建，返回 (全部crew, Ship区, Office区)"""
    A = load_assets()
    _, mrows = parse_csv(A["Moments"])
    _, crows = parse_csv(A["Crew"])

    climax = {}
    for m in mrows:
        disaster = m["id"].split("-")[0]
        for cid in [x.strip() for x in m["die"].split(",") if x.strip()]:
            if cid != "-":
                climax[cid] = disaster
    for did, ids in DISAPPEAR_CREW.items():
        for cid in ids:
            climax[cid] = did

    crew = [r["id"] for r in crows]
    unknown = [c for c in crew if c not in climax]
    if unknown:
        raise RuntimeError(f"有船员没有 climax（数据异常）: {unknown}")
    office = [c for c in crew if climax[c] == OFFICE_DISASTER]
    ship = [c for c in crew if climax[c] != OFFICE_DISASTER]
    return crew, ship, office


# ------------------------------------------------------------------ 读写存档
def load_save(path: Path):
    """返回 (外层容器原文, 明文 XML)

    注意 newline="" —— 容器必须逐字节保真。带换行转换的话，
    在 LF 系统（macOS/Linux）上会把 \\r\\n 静默改成 \\n，改档就损坏了。
    （实测现容器是单行、一个换行符都没有，但这里不该依赖这一点。）
    """
    with open(path, "r", encoding="iso-8859-1", newline="") as f:
        text = f.read()
    m = DATA_RE.search(text)
    if not m:
        raise RuntimeError(f"{path} 里找不到 <data> 块")
    cipher = base64.b64decode(m.group(1).strip())
    plain = to_bytes(xxtea_decrypt(to_longs(cipher), to_longs(KEY)))
    xml = plain.decode("utf-8").rstrip("\x00")
    return text, xml


def save_save(container_text: str, xml: str, dst: Path):
    """改好的 XML -> XXTEA -> Base64 -> 替换 <data> -> 写文件（逐字节保真）"""
    raw = xml.encode("utf-8")
    raw += b"\x00" * (-len(raw) % 4)        # 补齐到 4 的倍数（C# ToLongs 等价行为）
    b64 = base64.b64encode(csharp_encrypt(raw, KEY)).decode("ascii")
    out = DATA_RE.sub(lambda _m: f"<data>{b64}</data>", container_text, count=1)
    with open(dst, "w", encoding="iso-8859-1", newline="") as f:
        f.write(out)


# ------------------------------------------------------------------ 字段改写
def set_general(xml: str, name: str, value: str) -> str:
    m = GENERAL_RE.search(xml)
    tag = m.group(0)
    new_tag, n = re.subn(rf'\b{name}="[^"]*"', f'{name}="{value}"', tag, count=1)
    if n == 0:
        raise RuntimeError(f"<general> 里没有属性 {name}")
    print(f"    general.{name} -> {value}")
    return xml[:m.start()] + new_tag + xml[m.end():]


def patch_face(xml: str, crew_id: str, marked: bool, fate: str | None) -> str:
    for m in FACE_RE.finditer(xml):
        seg = m.group(0)
        if f'id="{crew_id}"' not in seg:
            continue
        new = re.sub(r'markedCorrect="[^"]*"', f'markedCorrect="{str(marked).lower()}"', seg)
        if fate is not None:
            new = re.sub(r'fateId="[^"]*"', f'fateId="{fate}"', new)
        print(f"    face[{crew_id}] -> markedCorrect={str(marked).lower()}"
              + (f", fateId={fate}" if fate is not None else ""))
        return xml[:m.start()] + new + xml[m.end():]
    raise RuntimeError(f"XML 里找不到船员 {crew_id!r}")


def get_correct_ids(xml: str) -> set:
    return {m.group(1) for m in re.finditer(r'<face\b[^>]*?id="([^"]+)"[^>]*?markedCorrect="true"', xml)}


def build_office_moments():
    """d070 章的 moment id 列表"""
    A = load_assets()
    _, mrows = parse_csv(A["Moments"])
    return [m["id"] for m in mrows if m["id"].split("-")[0] == OFFICE_DISASTER]


def build_fate_ids():
    """crewId -> 该船员可接受的 fateId 列表（Crew CSV 的 fate 列）

    对应 Manifest.IsCorrectFate(crewId, fateId) = crew.fateIds.Contains(fateId)
    """
    A = load_assets()
    _, crows = parse_csv(A["Crew"])
    return {r["id"]: [x.strip() for x in r["fate"].split(",") if x.strip()] for r in crows}


def auto_confirm_batch(zone_unsolved: int) -> int:
    """FateEditor.cs:653-658  自动确认每组几人

    int num = 3; if (zoneUnsolvedCount == 4 || zoneUnsolvedCount == 2) num = 2;
    """
    return 2 if zone_unsolved in (4, 2) else 3


def ship_correct_chain(ship_total: int):
    """船上阶段可达的「Ship 区解对数」升序序列。

    markedCorrect=true 在非调试代码里只有 FateEditor.cs:683 一处，位于 UpdateFateGuesses 内，
    且一次恰好登记 num 人（num = auto_confirm_batch(当时的未解数)）。
    未解数又随解对数变化 ⇒ 解对数是一条确定性链，不是任意值都能达到。
    58 人时: 0,3,6,...,51,54,56,58  ⇒ 52/53/55/57 永远无法到达。
    """
    vals, c = [0], 0
    while c < ship_total:
        u = ship_total - c
        num = auto_confirm_batch(u)
        if num > u:
            break
        c += num
        vals.append(c)
    return vals


def max_reachable_envelope(ship_total: int) -> int:
    """信封（Ship 未解完）时可达的最大解对数"""
    return max(v for v in ship_correct_chain(ship_total) if v < ship_total)


def max_reachable_below(ship_total: int, limit: int) -> int:
    """总解对数 < limit 且可达的最大值（信封存档 Office 区必为 0）"""
    cand = [v for v in ship_correct_chain(ship_total) if v < limit]
    return max(cand) if cand else 0


def _patch_element(xml, regex, ident, **kv):
    """把单个 <tag id="ident" .../> 元素里的属性改掉"""
    for m in regex.finditer(xml):
        seg = m.group(0)
        if f'id="{ident}"' not in seg:
            continue
        new = seg
        for k, v in kv.items():
            new, n = re.subn(rf'\b{k}="[^"]*"', f'{k}="{v}"', new, count=1)
            if n == 0:
                raise RuntimeError(f"{ident}: 元素里没有属性 {k}")
        return xml[:m.start()] + new + xml[m.end():]
    raise RuntimeError(f"XML 里找不到元素 id={ident!r}")


def patch_moment(xml, moment_id, **kv):
    return _patch_element(xml, MOMENT_RE, moment_id, **kv)


def patch_disaster(xml, disaster_id, **kv):
    return _patch_element(xml, DISASTER_RE, disaster_id, **kv)


def _stats_span(xml):
    m = STATS_RE.search(xml)
    if not m:
        raise RuntimeError("XML 里没有 <stats>...</stats> 块")
    return m.start(1), m.group(1), m.end(1)


def get_stat(xml, stat_id, default=None):
    for i, v in STAT_RE.findall(xml):
        if i == stat_id:
            return v
    return default


def set_stat(xml, stat_id, val):
    s, body, e = _stats_span(xml)
    pat = re.compile(r"<stat>\s*<id>" + re.escape(stat_id) + r"</id>\s*<val>.*?</val>\s*</stat>", re.S)
    rep = f"<stat><id>{stat_id}</id><val>{val}</val></stat>"
    if pat.search(body):
        new = pat.sub(lambda _m: rep, body, count=1)
    else:
        new = body + rep
    print(f"    stat {stat_id} -> {val}")
    return xml[:s] + new + xml[e:]


def remove_stat(xml, stat_id):
    s, body, e = _stats_span(xml)
    pat = re.compile(r"<stat>\s*<id>" + re.escape(stat_id) + r"</id>\s*<val>.*?</val>\s*</stat>", re.S)
    new, n = pat.subn("", body)
    if n:
        print(f"    移除 stat {stat_id}")
    return xml[:s] + new + xml[e:]


def remove_stats_prefix(xml, prefix):
    s, body, e = _stats_span(xml)
    kept, removed = [], []
    for m in STAT_RE.finditer(body):
        (removed if m.group(1).startswith(prefix) else kept).append(m.group(0))
    if removed:
        print(f"    移除 stat {removed}")
    return xml[:s] + "".join(kept) + xml[e:]


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser(description="生成「信封」结局存档")
    ap.add_argument("--src", default="ObraDinnSave-P2.txt",
                    help="基础存档（默认 ObraDinnSave-P2.txt，即已通关的办公室存档）")
    ap.add_argument("--dst", default="ObraDinnSave-ENV.txt",
                    help="输出文件名（默认 ObraDinnSave-ENV.txt）")
    ap.add_argument("--unmark", nargs="*", default=None,
                    help="要打成「未解对」的船员 id；默认自动选一个 Ship 区船员")
    ap.add_argument("--letter", choices=["mid", "fail"], default="mid",
                    help="信件口吻：mid=>=30 对（默认），fail=<30 对")
    ap.add_argument("--flavor", choices=["desk", "arrival"], default="desk",
                    help="desk=递送完毕停在书桌前(默认，跳过 34s 开场)；arrival=刚进办公室")
    ap.add_argument("--keep-fate", action="store_true",
                    help="不把未解船员的 fateId 改成 unknown")
    args = ap.parse_args()

    src, dst = Path(args.src), Path(args.dst)
    if not src.exists():
        sys.exit(f"[-] 找不到基础存档: {src}")

    crew, ship, office = build_zones()
    print(f"[i] 区域: Ship={len(ship)}  Office={len(office)} {office}  (共 {len(crew)})")

    container, xml = load_save(src)
    correct = get_correct_ids(xml)
    if any(c not in correct for c in ship):
        sys.exit(f"[-] {src.name} 的 Ship 区并未全部解对（像是已经改过的信封存档）。\n"
                 f"    用它当底会叠加改动、产生不可这一版的状态。\n"
                 f"    请用 --src 指定原始存档，例如 --src ObraDinnSave-P2.original.txt")
    print(f"[i] 基础存档 {src.name}: markedCorrect={len(correct)}/{len(crew)}")
    print(f"    Ship 区已解 {len([c for c in ship if c in correct])}/{len(ship)}")

    # ---- 1) 把 Office 区域(d070) 复位成「从未到过」
    #        不变量: 访问过 d070 <= 拿到过包裹 <= Ship 区全解对
    office_moments = build_office_moments()
    print(f"\n[i] 复位 Office 区域 {OFFICE_DISASTER}（{len(office_moments)} 个 moment）...")
    for mid in office_moments:
        xml = patch_moment(xml, mid, visitCount="0", unlocked="false",
                           revealedGhosts="false", revealedPageInBook="false")
    print(f"    moments[{OFFICE_DISASTER}-*] x{len(office_moments)} -> 全部未访问")
    xml = patch_disaster(xml, OFFICE_DISASTER, revealedChartInBook="false",
                         revealedDisappearancesInBook="false")
    print(f"    disasters[{OFFICE_DISASTER}] -> revealedChartInBook=false, "
          f"revealedDisappearancesInBook=false")
    for cid in office:
        xml = patch_face(xml, cid, marked=False, fate="unknown")
    # #dia-<momentId> 表示看过该 moment 的入场对白（MomentLogic.cs:191）
    # 既然 d070 从未到过，这些 stat 必须一并移除
    xml = remove_stats_prefix(xml, f"#dia-{OFFICE_DISASTER}-")
    xml = remove_stat(xml, "zone-complete-office")

    # ---- 2) 办公室进度标志
    print(f"\n[i] 设置办公室进度 (flavor = {args.flavor}) ...")
    xml = set_general(xml, "era", "3")                        # 办公室场景
    xml = set_general(xml, "officePawReady", "false")         # 信封支线到不了 Paw*
    xml = set_general(xml, "officeHaveRevealedBook", "false")  # OpenBook 只在 Paw* 里调用
    xml = set_general(xml, "officeEndedOnce", "false")         # 只有 Victory 才置 true
    xml = remove_stats_prefix(xml, "#dia-office-")
    if args.flavor == "desk":
        # OfficeLogic.cs:145 游戏自己在这里存档 => 这是原生存档点
        xml = set_general(xml, "officePackageReady", "true")
        xml = set_stat(xml, "#dia-office-intro", "1")
        xml = set_stat(xml, "#dia-office-delivery-envelope", "1")
    else:
        # 刚进办公室 / 停在 Tally->办公室切换点；开场对白会重播
        xml = set_general(xml, "officePackageReady", "false")

    # ---- 3) 结局流程对白计数归一为「第一次」
    #  ShipEnder: 离船一次 => notify/leave/done 各一次；Tally 一次；Office 入场一次。
    #  证据(P2): office-delivery-envelope=2 + delivery-package=1 => 离船 3 次，
    #  而 ship-end-done=3 / tally-intro=3 / leave-1=2 / leave-3=1
    #  => leave-1 = 船未解完的提示（对应信封），leave-3 = 船已解完的提示。
    #  notify 只在 era==0 时播(ShipEnder.Start 直接进 ZoneDone) => 永远是 1。
    print(f"\n[i] 归一结局流程对白计数 ...")
    for sid in ("#dia-ship-end-notify", "#dia-ship-end-leave-1",
                "#dia-ship-end-done", "#dia-tally-intro"):
        if get_stat(xml, sid) is not None:
            xml = set_stat(xml, sid, "1")
    xml = remove_stat(xml, "#dia-ship-end-leave-3")   # 「船已解完」的提示，信封存档不该有

    # ---- 4) 让 Ship 区未解完，且解对数落在「可达值」上
    correct = get_correct_ids(xml)
    ship_correct = [c for c in ship if c in correct]
    if args.unmark:
        targets = list(args.unmark)
    else:
        # 每次批量登记恰好 +2 或 +3 ⇒ 解对数只能取特定值，否则是游戏里永远出现不了的状态
        target = (max_reachable_below(len(ship), MID_THRESHOLD)   # fail 信件: <30 的最大可达值 = 27
                  if args.letter == "fail" else
                  max_reachable_envelope(len(ship)))              # mid 信件: <58 的最大可达值 = 56
        n_unmark = max(len(ship_correct) - target, 1)
        targets = ship_correct[:n_unmark]
        print(f"\n[i] 目标解对数 = {target}（可达值；链 = {ship_correct_chain(len(ship))}）")
        print(f"    需打错 {n_unmark} 个 Ship 区船员")

    bad = [c for c in targets if c in office]
    if bad:
        sys.exit(f"[-] {bad} 属于 Office 区域，打错它们不会产生信封。请换 Ship 区船员。")
    missing = [c for c in targets if c not in crew]
    if missing:
        sys.exit(f"[-] 不存在的船员 id: {missing}")

    print(f"\n[i] 改写 Ship 区 faces（共 {len(targets)} 人）...")
    fate = None if args.keep_fate else "unknown"
    for cid in targets:
        xml = patch_face(xml, cid, marked=False, fate=fate)

    # ---- 自检
    after = get_correct_ids(xml)
    ship_unsolved = [c for c in ship if c not in after]
    n_correct = len(after)
    is_envelope = len(ship_unsolved) > 0
    tier = "win(package)" if not is_envelope else ("mid" if n_correct >= MID_THRESHOLD else "fail")

    print("\n" + "=" * 62)
    chain = ship_correct_chain(len(ship))
    reachable = set(chain) | {v + 2 for v in chain}
    print(f"[结果] markedCorrect = {n_correct}/{len(crew)}"
          f"   可达值? {'是 [OK]' if n_correct in reachable else '否 [X]'}")
    print(f"       Ship 区未解对 = {len(ship_unsolved)} 人 {ship_unsolved[:10]}")
    print(f"       completedShipZoneCorrectly = {not is_envelope}")
    print(f"       => 信封/包裹 = {'信封 ENVELOPE [OK]' if is_envelope else '包裹 PACKAGE [X]'}"
          f"   信件口吻 = {tier}")
    print("=" * 62)
    if not is_envelope:
        sys.exit("[-] 没做成信封，检查 --unmark 参数")

    # ---- 写出
    if dst.exists():
        bak = dst.with_suffix(dst.suffix + ".bak")
        bak.write_text(dst.read_text(encoding="iso-8859-1"), encoding="iso-8859-1")
        print(f"\n[i] 已备份原文件 -> {bak.name}")
    save_save(container, xml, dst)
    print(f"[+] 已写出: {dst}")

    # ---- 回读验证
    _, back = load_save(dst)
    back_ok = back == xml
    print(f"[i] 回读验证: {'明文完全一致 [OK]' if back_ok else '不一致 [X]'}")
    print(f"    回读 markedCorrect = {len(get_correct_ids(back))}/{len(crew)}")

    print(f"\n安装方法: 把 {dst.name} 复制到")
    print("          C:\\Users\\<用户名>\\AppData\\LocalLow\\3909\\ObraDinn\\")
    print("          并重命名为 ObraDinnSave-P1.txt / -P2.txt / -P3.txt 之一")
    print(f"          验证: python inspect_save.py {dst.name}")


if __name__ == "__main__":
    main()
