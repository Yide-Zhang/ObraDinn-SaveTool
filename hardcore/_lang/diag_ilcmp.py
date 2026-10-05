"""比对两份 dump 的 IL 指令流（忽略文件绝对偏移）。"""
import re
import sys
from pathlib import Path

D = Path(__file__).resolve().parent / "_newbuild"

LINE = re.compile(r"\s*(IL_[0-9A-F]{4})\s+@0x[0-9A-F]+\s+(\S+)\s*(.*)$")


def parse(p):
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        m = LINE.match(ln)
        if m:
            out.append((m.group(1), m.group(2), m.group(3).strip()))
    return out


for base in ("Book", "ug"):
    a = parse(D / ("ctl.%s.txt" % base))
    b = parse(D / ("new.%s.txt" % base))
    print("=" * 74)
    print("%s : ctl %d 条  /  new %d 条" % (base, len(a), len(b)))
    if len(a) != len(b):
        print("  [X] 指令条数不同")
    diff = [(i, a[i], b[i]) for i in range(min(len(a), len(b))) if a[i] != b[i]]
    print("  逐条比对：不同 %d 条" % len(diff))
    if not diff:
        print("  [OK] IL wanquan yizhi (chu wenjian pianyi)")
    for i, x, y in diff[:10]:
        print("    #%d" % i)
        print("      ctl: %s" % (x,))
        print("      new: %s" % (y,))
    if len(diff) > 10:
        print("    ... 还有 %d 条" % (len(diff) - 10))

print()
print("=== xin build bu ding hou de xianchang (Book) ===")
b = parse(D / "new.Book.txt")
for i, (il, op, arg) in enumerate(b):
    if op in ("rem", "ldc.i4.3") and arg == "" and i + 1 < len(b) and b[i + 1][1] == "ldelem.ref":
        for k in range(max(0, i - 3), min(len(b), i + 3)):
            print("   ", b[k])
        print("    ---")
    if op in ("br", "bne.un"):
        tgt = arg
        for k, t in enumerate(b):
            if t[0] == tgt and k + 1 < len(b) and b[k + 1][1] == "newarr":
                print("   B1:", b[k - 2], "\n       ", b[k - 1], "\n       ", b[k], "\n       ", b[k + 1])
                break
print("=== C chu (1.2f / 2.4f de chufa) ===")
for i, (il, op, arg) in enumerate(b):
    if op == "div" and i >= 6:
        for k in range(i - 7, i + 2):
            print("   ", b[k])
        print("    ---")
