"""决定性判定：zh-s 的 help_faceclear_fates1 到底有没有多余空格。

全部用 ascii() 转义输出，排除控制台对 CJK 的渲染干扰。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hardcore"))
from patcher import core, langpatch_tool as lpt              # noqa: E402

KEY = "help_faceclear_fates1"


def show(tag: str, v: str) -> None:
    print("%-22s space=%-5s len=%-4d %s"
          % (tag, (" " in v), len(v), ascii(v)))


g = core.find_game()
if g:
    show("game(now)", lpt.bundle_values(core.streaming_assets(g) / "lang-zh-s")[KEY])

for lv in (6, 14, 29, 58):
    p = ROOT / "hardcore" / "_lang" / "out" / ("lv%d" % lv) / "lang-zh-s"
    if p.is_file():
        show("artifact lv%d" % lv, lpt.bundle_values(p)[KEY])

fp = lpt.fingerprints()["languages"]["zh-s"]
for lv in ("3", "4", "6", "9", "14", "29", "58"):
    show("fingerprint lv%s" % lv, fp[lv][KEY])

od = core.original_lang_dir()
if od and (od / "lang-zh-s").is_file():
    show("official orig", lpt.bundle_values(od / "lang-zh-s")[KEY])
bk = core.backup_dir() / "lang-zh-s"
if bk.is_file():
    show("backup(player)", lpt.bundle_values(bk)[KEY])

print()
print("--- zh-s 的 Token 表（S1 形状）---")
import numbers                                               # noqa: E402
t = numbers.NUMBERS["zh-s"][numbers.KEY_SHAPE[KEY]]
for lv in sorted(t):
    tok = t[lv]
    print("  lv%-4s space=%-5s %s" % (lv, (" " in tok), ascii(tok)))

print()
print("--- 各关键码点的全部键，逐个标出有没有空格 ---")
for src_name, p in (("game(now)", core.streaming_assets(g) / "lang-zh-s"),
                    ("fingerprint lv58", None)):
    if p is None:
        vals = fp["58"]
    else:
        vals = lpt.bundle_values(p)
    for k in lpt.KEYS:
        v = vals[k]
        print("  %-16s %-24s space=%-5s %s" % (src_name, k, (" " in v), ascii(v)))
