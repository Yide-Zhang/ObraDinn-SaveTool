"""originalDLLWin 的 DLL vs 我们的原版：逐位点对齐窗口比对 + 插入位置定位。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from patcher import core                                    # noqa: E402

NEW = (ROOT / "originalDLLWin" / "Assembly-CSharp.dll").read_bytes()
VAN = (ROOT / "hardcore" / "_backup" / "Assembly-CSharp.dll.orig").read_bytes()


def prefix(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def suffix(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[len(a) - 1 - i] == b[len(b) - 1 - i]:
        i += 1
    return i


p = prefix(NEW, VAN)
s = suffix(NEW, VAN)
print("大小   新 %d  原版 %d   差 %+d" % (len(NEW), len(VAN), len(NEW) - len(VAN)))
print("公共前缀 %d B (0x%X)" % (p, p))
print("公共后缀 %d B" % s)
print("⇒ 中间不同的一段：新 %d B (0x%X..0x%X)  原版 %d B (0x%X..0x%X)"
      % (len(NEW) - p - s, p, len(NEW) - s, len(VAN) - p - s, p, len(VAN) - s))
print("   （差 %+d）" % ((len(NEW) - p - s) - (len(VAN) - p - s)))

print()
print("差异段之前，新 DLL 多出来的 %d 字节内容：" % (len(NEW) - p - s - (len(VAN) - p - s)))
mid_new = NEW[p:len(NEW) - s]
mid_van = VAN[p:len(VAN) - s]
print("  新 : %d B, 前 96 字节: %s" % (len(mid_new), mid_new[:96].hex(" ")))
print("  原版: %d B, 前 96 字节: %s" % (len(mid_van), mid_van[:96].hex(" ")))

print()
print("=== 四个位点的相对窗口比对（各自用自己的偏移） ===")


def site_anchor(buf):
    a = buf.find(core.CONST_ANCHOR)
    return {"A": a,
            "C": (core.SEAL_VANILLA_RE.search(buf).start()
                  if core.SEAL_VANILLA_RE.search(buf) else -1)}


na, va = site_anchor(NEW), site_anchor(VAN)
print("  A  新@0x%06X  原版@0x%06X  Δ=%+d" % (na["A"], va["A"], na["A"] - va["A"]))
print("  C  新@0x%06X  原版@0x%06X  Δ=%+d" % (na["C"], va["C"], na["C"] - va["C"]))


def b2_off(buf):
    i = buf.find(b"\x02\x08\x07\x9a")
    return i


def b1_off(buf):
    import re
    for m in re.finditer(rb"\x18.{0,14}?[\x40\x38]", buf, re.S):
        j = m.end() - 1
        off = j + 5
        tgt = off + int.from_bytes(buf[j + 1:j + 5], "little", signed=True)
        if 0 <= tgt < len(buf) - 1 and buf[tgt:tgt + 2] == b"\x19\x8d":
            return j
    return -1


nb2, vb2 = b2_off(NEW), b2_off(VAN)
nb1, vb1 = b1_off(NEW), b1_off(VAN)
print("  B1 新@0x%06X  原版@0x%06X  Δ=%+d" % (nb1, vb1, nb1 - vb1))
print("  B2 新@0x%06X  原版@0x%06X  Δ=%+d" % (nb2, vb2, nb2 - vb2))

W = 48
for name, off_n, off_v in (("A", na["A"], va["A"]),
                           ("B1", nb1, vb1),
                           ("B2", nb2, vb2),
                           ("C", na["C"], va["C"])):
    if off_n < 0 or off_v < 0:
        print("  %-3s 有站点没找到，跳过" % name)
        continue
    wn = NEW[off_n - W:off_n + W]
    wv = VAN[off_v - W:off_v + W]
    same = wn == wv
    print("  %-3s ±%d B 窗口：%s" % (name, W, "逐字节相同 ✓" if same else "不同 ✗"))
    if not same:
        d = [i for i in range(len(wn)) if wn[i] != wv[i]]
        print("       不同位置(相对窗口) %s" % d[:24])

print()
print("=== 方法体级比对：把 A 锚点前 0x400 字节整体比 ===")
N = 0x400
print("  相对锚点 -0x200..+0x200 相同? %s"
      % (NEW[na["A"] - 0x200:na["A"] + 0x200] == VAN[va["A"] - 0x200:va["A"] + 0x200]))
print("  B1 相对 -0x300..+0x300 相同? %s"
      % (NEW[nb1 - 0x300:nb1 + 0x300] == VAN[vb1 - 0x300:vb1 + 0x300]))
print("  C  相对 -0x200..+0x200 相同? %s"
      % (NEW[na["C"] - 0x200:na["C"] + 0x200] == VAN[va["C"] - 0x200:va["C"] + 0x200]))
