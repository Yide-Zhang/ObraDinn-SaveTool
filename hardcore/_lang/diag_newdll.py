"""诊断 originalDLLWin\\Assembly-CSharp.dll 是哪个 build、补丁位点还在不在。"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from patcher import core                                    # noqa: E402

NEW = ROOT / "originalDLLWin" / "Assembly-CSharp.dll"
VAN = ROOT / "hardcore" / "_backup" / "Assembly-CSharp.dll.orig"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


print("=== 基本 ===")
for tag, p in (("新给的 originalDLLWin", NEW), ("我们的原版 backup", VAN)):
    if p.is_file():
        b = p.read_bytes()
        print("%-22s %8d B  sha=%s" % (tag, len(b), sha(p)[:32]))

nb = NEW.read_bytes()
vb = VAN.read_bytes()

print()
print("=== 用我们自己的探针看它 ===")
info = core.probe_dll(NEW)
for k in ("kind", "level", "name", "size", "const", "const_candidates",
          "const_note", "seal_vanilla", "seal_patched", "patchable", "patch_note"):
    print("  %-18s %s" % (k, info.get(k)))
for w in info.get("warnings") or []:
    print("  warning            %s" % w)

print()
print("=== 锚点 / 签名 ===")
if not nb.startswith(b"MZ"):
    print("  不是 PE 文件?!")
anchor = core.CONST_ANCHOR
print("  CONST_ANCHOR 在新 DLL 里出现 %d 次" % nb.count(anchor))
print("  CONST_ANCHOR 在原版里出现   %d 次" % vb.count(anchor))
print("  SEAL_VANILLA 新=%s  原版=%s"
      % (bool(core.SEAL_VANILLA_RE.search(nb)),
         bool(core.SEAL_VANILLA_RE.search(vb))))
print("  SEAL_PATCHED 新=%s  原版=%s"
      % (bool(core.SEAL_PATCHED_RE.search(nb)),
         bool(core.SEAL_PATCHED_RE.search(vb))))

print()
print("=== 与原版的差异 ===")
n = min(len(nb), len(vb))
diff_pos = [i for i in range(n) if nb[i] != vb[i]]
print("  长度差 %+d B   逐字节不同的位置 %d 个" % (len(nb) - len(vb), len(diff_pos)))
if diff_pos:
    runs = []
    s = prev = diff_pos[0]
    for i in diff_pos[1:]:
        if i - prev > 16:
            runs.append((s, prev))
            s = i
        prev = i
    runs.append((s, prev))
    print("  差异区段 %d 段（间隔>16B 才算新段）:" % len(runs))
    for a, b2 in runs[:40]:
        print("    0x%06X - 0x%06X  (%d B)" % (a, b2, b2 - a + 1))
    if len(runs) > 40:
        print("    ... 还有 %d 段" % (len(runs) - 40))

print()
print("=== 新 DLL 里锚点附近 ===")
i = nb.find(anchor)
while i >= 0:
    s = max(0, i - 24)
    print("  @0x%06X  %s" % (i, nb[s:i + 40].hex(" ")))
    i = nb.find(anchor, i + 1)
