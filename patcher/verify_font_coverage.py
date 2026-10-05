#!/usr/bin/env python3
"""验证裁剪后的字体确实覆盖了补丁器界面会显示的所有字符。

判定口径：对每个字符看它落到哪款字体
    SourceHanSerif 的 cmap 里有 -> 中文/符号走它
    否则 IMFe 的 cmap 里有     -> 英文/拉丁走它
    两个都没有                  -> 回落到系统字体，需要处理

额外还查一遍**存档工具那套字符集**：补丁器共用同一批字体文件，
不能因为给补丁器做子集把存档工具的界面字符裁掉。

用法：
    python -m patcher.verify_font_coverage
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from patcher.subset_fonts import FONTS, verify_charset   # noqa: E402

PATCHER_DIR = Path(__file__).resolve().parent
FONT_DIR = PATCHER_DIR / "assets" / "fonts"


def css_font_issues() -> list[str]:
    """检查界面 CSS 里有没有用规定字体之外的字体。

    光验字形覆盖不够：踩过一次 —— `.row .v` / `td .num` 写了
    Consolas/monospace，于是游戏位置、槽位号、登记计数都走了另一套字形。
    这里把每条 font / font-family 声明都挑出来，只允许 var(--font) 或 inherit。
    """
    from patcher.web import INDEX_HTML                    # noqa: PLC0415
    if "<style>" not in INDEX_HTML or "</style>" not in INDEX_HTML:
        return ["INDEX_HTML 里找不到 <style> 块"]
    style = INDEX_HTML.split("<style>", 1)[1].split("</style>", 1)[0]
    # @font-face 里必须写字体名，那是定义处，不算违规
    body = re.sub(r"@font-face\s*\{[^}]*\}", "", style)

    issues: list[str] = []
    # `(?<![-\w])` 是为了避开 `--font:...` 这个自定义属性的**定义处** ——
    # 那里本来就要写字体名，不该算违规。
    for rule in re.finditer(r"([^{}]+)\{([^}]*)\}", body):
        selector = rule.group(1).strip().splitlines()[-1].strip()
        for decl in re.finditer(r"(?<![-\w])font(?:-family)?\s*:\s*([^;]+)",
                                rule.group(2)):
            val = decl.group(1).strip()
            if "var(--font)" in val or val.split()[0] == "inherit":
                continue
            issues.append("%s  { font: %s }" % (selector, val))
    return issues


def cmap_of(p: Path) -> set[int]:
    from fontTools.ttLib import TTFont              # noqa: PLC0415
    with TTFont(p, lazy=True) as f:
        return set(f.getBestCmap())


def main(argv: list[str] | None = None) -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="验证字体覆盖")
    ap.add_argument("--dir", default=None,
                    help="字体目录；默认 assets/fonts，"
                         "子集化之前可以指定 font_src 先验原件")
    ap.add_argument("--chars", default=None, help="额外逐字检查这几个字符")
    a = ap.parse_args(argv)
    d = Path(a.dir) if a.dir else FONT_DIR
    # FONTS 是 {输出文件名: 基准原件} 的 dict，别再按下标取（以前写 FONTS[0]，
    # dict 化之后直接 KeyError）。按名字挑，跟顺序无关。
    keys = list(FONTS)
    lat_p = d / next(n for n in keys if "imfe" in n.lower())
    cjk_p = d / next(n for n in keys if "sourcehan" in n.lower())

    print("[i] 字体目录: %s" % d)
    for p in (lat_p, cjk_p):
        if not p.is_file():
            print("[X] 找不到字体 %s" % p)
            return 2

    if a.chars:
        lat0, cjk0 = cmap_of(lat_p), cmap_of(cjk_p)
        print("[i] 逐字检查：")
        for c in a.chars:
            where = ("SourceHanSerif" if ord(c) in cjk0
                     else "IMFe" if ord(c) in lat0 else "**两个都没有**")
            print("    %r U+%04X  %s" % (c, ord(c), where))
        return 0

    lat, cjk = cmap_of(lat_p), cmap_of(cjk_p)
    print("[i] %s: %d 个码位" % (lat_p.name, len(lat)))
    print("[i] %s: %d 个码位" % (cjk_p.name, len(cjk)))

    chars = verify_charset()
    missing = sorted(c for c in chars if ord(c) not in lat and ord(c) not in cjk)
    in_cjk = sum(1 for c in chars if ord(c) in cjk)
    in_lat = sum(1 for c in chars if ord(c) not in cjk and ord(c) in lat)
    print()
    print("[i] 会上屏的字符: %d 个" % len(chars))
    print("    SourceHanSerif 命中 : %d" % in_cjk)
    print("    IMFe 命中           : %d" % in_lat)
    print("    无字形（会回落）    : %d" % len(missing))
    ok = not missing
    for c in missing[:60]:
        print("    U+%04X  %r" % (ord(c), c))

    # 英文字母优先走 IMFe（字体栈第一位），ASCII 必须全在 IMFe 里
    ascii_missing = [c for c in (chr(i) for i in range(0x20, 0x7F))
                     if ord(c) not in lat]
    if ascii_missing:
        ok = False
        print()
        print("[-] ASCII 里有 %d 个字符 IMFe 不含，会被后面的中文字体接管，"
              "英文观感会断：" % len(ascii_missing))
        print("    %r" % "".join(ascii_missing))

    # CSS 里不允许出现规定字体之外的字体
    css_issues = css_font_issues()
    print()
    print("[i] CSS 字体声明检查：%s"
          % ("全部使用 var(--font) [OK]" if not css_issues
             else "发现 %d 处用了别的字体" % len(css_issues)))
    for it in css_issues:
        print("    %s" % it)
        ok = False

    print()
    print("结论：%s" % ("全部有字形 [OK]" if ok else "有问题，见上"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
