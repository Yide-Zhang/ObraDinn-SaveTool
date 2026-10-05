"""查 B1 字节判据为什么认不出已打补丁的 DLL。"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from patcher import core                                    # noqa: E402

TARGETS = [
    ("游戏现在的(6)", core.managed_dll(core.find_game())),
    ("_patched lv4", ROOT / "hardcore" / "_patched" / "lc-lv4.dll"),
    ("官方原版", ROOT / "hardcore" / "_backup" / "Assembly-CSharp.dll.orig"),
]

for tag, p in TARGETS:
    buf = p.read_bytes()
    print("=== %s  %s" % (tag, p.name))
    op = core._b1_branch_op(buf)
    print("  core._b1_branch_op = %s" % (("0x%02X" % op) if op is not None else None))
    n = 0
    for m in re.finditer(rb"\x18([\x2b\x2e\x38\x40])", buf):
        b = m.group(1)[0]
        after = m.end()
        if b in (0x38, 0x40):
            if after + 4 > len(buf):
                continue
            tgt = after + 4 + int.from_bytes(buf[after:after + 4], "little", signed=True)
        else:
            if after + 1 > len(buf):
                continue
            tgt = after + 1 + int.from_bytes(buf[after:after + 1], "little", signed=True)
        ok = 0 <= tgt < len(buf) - 1 and buf[tgt:tgt + 2] == b"\x19\x8d"
        pre = "%02X" % buf[m.start() - 5] if m.start() >= 5 else "-"
        print("   @0x%06X  18 %02X  tgt=0x%06X %-8s 前第5字节=%s"
              % (m.start(), b, tgt, "->19 8d" if ok else "", pre))
        n += 1
        if n > 12:
            print("   ...")
            break
    if n == 0:
        print("   （一个 18+分支 都没找到）")
