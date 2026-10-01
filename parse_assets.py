"""解析 txtAssetDump 里导出的 Unity TextAsset, 生成完整 id 速查表

用法:
    python parse_assets.py
输出:
    ids_reference.md / ids_reference.json
"""
import csv
import json
import re
from collections import OrderedDict
from pathlib import Path

BASE = Path(__file__).parent
DUMP = BASE / "txtAssetDump"

M_SCRIPT_PREFIX = "1 string m_Script = "


# ---------------------------------------------------------------- 读取 dump

def unescape_cs(s: str) -> str:
    """还原 C# 字符串字面量里的转义序列"""
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            e = s[i + 1]
            if e == "n":
                out.append("\n"); i += 2; continue
            if e == "r":
                out.append("\r"); i += 2; continue
            if e == "t":
                out.append("\t"); i += 2; continue
            if e == '"':
                out.append('"'); i += 2; continue
            if e == "\\":
                out.append("\\"); i += 2; continue
            if e == "u" and i + 6 <= n:
                out.append(chr(int(s[i + 2:i + 6], 16))); i += 6; continue
        out.append(c)
        i += 1
    return "".join(out)


def load_assets() -> dict:
    """{资产名: 文本内容}；文件名形如 Crew-resources.assets-13.txt"""
    assets = {}
    for p in sorted(DUMP.glob("*.txt")):
        body = None
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith(M_SCRIPT_PREFIX):
                body = s[len(M_SCRIPT_PREFIX):]
                if body.startswith('"') and body.endswith('"'):
                    body = body[1:-1]
                body = unescape_cs(body)
                break
        if body is None:
            print(f"[!] {p.name}: 没找到 m_Script")
            continue
        name = p.name.split("-resources.assets-")[0]
        assets[name] = body
    return assets


def parse_csv(text: str):
    """返回 (header, rows)；rows 为 dict 列表（同名空列用 colN 占位）"""
    reader = csv.reader(text.splitlines())
    raw = [r for r in reader if any(x.strip() for x in r)]
    if not raw:
        return [], []
    header = [(h.strip() or f"col{i}") for i, h in enumerate(raw[0])]
    rows = []
    for r in raw[1:]:
        r = r + [""] * (len(header) - len(r))
        rows.append({header[i]: r[i].strip() for i in range(len(header))})
    return header, rows


# ---------------------------------------------------------------- 主流程

