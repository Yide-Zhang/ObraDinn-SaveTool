#!/usr/bin/env python3
"""按 numbers.py 生成「6 档 × 14 语言」的文案替换，并调用 langtool 重打包。

流程（每个档位、每种语言）：
    1. 从 hardcore/_lang/export/<code>.tsv 读出**原始**文案（那是真原文）
    2. 对 4 个键算出新值（numbers.make_value）
    3. 写 edits-<code>.txt（key<TAB>新值，转义格式与 langtool 一致）
    4. 调 langtool set，从**原始包**重打包（不叠加，所以可反复跑）

产物：
    hardcore/_lang/out/lv<N>/lang-<code>            补丁后的语言包
    hardcore/_lang/out/lv<N>/edits-<code>.txt       本次替换清单（备查/可复现）
    hardcore/_dump/lang_review.txt                  全语言 × 全档位对照表（人工校对用）

用法：
    python hardcore/_lang/make_lang_packs.py [--dry] [--levels 4,6]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numbers as NUM  # noqa: E402

ROOT = Path("hardcore/_lang")
SRC = ROOT                      # 原始包（未改过的）
EXPORT = ROOT / "export"
OUT = ROOT / "out"
REVIEW = Path("hardcore/_dump/lang_review.txt")
KEYS = tuple(NUM.KEY_SHAPE)


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


def esc(s: str) -> str:
    return (s.replace("\\", "\\\\").replace("\r", "\\r")
             .replace("\n", "\\n").replace("\t", "\\t"))


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


def main() -> int:
    dry = "--dry" in sys.argv
    levels = list(NUM.LEVELS)
    for i, a in enumerate(sys.argv):
        if a == "--levels" and i + 1 < len(sys.argv):
            levels = [int(x) for x in sys.argv[i + 1].split(",")]

    orig = load_originals()
    langs = sorted(orig)
    print("原始语言包 %d 个：%s" % (len(langs), ", ".join(langs)))

    review: list[str] = []
    failed: list[str] = []

    for level in levels:
        outdir = OUT / ("lv%d" % level)
        outdir.mkdir(parents=True, exist_ok=True)
        print()
        print("=" * 84)
        print("档位 %d 人批  ->  %s" % (level, outdir))
        print("=" * 84)

        for lang in langs:
            edits: list[tuple[str, str, str]] = []      # (key, 旧, 新)
            for key in KEYS:
                old = orig[lang][key]
                new = NUM.make_value(lang, key, level, old)
                edits.append((key, old, new))

            edit_file = outdir / ("edits-%s.txt" % lang)
            edit_file.write_text(
                "# 档位 %d 人批  语言 %s\n" % (level, lang)
                + "".join("%s\t%s\n" % (k, esc(n)) for k, _o, n in edits),
                encoding="utf-8")

            dst = outdir / ("lang-%s" % lang)
            if dry:
                print("  [dry] %-6s -> %s" % (lang, dst))
            else:
                r = subprocess.run(
                    ["dotnet", "run", "--project", "hardcore/langtool", "-c", "Release",
                     "--no-build", "--", "set", str(SRC / ("lang-" + lang)), str(dst),
                     str(edit_file), "--pack=lzma"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
                ok = r.returncode == 0 and "自验证通过" in (r.stdout or "")
                size = dst.stat().st_size if dst.exists() else -1
                print("  [%s] %-6s %8d bytes" % ("OK" if ok else "XX", lang, size))
                if not ok:
                    failed.append("lv%d/%s" % (level, lang))
                    print((r.stdout or "")[-1500:])
                    print((r.stderr or "")[-800:])

            for key, old, new in edits:
                review.append("[%s] %d  %s" % (lang, level, key))
                review.append("    旧: " + esc(old))
                review.append("    新: " + esc(new))

    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.write_text("\n".join(review) + "\n", encoding="utf-8")
    print()
    print("对照表 -> %s" % REVIEW)
    if failed:
        print("[X] 失败 %d 项：%s" % (len(failed), ", ".join(failed)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
