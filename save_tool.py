#!/usr/bin/env python3
"""Obra Dinn 存档工具箱 —— 查看 / 改性别 / 导入 / 导出。

设计成「库 + 薄 CLI」：GUI 直接 `import save_tool` 调函数即可，
命令行也能单独用。

    info    FILE...                  摘要（era / 结局档 / 性别 / 解锁度 / 标记）
    gender  FILE... [--female|--male|--toggle] [-o OUT]
                                     改主人公性别（只写 general.playerFemale）
    slots                            列出游戏目录三个槽位
    export  SRC DST                  导出（校验 + 复制，不动游戏目录）
    import  SRC --slot P1|P2|P3      导入到游戏目录（自动备份 + 回读校验）

性别字段的依据：
    SaveData.cs:1289-1290   [XmlAttribute] public bool playerFemale { get; set; }
    SaveData.cs:1302-1309   public Manifest.Gender playerGender => playerFemale ? Female : Male;
                            （只读计算属性 → 不落盘，改 playerFemale 就够）
    消费点全部是文本：OfficeLogic.cs:89/94/99（信件）、Lang.GetGendered /
    GetGenderedForPlayer、PageTemplate.cs:83、LocalizedUi.cs:19、Dialog.cs:189、
    Book.cs:1135；另外 Intro.cs:46 选开场旁白音轨（只在新游戏时跑）。
    ⇒ 无任何玩法 / 存档状态联动，可安全任意切换。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from make_envelope_save import (DISASTER_RE, FACE_RE, GENERAL_RE, MID_THRESHOLD,
                                MOMENT_RE, build_zones, get_correct_ids,
                                load_save, save_save, set_general)

SLOTS = ("P1", "P2", "P3")
ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
DEFAULT_WORKSPACE = Path(__file__).resolve().parent


# ------------------------------------------------------------------ 路径
MAC_GAME_APP = "Return of the Obra Dinn.app"


def _mac_bundle_id_dirs(support: Path) -> list[Path]:
    """从游戏 .app 的 Info.plist 读 CFBundleIdentifier 当目录名

    ★ macOS 实测（macOS 26 + 真机装的 Return of the Obra Dinn.app）：
      Unity 在 macOS 上用的是 **bundle identifier** `co.3909.ObraDinn`，
      而不是 Windows 那种 `<公司>/<产品>` 目录。文件布局两边完全一致
      （都有 `ObraDinnSave-P1.txt` 和 `Backup/ObraDinnSave-P1-Recent.txt`）。
      读 plist 比写死常量更牢靠 —— 换个发行版（如 Steam）标识符可能不同。
    """
    out: list[Path] = []
    for root in (Path("/Applications"), Path.home() / "Applications"):
        plist = root / MAC_GAME_APP / "Contents" / "Info.plist"
        if not plist.is_file():
            continue
        try:
            import plistlib
            with plist.open("rb") as f:
                bid = plistlib.load(f).get("CFBundleIdentifier")
        except Exception:                               # noqa: BLE001
            continue
        if bid and (support / bid) not in out:
            out.append(support / bid)
    return out


def game_dir() -> Path:
    """游戏存档目录（Unity 的 persistentDataPath）；可用环境变量 OBRADINN_SAVE_DIR 覆盖

    Windows  %USERPROFILE%\\AppData\\LocalLow\\<公司>\\<产品>  —— 实测 `3909\\ObraDinn`
    macOS    ~/Library/Application Support\\<bundle identifier>  —— **实测 `co.3909.ObraDinn`**
             （不是 `3909/ObraDinn`！Windows 那套规则不通用，见 _mac_bundle_id_dirs）
    Linux    ~/.config/unity3d/<公司>/<产品>
    """
    env = os.environ.get("OBRADINN_SAVE_DIR")
    if env:
        return Path(env)
    home = Path.home()
    if sys.platform == "darwin":
        support = home / "Library" / "Application Support"
        cands = [support / "co.3909.ObraDinn"]           # 实测优先
        cands += _mac_bundle_id_dirs(support)            # 装了游戏就按 Info.plist 读
        cands += [support / "3909" / "ObraDinn",
                  support / "unity.3909.ObraDinn",
                  support / "Obra Dinn",
                  support / "3909" / "Obra Dinn"]
    elif sys.platform.startswith("linux"):
        cfg = home / ".config"
        cands = [cfg / "unity3d" / "3909" / "ObraDinn",
                 cfg / "3909" / "ObraDinn"]
    else:
        return home / "AppData" / "LocalLow" / "3909" / "ObraDinn"
    for c in cands:
        if c.is_dir():
            return c
    return cands[0]


def slot_path(slot: str, root: Path | None = None) -> Path:
    slot = slot.upper()
    if slot not in SLOTS:
        raise ValueError(f"槽位只能是 {SLOTS}，收到 {slot!r}")
    return (root or game_dir()) / f"ObraDinnSave-{slot}.txt"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ 校验 / 摘要
def load_checked(path: Path):
    """解密并做基本结构校验；失败抛 ValueError（带可读原因）"""
    path = Path(path)
    if not path.exists():
        raise ValueError(f"文件不存在: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"文件是空的: {path}")
    try:
        container, xml = load_save(path)
    except Exception as e:                                  # noqa: BLE001
        raise ValueError(f"不是有效的 Obra Dinn 存档（解密失败）: {e}") from e
    if "<general" not in xml:
        raise ValueError("解密成功但内容不像存档（找不到 <general>）")
    if not FACE_RE.search(xml):
        raise ValueError("解密成功但内容不像存档（找不到 <face>）")
    return container, xml


def _elements(xml, regex):
    out = {}
    for m in regex.finditer(xml):
        a = dict(ATTR_RE.findall(m.group(0)))
        if a.get("id"):
            out[a["id"]] = a
    return out


def get_general_attr(xml: str, name: str, default=None):
    m = GENERAL_RE.search(xml)
    if not m:
        return default
    mm = re.search(rf'\b{name}="([^"]*)"', m.group(0))
    return mm.group(1) if mm else default


def get_gender(xml: str) -> str:
    """'male' | 'female'"""
    v = get_general_attr(xml, "playerFemale")
    if v is None:
        raise ValueError("general 里没有 playerFemale 属性")
    return "female" if v.lower() == "true" else "male"


def set_gender(xml: str, female: bool) -> str:
    return set_general(xml, "playerFemale", "true" if female else "false")


_ZONES: tuple | None = None


def _zones() -> tuple:
    """默认的 crew / ship / office 名单（进程内只解析一次）。

    优先读 `txtAssetDump/` 资产表；**打包成 exe 后没有那个目录**，就退回
    `gen_gui_data.py` 固化的 `gui/data.py`（同源，都是 `build_zones()` 的结果）。
    不这样兜底的话，exe 里任何漏传名单的调用都会炸成 `KeyError('Moments')`
    ——备份列表、导入、导出都踩过。

    缓存还能省下重复解析：`list_backups` 对每个备份文件都要 `describe` 一次。
    """
    global _ZONES
    if _ZONES is not None:
        return _ZONES
    try:
        _ZONES = build_zones()
    except Exception as e:                              # noqa: BLE001
        print(f"[i] 跳过资产表（{e!r}），改用内置 gui/data.py 名单", file=sys.stderr)
        try:
            from gui.data import CREW, OFFICE, SHIP
        except ImportError:                             # 直接跑脚本时
            from data import CREW, OFFICE, SHIP          # type: ignore
        _ZONES = (CREW, SHIP, OFFICE)
    return _ZONES


def describe(path: Path, crew=None, ship=None, office=None) -> dict:
    """给 GUI / CLI 用的摘要（全部为纯 Python 值，可直接塞进 JSON）"""
    path = Path(path)
    if crew is None:
        crew, ship, office = _zones()
    _, xml = load_checked(path)

    faces = _elements(xml, FACE_RE)
    moments = _elements(xml, MOMENT_RE)
    disasters = _elements(xml, DISASTER_RE)
    correct = get_correct_ids(xml)

    ship_ok = [c for c in ship if c in correct]
    office_ok = [c for c in office if c in correct]
    ship_solved = len(ship_ok) == len(ship)
    n = len(correct)

    if ship_solved:
        tier, delivery = "win", "package"
    else:
        tier = "mid" if n >= MID_THRESHOLD else "fail"
        delivery = "envelope"

    visited = [m for m, a in moments.items() if int(a.get("visitCount", 0)) > 0]
    era = int(get_general_attr(xml, "era", "0"))
    phase = {0: "on-ship", 1: "ready-to-leave", 2: "tally", 3: "office"}.get(era, f"era{era}")
    return {
        "file": str(path),
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "sha256_16": sha256(path)[:16],
        "era": era,
        "phase": phase,                       # 当前在流程哪一段
        "gender": get_gender(xml),
        "playTime": float(get_general_attr(xml, "playTime", "0")),
        "fates_correct": n,
        "crew_total": len(crew),
        "ship_correct": len(ship_ok),
        "ship_total": len(ship),
        "office_correct": len(office_ok),
        "office_total": len(office),
        "ship_solved": ship_solved,
        "ending": tier,                       # win / mid / fail
        "delivery": delivery,                 # package / envelope
        "moments_visited": len(visited),
        "moments_total": len(moments),
        "charts_revealed": sum(1 for a in disasters.values()
                               if a.get("revealedChartInBook") == "true"),
        "bookVisitedLastPage": get_general_attr(xml, "bookVisitedLastPage") == "true",
        "officePackageReady": get_general_attr(xml, "officePackageReady") == "true",
        "officePawReady": get_general_attr(xml, "officePawReady") == "true",
        "officeHaveRevealedBook": get_general_attr(xml, "officeHaveRevealedBook") == "true",
        "officeEndedOnce": get_general_attr(xml, "officeEndedOnce") == "true",
        "blank_faces": sum(1 for f in faces.values()
                           if f.get("nameId") == "unknown" and f.get("fateId") == "unknown"),
        "faces_total": len(faces),
    }


# ------------------------------------------------------------------ 导入 / 导出
def export_save(src: Path, dst: Path) -> dict:
    """把存档导出到任意路径（只读源，不碰游戏目录）"""
    src, dst = Path(src), Path(dst)
    load_checked(src)                                   # 先证明源是好的
    if dst.is_dir():
        dst = dst / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    if sha256(src) != sha256(dst):
        raise RuntimeError("导出后哈希不一致，请重试")
    return {"src": str(src), "dst": str(dst), "bytes": dst.stat().st_size,
            "sha256_16": sha256(dst)[:16]}


def backup_dir(workspace: Path | None = None) -> Path:
    """工具自己产生备份的落地目录：<workspace>/_backups

    放在子目录里，这样它不会混进存档库列表。
    """
    ws = Path(workspace) if workspace else DEFAULT_WORKSPACE
    d = ws / "_backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_slot(slot: str, tag: str = "import", workspace: Path | None = None) -> list[str]:
    """把游戏目录里的槽位备份到 游戏 Backup\\ 与 <workspace>/_backups 各一份"""
    src = slot_path(slot)
    if not src.exists():
        return []
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    dirs = [src.parent / "Backup", backup_dir(workspace)]
    made = []
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"ObraDinnSave-{slot.upper()}-before{tag}-{ts}.txt"
        shutil.copy2(src, p)
        made.append(str(p))
    return made


def import_save(src: Path, slot: str, workspace: Path | None = None,
                do_backup: bool = True, dry_run: bool = False,
                force: bool = False) -> dict:
    """把任意存档文件装进游戏目录的某个槽位（自动备份 + 回读校验）

    ⚠ 游戏自己会在每次存档前把上一份写成 `Backup\\<槽位>-Recent.txt`——
      那是最后的救命稻草；`--no-backup` 要配 `--yes` 才能越过已存在的槽位。
    """
    src = Path(src)
    info = describe(src)                                # 顺带证明源可用
    dst = slot_path(slot)
    result = {"src": str(src), "slot": slot.upper(), "dst": str(dst),
              "backups": [], "dry_run": dry_run, "info": info}
    if dry_run:
        result["existed"] = dst.exists()
        return result
    if dst.parent and not dst.parent.exists():
        raise ValueError(f"游戏存档目录不存在: {dst.parent}\n"
                         f"（可以用环境变量 OBRADINN_SAVE_DIR 指定）")
    if dst.exists() and not do_backup and not force:
        raise ValueError("目标槽位已存在，且指定了 --no-backup（不备份）。\n"
                         "  要么去掉 --no-backup 让它自动备份，\n"
                         "  要么加 --yes 确认不需要备份。")
    if do_backup:
        result["backups"] = backup_slot(slot, "import", workspace)
    shutil.copy2(src, dst)
    if sha256(src) != sha256(dst):
        raise RuntimeError("写入后哈希不一致！请用备份恢复")
    result["bytes"] = dst.stat().st_size
    result["sha256_16"] = sha256(dst)[:16]
    return result


def list_backups(slot: str, workspace: Path | None = None,
                 crew=None, ship=None, office=None) -> list[dict]:
    """列出某个槽位所有可用的备份（新→旧）

    来源三类：
      game-recent  游戏自带 `Backup\\<槽位>-Recent.txt`（存档前的上一份，最可靠）
      game-backup  我们写入前自动存的 `Backup\\<槽位>-before*.txt`
      workspace    工作区里的 `*.before*.txt` / `*-<槽位>.txt` 副本

    `crew/ship/office` 透传给 `describe()`；打包运行时必须由调用方传入。
    """
    slot = slot.upper()
    ws = Path(workspace) if workspace else DEFAULT_WORKSPACE
    gd = game_dir()
    found: list[Path] = []
    rec = gd / "Backup" / f"ObraDinnSave-{slot}-Recent.txt"
    if rec.exists():
        found.append(rec)
    for d in (gd / "Backup", ws, ws / "_backups"):
        if not d.exists():
            continue
        for pat in (f"ObraDinnSave-{slot}-before*.txt", f"ObraDinnSave-{slot}.before*.txt"):
            found += sorted(d.glob(pat))
    out = []
    for p in dict.fromkeys(found):                    # 去重且保序
        row = {"path": str(p), "name": p.name, "bytes": p.stat().st_size,
               "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")}
        try:
            row["sha256_16"] = sha256(p)[:16]
            row["info"] = describe(p, crew, ship, office)
        except Exception as e:                        # noqa: BLE001
            row["error"] = str(e)
        out.append(row)
    return sorted(out, key=lambda r: r["mtime"], reverse=True)


def list_slots(root: Path | None = None,
               crew=None, ship=None, office=None) -> list[dict]:
    out = []
    for s in SLOTS:
        p = slot_path(s, root)
        row = {"slot": s, "path": str(p), "exists": p.exists()}
        if p.exists():
            try:
                d = describe(p, crew, ship, office)
                row.update({k: d[k] for k in
                            ("era", "phase", "gender", "fates_correct", "crew_total",
                             "ending", "delivery", "bytes", "sha256_16",
                             "moments_visited", "moments_total", "charts_revealed")})
            except Exception as e:                       # noqa: BLE001
                row["error"] = str(e)
        out.append(row)
    return out


# ------------------------------------------------------------------ CLI
def _fmt(d: dict) -> str:
    return (f"{d['fates_correct']:>2}/{d['crew_total']}  {d['phase']:<14} "
            f"(若现在离船 => {d['ending']}/{d['delivery']})  era={d['era']} "
            f"{d['gender']:<6} 页 {d['moments_visited']}/{d['moments_total']}  "
            f"图 {d['charts_revealed']}  {d['bytes']}B  {d['sha256_16']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Obra Dinn 存档工具箱")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="查看存档摘要")
    p.add_argument("files", nargs="+")

    p = sub.add_parser("gender", help="改主人公性别")
    p.add_argument("files", nargs="+")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--female", action="store_true")
    g.add_argument("--male", action="store_true")
    g.add_argument("--toggle", action="store_true", help="male <-> female")
    p.add_argument("-o", "--out", help="输出文件名（默认 <原名>.gender.txt）")

    p = sub.add_parser("slots", help="列出游戏目录三个槽位")
    p.add_argument("--root", help="覆盖游戏存档目录")

    p = sub.add_parser("export", help="导出（校验 + 复制）")
    p.add_argument("src")
    p.add_argument("dst")

    p = sub.add_parser("import", help="导入到游戏目录")
    p.add_argument("src")
    p.add_argument("--slot", required=True, choices=SLOTS)
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true",
                   help="配合 --no-backup：确认即便槽位已存在也不备份")

    p = sub.add_parser("backups", help="列出某个槽位可用的备份")
    p.add_argument("--slot", required=True, choices=SLOTS)

    args = ap.parse_args(argv)
    crew, ship, office = build_zones()

    if args.cmd == "info":
        for f in args.files:
            try:
                d = describe(Path(f), crew, ship, office)
            except ValueError as e:
                print(f"[X] {Path(f).name}: {e}")
                continue
            print(f"[i] {d['name']}: {_fmt(d)}")
            print(f"      Ship {d['ship_correct']}/{d['ship_total']}"
                  f"  Office {d['office_correct']}/{d['office_total']}"
                  f"  空白脸 {d['blank_faces']}/{d['faces_total']}"
                  f"  末页已看={d['bookVisitedLastPage']}")
            print(f"      packageReady={d['officePackageReady']}"
                  f"  pawReady={d['officePawReady']}"
                  f"  revealedBook={d['officeHaveRevealedBook']}"
                  f"  endedOnce={d['officeEndedOnce']}")
        return 0

    if args.cmd == "slots":
        root = Path(args.root) if args.root else None
        print(f"[i] 游戏目录: {root or game_dir()}")
        for r in list_slots(root):
            if not r["exists"]:
                print(f"    {r['slot']}  <空>")
            elif "error" in r:
                print(f"    {r['slot']}  [X] {r['error']}")
            else:
                print(f"    {r['slot']}  {_fmt(r)}")
        return 0

    if args.cmd == "gender":
        for f in args.files:
            src = Path(f)
            try:
                container, xml = load_checked(src)
                cur = get_gender(xml)
            except ValueError as e:
                print(f"[-] {src.name}: {e}")
                return 1
            if args.toggle:
                want = cur != "female"
            elif args.female or args.male:
                want = args.female
            else:
                print(f"[i] {src.name}: 当前 {cur}（用 --female / --male / --toggle 指定目标）")
                continue
            if want == (cur == "female"):
                print(f"[=] {src.name}: 已经是 {cur}，跳过")
                continue
            print(f"[i] {src.name}: {cur} -> {'female' if want else 'male'}")
            xml = set_gender(xml, want)
            dst = Path(args.out) if args.out else src.with_suffix(".gender.txt")
            save_save(container, xml, dst)
            _, back = load_save(dst)
            ok = get_gender(back) == ("female" if want else "male")
            print(f"[+] 已写出 {dst}  {'[OK]' if ok else '[X]'}")
        return 0

    if args.cmd == "export":
        try:
            r = export_save(Path(args.src), Path(args.dst))
        except (ValueError, RuntimeError) as e:
            print(f"[-] {e}")
            return 1
        print(f"[+] 导出 {r['src']} -> {r['dst']}  {r['bytes']}B  {r['sha256_16']}")
        return 0

    if args.cmd == "import":
        try:
            r = import_save(Path(args.src), args.slot, do_backup=not args.no_backup,
                            dry_run=args.dry_run, force=args.yes)
        except (ValueError, RuntimeError) as e:
            print(f"[-] {e}")
            return 1
        if r["dry_run"]:
            print(f"[i] 演练：{r['src']} -> {r['dst']}  (槽位已存在={r['existed']})")
            print(f"    {_fmt(r['info'])}")
            return 0
        for b in r["backups"]:
            print(f"[b] 备份 {b}")
        print(f"[+] 导入 -> {r['dst']}  {r['bytes']}B  {r['sha256_16']}")
        print(f"    {_fmt(r['info'])}")
        return 0

    if args.cmd == "backups":
        rows = list_backups(args.slot)
        if not rows:
            print(f"[i] {args.slot.upper()} 没有找到任何备份")
            return 0
        for r in rows:
            d = r.get("info")
            tail = _fmt(d) if d else f"[X] {r.get('error', '无法解析')}"
            print(f"    {r['mtime']}  {r['name']:<52} {tail}")
        print(f"\n[i] 恢复命令： python save_tool.py import \"<上面的路径>\" --slot {args.slot.upper()}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
