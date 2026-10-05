"""检查 mac 那份 DLL 的四个补丁站点是否可定位、是否原版形态。"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from patcher import core                                    # noqa: E402

TARGETS = [
    ("mac (GOG)",            ROOT / "mac_probe" / "Assembly-CSharp-mac.dll"),
    ("win 官方原版",          ROOT / "hardcore" / "_backup" / "Assembly-CSharp.dll.orig"),
    ("win 另一份 build",      ROOT / "originalDLLWin" / "Assembly-CSharp.dll"),
]

for tag, p in TARGETS:
    if not p.is_file():
        print("=== %s  （不存在）" % tag)
        continue
    buf = p.read_bytes()
    info = core.probe_dll(p)
    print("=" * 74)
    print("%s   %s" % (tag, p.name))
    print("  %d B  sha256=%s" % (len(buf), hashlib.sha256(buf).hexdigest()[:24]))
    print("  kind=%-8s const=%-5s seal_vanilla=%-5s seal_patched=%-5s"
          % (info.get("kind"), info.get("const"),
             info.get("seal_vanilla"), info.get("seal_patched")))
    print("  b1_patched=%-5s b2_patched=%-5s  可就地改=%s %s"
          % (info.get("b1_patched"), info.get("b2_patched"),
             info.get("patchable"), info.get("patch_note") or ""))

    a = buf.find(core.CONST_ANCHOR)
    b2v = buf.find(core.B2_VANILLA)
    b2p = buf.find(core.B2_PATCHED)
    sv = core.SEAL_VANILLA_RE.search(buf)
    sp = core.SEAL_PATCHED_RE.search(buf)
    b1op = core._b1_branch_op(buf)                           # noqa: SLF001
    print("  A 锚点@%s  B1 分支=%s  B2 原版@%s/补丁@%s  C 原版@%s/补丁@%s"
          % ("0x%06X" % a if a >= 0 else "无",
             ("0x%02X" % b1op) if b1op is not None else "无",
             ("0x%06X" % b2v) if b2v >= 0 else "-",
             ("0x%06X" % b2p) if b2p >= 0 else "-",
             ("0x%06X" % sv.start()) if sv else "-",
             ("0x%06X" % sp.start()) if sp else "-"))

print()
print("=== 与 Windows 原版的差异（逐字节）===")
mac = (ROOT / "mac_probe" / "Assembly-CSharp-mac.dll").read_bytes()
van = (ROOT / "hardcore" / "_backup" / "Assembly-CSharp.dll.orig").read_bytes()
n = min(len(mac), len(van))
diff = [i for i in range(n) if mac[i] != van[i]]
print("  长度差 %+d   逐字节不同 %d 个 (%.1f%%)"
      % (len(mac) - len(van), len(diff), 100.0 * len(diff) / n))
if diff:
    runs = []
    s = prev = diff[0]
    for i in diff[1:]:
        if i - prev > 16:
            runs.append((s, prev))
            s = i
        prev = i
    runs.append((s, prev))
    print("  差异区段 %d 段；前 8 段：" % len(runs))
    for a2, b2 in runs[:8]:
        print("    0x%06X - 0x%06X  (%d B)" % (a2, b2, b2 - a2 + 1))

W = 48
print()
print("=== 位点相对窗口比对（各自用自己文件里的偏移）===")
for name, pat in (("A", core.CONST_ANCHOR), ("B2", core.B2_VANILLA)):
    om = mac.find(pat)
    ov = van.find(pat)
    if om < 0 or ov < 0:
        print("  %-3s 有一边没找到" % name)
        continue
    same = mac[om - W:om + W] == van[ov - W:ov + W]
    print("  %-3s mac@0x%06X win@0x%06X  Δ=%+d  ±%dB 窗口 %s"
          % (name, om, ov, om - ov, W, "逐字节相同" if same else "不同"))
    if not same:
        d = [i for i in range(2 * W) if mac[om - W + i] != van[ov - W + i]]
        print("       不同位置(相对) %s" % d[:20])
