#!/usr/bin/env python3
"""从语言包反推「当前文案是哪个档位」—— 对应 DLL 侧的 check_level.py。

原理：4 个键的值在每个档位下都是确定的（由 numbers.py 与原始文案算出来），
逐语言比对即可。因为切换档位时语言包可能已经是改过的，所以这里
**以 numbers.py 算出的 7 种状态为基准**逐个匹配，而不是「有没有改过」。

判定用 4 个键联合指纹（welldone_3_first/_more + help_faceclear_fates0/_1），
任何一项对不上就报「认不出」，绝不猜。

用法：
    python hardcore/_lang/check_lang.py                          # 默认查游戏目录
    python hardcore/_lang/check_lang.py <目录>                    # 查某个目录里的 lang-*
    python hardcore/_lang/check_lang.py <目录> --dll <dll 路径>    # 顺便和 DLL 档位对账
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numbers as NUM  # noqa: E402

GAME_DIR = Path(r"F:\AceAttorneySeries\gameFiles\steamapps\common\ObraDinn"
                r"\ObraDinn_Data\StreamingAssets")
DEFAULT_DLL = Path(r"F:\AceAttorneySeries\gameFiles\steamapps\common\ObraDinn"
                   r"\ObraDinn_Data\Managed\Assembly-CSharp.dll")
EXPORT = Path("hardcore/_lang/export")
EXE = Path("hardcore/langtool/bin/Release/net8.0/langtool.exe")

KEYS = tuple(NUM.KEY_SHAPE)
LEVEL_NAMES = {3: "简单（原版）", 4: "容易", 6: "中等", 9: "偏高",
               14: "较难", 29: "困难", 58: "硬核"}


def unesc(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] in "ntr\\":
            out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}[s[i + 1]])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def langtool_keys(bundle: Path) -> dict[str, str] | None:
    cmd = ([str(EXE)] if EXE.exists()
           else ["dotnet", "run", "--project", "hardcore/langtool", "-c", "Release",
                 "--no-build", "--"])
    r = subprocess.run(cmd + ["keys", str(bundle), *KEYS],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("  [X] %s: %s" % (bundle.name, (r.stderr or "").strip()[:200]))
        return None
    out: dict[str, str] = {}
    for line in (r.stdout or "").splitlines():
        k, _, v = line.partition("\t")
        out[k] = unesc(v)
    return out


def load_originals() -> dict[str, dict[str, str]]:
    data: dict[str, dict[str, str]] = {}
    for p in sorted(EXPORT.glob("*.tsv")):
        d: dict[str, str] = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("\t")
            d[k] = unesc(v)
        data[p.stem] = d
    return data


def build_expected(orig: dict[str, dict[str, str]]) -> dict[int, dict[str, dict[str, str]]]:
    levels = [3, *NUM.LEVELS]
    exp: dict[int, dict[str, dict[str, str]]] = {}
    for lv in levels:
        exp[lv] = {lg: {k: NUM.make_value(lg, k, lv, orig[lg][k]) for k in KEYS}
                   for lg in orig}
    return exp


def main() -> int:
    args = [a for a in sys.argv[1:]]
    dll = None
    if "--dll" in args:
        i = args.index("--dll")
        dll = Path(args[i + 1]) if i + 1 < len(args) else DEFAULT_DLL
        del args[i:i + 2]
    target = Path(args[0]) if args else GAME_DIR

    if not target.exists():
        print("[X] 找不到 " + str(target))
        return 2

    print("=" * 78)
    print("目录: " + str(target))
    print("=" * 78)

    exp = build_expected(load_originals())

    per_lang: dict[str, int | None] = {}
    ok = True
    for lang in sorted(exp[3]):
        f = target / ("lang-" + lang)
        if not f.exists():
            print("  %-6s [X] 缺少 %s" % (lang, f.name))
            ok = False
            continue
        got = langtool_keys(f)
        if got is None:
            ok = False
            continue
        hits = [lv for lv in sorted(exp) if all(exp[lv][lang][k] == got.get(k) for k in KEYS)]
        if len(hits) == 1:
            per_lang[lang] = hits[0]
            print("  %-6s -> %s（%d 人批）" % (lang, LEVEL_NAMES[hits[0]], hits[0]))
        else:
            per_lang[lang] = None
            ok = False
            # 指出哪几个键对不上，便于定位
            diff = [k for k in KEYS
                    if not any(exp[lv][lang][k] == got.get(k) for lv in exp)]
            print("  %-6s [X] 认不出（命中 %d 种状态；以下键不符合任何档位: %s）"
                  % (lang, len(hits), ", ".join(diff) or "无"))

    levels = {v for v in per_lang.values() if v is not None}
    lang_lv = next(iter(levels)) if len(levels) == 1 else None
    print()
    if lang_lv is not None and all(v is not None for v in per_lang.values()):
        print("=> 14 种语言一致：%s（%d 人批）" % (LEVEL_NAMES[lang_lv], lang_lv))
    elif not levels:
        print("=> 认不出当前档位")
    else:
        print("=> [X] 各语言不一致：%s" % ", ".join(
            "%s=%s" % (lg, LEVEL_NAMES[v] if v else "?") for lg, v in sorted(per_lang.items())))
        ok = False

    if dll is not None:
        r = subprocess.run([sys.executable, "hardcore/check_level.py", str(dll), "--json"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            dll_num = json.loads(r.stdout)["num"]
        except Exception:                          # noqa: BLE001
            print("   [!] 读不到 DLL 档位，跳过对账")
            dll_num = None
        if dll_num is not None and lang_lv is not None:
            if dll_num == lang_lv:
                print("   DLL 与语言包一致（%d）" % dll_num)
            else:
                print("   [X] DLL 是 %d，语言包是 %d —— 不一致，需要重新打补丁"
                      % (dll_num, lang_lv))
                ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