def main():
    assets = load_assets()

    print("=== dump 概览 ===")
    for name, text in assets.items():
        print(f"  {name:14s} {len(text):7d} 字符, {len(text.splitlines()):5d} 行")

    out = OrderedDict()

    # ---- 1) FateBaseIds：fateId 的 base 全集
    base_ids = [x.strip() for x in assets["FateBaseIds"].splitlines() if x.strip()]
    out["fate_base_ids"] = base_ids

    # ---- 2) FateEntIds：凶手 id 全集
    ent_ids = [x.strip() for x in assets["FateEntIds"].splitlines() if x.strip()]
    out["fate_ent_ids"] = ent_ids

    # ---- 3) Crew：名册 + 每题可接受答案
    crew_header, crew_rows = parse_csv(assets["Crew"])
    print("\n=== Crew 表 ===")
    print("  列头:", crew_header)
    print("  行数:", len(crew_rows))

    crews = []
    for r in crew_rows:
        fate_ids = [x.strip() for x in r.get("fate", "").split(",") if x.strip()]
        clue_ids = [x.strip() for x in r.get("clue", "").split() if x.strip()]
        hints = [x.strip() for x in r.get("hint", "").split(",") if x.strip()]
        tallies = [x.strip() for x in r.get("tally", "").split(",") if x.strip()]
        ins = r.get("insurance", "")
        crews.append(OrderedDict([
            ("id", r.get("id", "")),
            ("job", r.get("job", "")),
            ("gender_col", r.get("gender", "")),
            ("birthplace", r.get("birthplace", "")),
            ("category", r.get("category", "")),
            ("fateIds", fate_ids),
            ("clue", clue_ids),
            ("difficulty", r.get("difficulty", "")),
            ("hint", hints),
            ("sketch", r.get("sketch", "")),
            ("tally", tallies),
            ("pay", r.get("pay", "")),
            ("insuranceEstateKnown", "estate-unknown" not in ins),
            ("insuranceKilledIntentionally", "killed-accidental" not in ins),
            ("_raw_insurance", ins),
        ]))
    out["crew"] = crews

    # 诊断：gender 列到底有什么值
    print("  gender 列取值:", sorted({c["gender_col"] for c in crews}))
    print("  category 取值:", sorted({c["category"] for c in crews}))

    # ---- 4) Moments
    mo_header, mo_rows = parse_csv(assets["Moments"])
    print("\n=== Moments 表 ===")
    print("  列头:", mo_header)
    print("  行数:", len(mo_rows))
    moments = []
    for r in mo_rows:
        mid = r.get("id", "")
        moments.append(OrderedDict([
            ("id", mid),
            ("disaster", mid.split("-")[0] if mid else ""),
            ("corpse", r.get("corpse", "")),
            ("music", r.get("music", "")),
            ("die", [x.strip() for x in r.get("die", "").split(",") if x.strip()]),
            ("clear", r.get("clear", "")),
            ("skel", r.get("skel", "")),
            ("unlock", [x.strip() for x in r.get("unlock", "").split(",") if x.strip()]),
        ]))
    out["moments"] = moments

    # ---- 5) Presence：每个 moment 的在场名单
    presence = OrderedDict()
    for line in assets["Presence"].splitlines():
        toks = line.split()
        if toks:
            presence[toks[0]] = toks[1:]
    out["presence"] = presence

    # ---- 6) Version
    out["version"] = assets["Version"].strip()

    # ================================================================ 写 JSON
    (BASE / "ids_reference.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # ================================================================ 写 markdown
    L = []
    A = L.append
    A("# Obra Dinn id 速查表（从 txtAssetDump 自动生成）")
    A("")
    A(f"游戏版本：`{out['version']}`　生成脚本：`parse_assets.py`")
    A("")

    A("## 1. `fateId` 的 base 全集")
    A("")
    A(f"共 **{len(base_ids)}** 个（来自 TextAsset `FateBaseIds`）。")
    A("完整语法：`baseId` 或 `baseId:killerId`，冒号仅当 baseId 含 `-killer` 时出现。")
    A("")
    groups = OrderedDict()
    for b in base_ids:
        if b == "unknown":
            k = "特殊"
        elif b.endswith("-killer"):
            k = "他杀（`-killer`，可带 `:凶手`）"
        elif b.endswith("-beast"):
            k = "海怪致死（`-beast`）"
        elif b.startswith("suicide-"):
            k = "自杀（`suicide-`）"
        elif b.startswith("alive-"):
            k = "存活/去向（`alive-`）"
        elif b.startswith("crushed-"):
            k = "挤压（`crushed-`）"
        elif b.startswith("fell-"):
            k = "坠落（`fell-`）"
        elif b.startswith("expired-"):
            k = "自然/病死（`expired-`）"
        else:
            k = "事故/其他"
        groups.setdefault(k, []).append(b)
    A("| 类别 | 数量 | 取值 |")
    A("|---|---|---|")
    for k, v in groups.items():
        A(f"| {k} | {len(v)} | " + ", ".join(f"`{x}`" for x in v) + " |")
    A("")

    A("## 2. `killerId` 的合法取值（`FateEntIds`）")
    A("")
    crew_ids = {c["id"] for c in crews}
    cat_ids = [e for e in ent_ids if e.startswith("?")]
    special = [e for e in ent_ids if e in ("unknown", "enemy", "beast")]
    plain_crew = [e for e in ent_ids if not e.startswith("?") and e not in ("unknown", "enemy", "beast")]
    A(f"共 **{len(ent_ids)}** 个。")
    A("")
    A("| 类别 | 数量 | 说明 | 取值 |")
    A("|---|---|---|---|")
    A(f"| 特殊 | {len(special)} | `unknown` 无凶手；`beast` 海怪；`enemy` 敌人（非船员） | " +
      ", ".join(f"`{x}`" for x in special) + " |")
    A(f"| 职级（`?` 前缀） | {len(cat_ids)} | **只知职级、不知是谁** —— 与 `Crew.category` 列同源 | " +
      ", ".join(f"`{x}`" for x in cat_ids) + " |")
    A(f"| 具体船员 | {len(plain_crew)} | | " + ", ".join(f"`{x}`" for x in plain_crew) + " |")
    A("")
    A(f"> `FateEntIds` 里的具体船员 id 共 {len(plain_crew)} 个，与存档里 60 个 `face.id` 的关系："
      f"少 {len(crew_ids) - len(plain_crew)} 个（`face.id` 全集见 §3）。")
    A("")

    A("## 3. 船员名册（`Crew` 表，" + str(len(crews)) + " 人）")
    A("")
    A("| id | job | category | difficulty | pay | 可接受的命运答案 | clue 时刻 |")
    A("|---|---|---|---|---|---|---|")
    for c in crews:
        fates = "<br>".join(f"`{f}`" for f in c["fateIds"]) or "—"
        clue = " ".join(c["clue"]) or "—"
        A(f"| `{c['id']}` | {c['job']} | `{c['category']}` | {c['difficulty'] or '—'} | "
          f"{c['pay'] or '—'} | {fates} | {clue} |")
    A("")
    multi = [c for c in crews if len(c["fateIds"]) > 1]
    A(f"> **{len(multi)} 个**船员的命运答案**不唯一**（`IsCorrectFate` 用 `Contains` 判定），"
      f"最多的是 `{max(crews, key=lambda c: len(c['fateIds']))['id']}`"
      f"（{max(len(c['fateIds']) for c in crews)} 个答案）。")
    A("")

    A("## 4. `moment.id` 与章节（`Moments` 表，" + str(len(moments)) + " 个）")
    A("")
    A("| moment id | 章节 | 死者 | 尸体 | 音乐 |")
    A("|---|---|---|---|---|")
    for m in moments:
        die = ", ".join(f"`{d}`" for d in m["die"]) or "—"
        A(f"| `{m['id']}` | `{m['disaster']}` | {die} | {m['corpse'] or '—'} | {m['music'] or '—'} |")
    A("")
    A(f"> 另有硬编码的 `d100-fina-m00-final`，不进存档的 `moments` 列表（`isFinal`），"
      f"所以存档里是 {len(moments)} 条。")
    A("")

    A("## 5. `disaster.id` → 章节名")
    A("")
    chapters = OrderedDict()
    for m in moments:
        chapters.setdefault(m["disaster"], []).append(m["id"])
    A("| disaster id | moment 数 | 章节名（来自 `Lang` 键 `book_chapter_N_name`） |")
    A("|---|---|---|")
    names = ["Loose Cargo", "A Bitter Cold", "Murder", "The Calling", "Unholy Captives",
             "Soldiers of the Sea", "The Doom", "Bargain", "Escape", "The End"]
    for i, (d, ms) in enumerate(chapters.items()):
        nm = names[i] if i < len(names) else "?"
        A(f"| `{d}` | {len(ms)} | {nm} |")
    A("")

    A("## 6. `Presence` 表（每时刻在场名单）")
    A("")
    extra = [k for k in presence if k not in {m["id"] for m in moments}]
    A(f"共 {len(presence)} 个 moment 有记录。")
    A(f"其中 {len(extra)} 个 id **不在** `Moments` 表里（`Story.GetMoment()` 返回 `null` 会被跳过）"
      f"，属遗留条目：")
    A("")
    for e in extra:
        A(f"- `{e}`")
    A("")

    A("## 7. 端到端验证（`validate_ids.py`）")
    A("")
    A("用本表的答案集合复现游戏的判定逻辑（`savedata.css:622`）：")
    A("")
    A("```csharp")
    A("if (faceData.id == faceData.nameId && Manifest.it.IsCorrectFate(crewId, faceData.fateId))")
    A("    // 判定正确")
    A("```")
    A("")
    A("即 `markedCorrect == (nameId == id) && (fateId ∈ crew.fateIds)`。核对三份存档共 **180** 条 `face` 记录：")
    A("")
    A("| 指标 | 结果 |")
    A("|---|---|")
    A("| 判定吻合 | **180 / 180 = 100%** |")
    A("| `fateId` 落在 `FateBaseIds`/`FateEntIds` 词表外的记录 | **0** |")
    A("")
    A("⇒ `fateId` 语法、`killerId` 词表、每题答案集合、`markedCorrect`、`nameId` 五个语义**全部验证通过**。")
    A("")

    A("## 8. 未使用的遗留资产")
    A("")
    A("`txtAssetDump` 里这几张表**在全部 370 个源码文件中都没有被 `Resources.Load` 引用**：")
    A("")
    A("| 表 | 内容 | 判断 |")
    A("|---|---|---|")
    A("| `Action-Action` | 旧式死因 → 英文标签，如 `killed-gun` → `Shot (Gun)` | **遗留**：命名属旧一代方案 |")
    A("| `Verb-Table` | 旧式动词 → 宾语槽位，如 `killed-gun` → `killer` | 同上 |")
    A("| `Object-Table` | 旧式 `killer.?officer` / `killer.beast` 模板 | 同上 |")
    A("| `Subject-Table` | 旧式 `$num\\|$name\\|$job\\|$birthplace` 模板 | 同上 |")
    A("| `Readme` | 2017 Day of the Devs 试玩版说明 | 无关 |")
    A("")
    A("> 游戏中实际使用的是 `FateBaseIds`（`gunned-killer` 一代）配合 `Lang` 的 "
      "`fate_parts_*` / `fate_ent_*` 键。**不要基于上面这四张表建任何逻辑。**")
    A("")

    A("## 9. `bookPageId` 全集（来自 `css/Assembly-CSharp/BookSpec.cs`）")
    A("")
    A("**静态页**（`BookSpec` 构造函数逐个 `AddPage`）：")
    A("")
    A("```")
    A("title  preface  toc  maps  crew  glossary  last")
    A("air  desk  cover  folio-chart  folio-deck  folio-sketch")
    A("scrollable-manifest  screenplay  message")
    A("```")
    A("")
    A("**随章节/时刻动态生成**（`BookSpec.cs:132-144`）：")
    A("")
    A("| 形式 | 例子 | 触发条件 |")
    A("|---|---|---|")
    A("| `<disasterId>` | `d000` | 每章一个 Chapter 页 |")
    A("| `<moment.id>` | `d000-stow-m00-seag` | 每个 Death 页（`MomentLogic` 会写入它） |")
    A("| `<disasterId>-disappear` | `d030-disappear` | 该章有失踪者时 |")
    A("| `<disasterId>-disappear2` | `d060-disappear2` | 失踪者 > 4 人时（`numDisappearCrewPages == 2`） |")
    A("")

    A("## 10. 相关脚本")
    A("")
    A("| 脚本 | 作用 |")
    A("|---|---|")
    A("| `parse_assets.py` | 本文件的生成脚本 |")
    A("| `to_json.py` | 把 `txtAssetDump/` 转成整洁 JSON → `jsonDump/*.json` |")
    A("| `validate_ids.py` | 端到端验证（180 条 face） |")
    A("| `inspect_dump.py` | 预览 dump 里任意一张表 |")
    A("")
    A("> 机器可读的逐表数据见 `jsonDump/`（每张表一个 JSON，文件名已去掉 `-resources.assets-NN`）。")
    A("")

    (BASE / "ids_reference.md").write_text("\n".join(L), encoding="utf-8")
    print("\n[+] 已写出 ids_reference.md / ids_reference.json")


if __name__ == "__main__":
    main()
