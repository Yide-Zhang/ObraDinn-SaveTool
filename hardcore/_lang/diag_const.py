"""核验 A 处常量解析：六个档位的基准产物都要读出正确的值。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from patcher import core                                    # noqa: E402

print("=== 基准产物目录 %s ===" % core.patched_dir())
for lv in core.PATCH_LEVELS:
    p = core.patched_dir() / ("lc-lv%d.dll" % lv)
    if not p.is_file():
        print("  lv%-3d 缺" % lv)
        continue
    buf = p.read_bytes()
    _, cands, note = core._const_value(buf)
    ok, why = core.verify_patched_dll(p, lv)
    print("  lv%-3d  解析=%-10s 四处自检 %s %s"
          % (lv, cands, "[OK]" if ok else "[X]", why))

print()
print("=== 官方原版应读成 3 ===")
od = core.original_dll()
if od and od.is_file():
    _, cands, _ = core._const_value(od.read_bytes())
    print("  %s -> %s" % (od.name, cands))

print()
print("=== probe_dll 对各档位 ===")
for lv in core.PATCH_LEVELS:
    p = core.patched_dir() / ("lc-lv%d.dll" % lv)
    if not p.is_file():
        continue
    i = core.probe_dll(p)
    print("  lv%-3d kind=%-8s level=%-5s const=%-5s 可就地改=%s"
          % (lv, i["kind"], i["level"], i["const"], i["patchable"]))
