"""验证 mac DLL 就地打出来的补丁，与 Windows 已验证产物在 IL 上完全一致。"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from patcher import core                                    # noqa: E402

GEN = ROOT / "hardcore" / "gen" / "bin" / "Release" / "net8.0" / "genrecipes.exe"
OUT = ROOT / "mac_probe"
OUT.mkdir(exist_ok=True)

game = core.find_game()
deps = core.managed_dll(game).parent if game else None
print("依赖目录: %s" % deps)

mac = OUT / "Assembly-CSharp-mac.dll"
ref = ROOT / "hardcore" / "_patched" / "lc-lv4.dll"
made = OUT / "mac-lv4.dll"

rep = core.lpt.patch_dll(mac, 4, made, deps=deps)
ok, why = core.verify_patched_dll(made, 4)
print("mac -> lv4   四处自检: %s  %s" % ("[OK]" if ok else "[X]", why))
print("  尺寸 %d -> %d" % (mac.stat().st_size, made.stat().st_size))
print("  sha256 %s" % core.sha256_file(made)[:24])

LINE = re.compile(r"\s*(IL_[0-9A-F]{4})\s+@0x[0-9A-F]+\s+(\S+)\s*(.*)$")


def dump(dll: Path, typ: str, meth: str, out: Path):
    r = subprocess.run([str(GEN), "dump", str(dll), typ, meth, str(out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if not out.is_file():
        print("  dump 失败: %s" % (r.stderr or r.stdout)[-400:])
        return []
    res = []
    for ln in out.read_text(encoding="utf-8").splitlines():
        m = LINE.match(ln)
        if m:
            res.append((m.group(1), m.group(2), m.group(3).strip()))
    return res


print()
print("=== IL 逐指令比对（win 已验证产物 vs mac 现打产物）===")
for typ, meth in (("Book", "RevealCorrectGuesses"),
                  ("FateEditor", "UpdateFateGuesses")): 
    a = dump(ref, typ, meth, OUT / ("win.%s.txt" % meth))
    b = dump(made, typ, meth, OUT / ("mac.%s.txt" % meth))
    diff = [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]
    extra = abs(len(a) - len(b))
    print("  %-22s win %3d 条 / mac %3d 条 -> 不同 %d 条%s"
          % (meth, len(a), len(b), len(diff),
             "  [OK] 完全一致" if not diff and not extra else ""))
    for i, x, y in diff[:6]:
        print("     #%d" % i)
        print("       win %s" % (x,))
        print("       mac %s" % (y,))
