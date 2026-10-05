"""定位 originalDLLWin 与我们的原版之间到底差了什么。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEW = (ROOT / "originalDLLWin" / "Assembly-CSharp.dll").read_bytes()
VAN = (ROOT / "hardcore" / "_backup" / "Assembly-CSharp.dll.orig").read_bytes()

L = min(len(NEW), len(VAN))

print("=== 整体偏移画像（对每个候选位移，看有多少探针窗口完全命中）===")
probes = list(range(0x400, L - 512, 0x40))
for d in (-688, -512, -176, 0, 176, 512, 688):
    hits = sum(1 for i in probes if NEW[i + d:i + d + 64] == VAN[i:i + 64])
    print("  NEW[i%+5d] == VAN[i]  命中 %5d / %d" % (d, hits, len(probes)))

print()
print("=== 逐段求偏移转变点 ===")


def run(n, v, limit=1 << 20):
    k = 0
    while k < limit and n + k < len(NEW) and v + k < len(VAN) and NEW[n + k] == VAN[v + k]:
        k += 1
    return k


seg = []
n = v = 0x400
while n < L - 1024:
    k = run(n, v)
    n += k
    v += k
    if n >= L - 1024:
        seg.append((n, v, 0))
        break
    # 找新的对齐位移
    found = None
    for d in list(range(1, 2049)) + list(range(-1, -2049, -1)):
        if 0 <= n + d and n + d + 128 <= len(NEW) and NEW[n + d:n + d + 128] == VAN[v:v + 128]:
            found = d
            break
        if 0 <= v + d and v + d + 128 <= len(VAN) and NEW[n:n + 128] == VAN[v + d:v + d + 128]:
            found = -d
            break
    if found is None:
        print("  在 NEW 0x%06X / VAN 0x%06X 处无法重新对齐，停止" % (n, v))
        break
    seg.append((n, v, found))
    n += found if found > 0 else 0
    v += -found if found < 0 else 0

prev = None
for n, v, d in seg:
    if d != prev:
        print("  NEW 0x%06X  VAN 0x%06X   位移变为 %+d" % (n, v, d))
        prev = d

print()
print("=== 差异区段内容（第一处）===")
n = v = 0x400
for _ in range(6):
    k = run(n, v)
    if n + k >= L - 1024:
        break
    print("  相同到 NEW 0x%06X（%d B）" % (n + k, k))
    print("     NEW : %s" % NEW[n + k:n + k + 80].hex(" "))
    print("     VAN : %s" % VAN[v + k:v + k + 80].hex(" "))
    # 打印可读串
    import re
    for tag, b in (("NEW", NEW[n + k - 40:n + k + 200]), ("VAN", VAN[v + k - 40:v + k + 200])):
        ss = [m.group(0).decode("latin-1") for m in re.finditer(rb"[\x20-\x7e]{6,}", b)]
        if ss:
            print("     %s 可读串: %s" % (tag, ss[:4]))
    nv = None
    for d in list(range(1, 2049)) + list(range(-1, -2049, -1)):
        if NEW[n + k + d:n + k + d + 128] == VAN[v + k:v + k + 128]:
            nv = d
            break
    if nv is None:
        print("     重新对齐失败")
        break
    n, v = n + k + nv, v + k
