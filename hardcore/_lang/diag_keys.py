"""打印某个语言包里那 4 个键的当前值。用法：diag_keys.py <包路径> [更多包…]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "patcher").is_dir():        # 从别处（例如 /tmp）跑时按当前目录算
    ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from patcher import core, langpatch_tool as lpt              # noqa: E402

if len(sys.argv) < 2:
    d = core.original_lang_dir()
    print("（没给路径）原始语言包目录候选: %s" % d)
    sys.exit(0)

for a in sys.argv[1:]:
    p = Path(a)
    print("=== %s  (%s)" % (p, "存在" if p.is_file() else "不存在"))
    if not p.is_file():
        continue
    try:
        v = lpt.bundle_values(p)
    except Exception as e:                                   # noqa: BLE001
        print("   读失败: %s: %s" % (type(e).__name__, e))
        continue
    for k in lpt.KEYS:
        print("   %-24s %r" % (k, v.get(k)))
    print("   level_of = %s" % lpt.level_of(p.name[5:], v))
