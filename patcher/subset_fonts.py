#!/usr/bin/env python3
"""把**存档工具那两款字体**按补丁器界面实际会用到的字符集裁剪一份。

字体沿用存档工具的（风格一致）：
    拉丁/英文 : font_src/IMFeENrm28P.ttf                （IM Fell English Roman）
    中文/符号 : font_src/SOURCEHANSERIFSC-SEMIBOLD.OTF   （思源宋体 SemiBold，**完整**那份）

**基准原件在仓库根的 `font_src/`，本脚本只读不改** —— 输出写到自己目录下的
`assets/fonts/`，不碰存档工具的 `gui/fonts/`。思源宋体一律拿完整那份当底：
`…-subset.otf` 是裁过的，用它当底会把本来就没有的字静默丢掉。

字符集口径
----------
1. `_font_charset.txt` —— 存档工具已经确认过的那套字符（并入，保证不倒退）
2. 补丁器自己的 `.py` 源码里的字符串字面量（界面文案、档位名、日志文案）
3. 基础区间：ASCII、Latin-1 补充、常用标点、CJK 标点、全角形式

用法：
    python -m patcher.subset_fonts [--check]
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

PATCHER_DIR = Path(__file__).resolve().parent
REPO = PATCHER_DIR.parent

SRC_DIR = REPO / "font_src"
OUT_DIR = PATCHER_DIR / "assets" / "fonts"
SAVE_TOOL_CHARSET = REPO / "_font_charset.txt"

# 输出文件名 -> 子集化的**基准原件**（在 font_src/ 里）。
# 思源宋体一律用完整那份，别用 `…-subset.otf` 当底。
FONTS = {
    "IMFeENrm28P.ttf": "IMFeENrm28P.ttf",
    "SourceHanSerifSC-SemiBold-subset.otf": "SOURCEHANSERIFSC-SEMIBOLD.OTF",
}

EXTRA_RANGES = [
    (0x0020, 0x007E),   # ASCII 可打印
    (0x00A0, 0x00FF),   # Latin-1 补充（· × 等）
    (0x2000, 0x206F),   # 常用标点（— – … “ ” ‘ ’ 等）
    (0x2190, 0x21FF),   # 箭头
    (0x2500, 0x257F),   # 制表符
    (0x3000, 0x303F),   # CJK 标点（、。「」等）
    (0xFF00, 0xFFEF),   # 全角形式
]


def ui_sources() -> list[Path]:
    """真正能把文字送到界面上的模块（子集化用，宽口径）。"""
    files = sorted(PATCHER_DIR.glob("*.py"))
    launcher = REPO / "run_patch_gui.py"
    if launcher.is_file():
        files.append(launcher)
    return files


#: 能把文字送进浏览器的模块。字体口径就按这几个算。
#:
#: 为什么不把 patcher/*.py 全收进来：build_gui / subset_fonts / selftest /
#: gui_smoke 这些**只在终端输出**，而终端用的是它自己的字体，跟我们这两款无关。
#: 把它们算进来，每改一次控制台文案就要重新子集化一次（实测被「依赖」「排除」
#: 这类字坑了两回），全是假缺口。这里的 langpatch_tool 要算 —— 它的提示会进
#: 界面的日志区。
UI_MODULES = ("core", "server", "web", "langpatch_tool")


def verify_sources() -> list[Path]:
    """验证用（窄口径）：能上浏览器的模块 + 存档工具的界面模块。

    存档工具那几个也要算：两款字体是两边**共用**的，给它做子集时不能把
    存档工具界面要用的字裁掉。
    """
    files = [PATCHER_DIR / (m + ".py") for m in UI_MODULES]
    files = [p for p in files if p.is_file()]
    gui = REPO / "gui"
    if gui.is_dir():
        files += sorted(gui.glob("*.py"))
    for name in ("save_tool.py", "make_envelope_save.py"):
        p = REPO / name
        if p.is_file():
            files.append(p)
    return files


def verify_charset() -> set[str]:
    """只统计**真会显示**的字符。

    与子集化的口径区别：这里**不含** EXTRA_RANGES —— 那批基础区间（比如
    2000-206F 里的罕见标点）本来就不在字体里，把它们算进验证只会恒定报缺口，
    毫无信息量。它们只在子集化时当余量用。
    """
    chars, _ = source_strings(verify_sources())
    pj = REPO / "gui" / "presets" / "presets.json"
    if pj.is_file():
        chars.update(pj.read_text(encoding="utf-8", errors="replace"))
    for d in (REPO, pj.parent, REPO / "saves"):
        if d.is_dir():
            for f in d.glob("*.txt"):
                chars.update(f.name)
    return {c for c in chars if c.isprintable() and c not in "\r\n\t"}


def _docstring_values(tree: ast.AST) -> set[int]:
    """找出所有 docstring 字面量（module / class / function 的第一条语句）。

    它们不可能上屏，但里面常出现 ⇒ ∪ ≠ 这类符号。不排掉的话，字体覆盖验证会
    恒定报一堆假缺口，真问题反而被淹掉。
    """
    out: set[int] = set()
    kinds = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, kinds):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.add(id(first.value))
    return out


def source_strings(files: list[Path]) -> tuple[set[str], int]:
    """抽 `.py` 里的字符串字面量（用 ast，避开注释与变量名；docstring 不算）。"""
    chars: set[str] = set()
    n = 0
    for p in files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        n += 1
        skip = _docstring_values(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in skip):
                chars.update(node.value)
    return chars, n


def charset() -> tuple[set[str], dict]:
    """要覆盖的全部字符，以及来源统计。

    ⚠️ 这里**必须**用 `verify_sources()` —— 和 `verify_font_coverage` 同一份口径。
    两款字体是和存档工具共用的，如果子集化口径比验证口径窄，就会把存档工具
    界面要用的字裁掉（实测漏过：叫 将 止 滚 轮）。
    """
    chars: set[str] = set()
    stats: dict = {}

    if SAVE_TOOL_CHARSET.is_file():
        raw = SAVE_TOOL_CHARSET.read_text(encoding="utf-8", errors="replace")
        chars.update(raw)
        stats["存档工具字符集"] = len(set(raw))

    src, n = source_strings(verify_sources())
    chars |= src
    stats["界面源码模块"] = n

    base: set[str] = set()
    for lo, hi in EXTRA_RANGES:
        for cp in range(lo, hi + 1):
            try:
                base.add(chr(cp))
            except ValueError:
                pass
    chars |= base
    stats["基础区间(余量)"] = len(base)

    chars = {c for c in chars if c.isprintable() and c not in "\r\n\t"}
    stats["合计"] = len(chars)
    return chars, stats


def main(argv: list[str] | None = None) -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="裁剪补丁器界面字体")
    ap.add_argument("--check", action="store_true", help="只报告，不写文件")
    a = ap.parse_args(argv)

    chars, stats = charset()
    print("字符集来源：")
    for k, v in stats.items():
        print("   %-14s %s" % (k, v))
    print()

    missing_src = [b for b in FONTS.values() if not (SRC_DIR / b).is_file()]
    if missing_src:
        print("[X] font_src/ 里缺基准原件：%s" % missing_src)
        print("    基准一律用完整原件，别拿裁过的产物覆盖。")
        return 2

    from fontTools import subset                      # noqa: PLC0415

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total_before = total_after = 0
    for out_name, base_name in FONTS.items():
        src = SRC_DIR / base_name
        dst = OUT_DIR / out_name
        before = src.stat().st_size
        total_before += before
        if not a.check:
            opts = subset.Options()
            opts.layout_features = ["*"]
            opts.name_IDs = ["*"]
            opts.notdef_outline = True
            opts.recalc_bounds = True
            opts.drop_tables = ["DSIG"]
            font = subset.load_font(str(src), opts)
            subsetter = subset.Subsetter(options=opts)
            subsetter.populate(text="".join(sorted(chars)))
            subsetter.subset(font)
            subset.save_font(font, str(dst), opts)
            font.close()
        after = dst.stat().st_size if dst.is_file() else 0
        total_after += after
        print("  %-40s %7.1f KB -> %7.1f KB"
              % (out_name, before / 1024, after / 1024))

    print()
    if a.check:
        print("（--check：没有写文件）")
    else:
        print("合计 %.1f KB -> %.1f KB    输出目录 %s"
              % (total_before / 1024, total_after / 1024, OUT_DIR))
    return 0


if __name__ == "__main__":
    sys.exit(main())
