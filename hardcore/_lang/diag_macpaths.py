"""验证 mac 布局的路径识别（在 Windows 上造一个假的 .app 结构来测）。"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from patcher import core                                    # noqa: E402

FAKE = ROOT / "mac_probe" / "FakeApp"
shutil.rmtree(FAKE, ignore_errors=True)
app = FAKE / "Return of the Obra Dinn.app"
data = app / "Contents" / "Resources" / "Data"
(data / "Managed").mkdir(parents=True)
(data / "StreamingAssets").mkdir(parents=True)
(data / "Managed" / core.DLL_NAME).write_bytes(b"MZ fake")
(data / "StreamingAssets" / "lang-en").write_bytes(b"x")

print("=== mac 布局识别 ===")
cases = [
    ("（.app 本身）", app),
    ("（Contents/Resources）", app / "Contents" / "Resources"),
    ("（Contents）", app / "Contents"),
    ("（Data 本身）", data),
    ("（.app 的父目录，不该中）", FAKE),
]
for tag, p in cases:
    print("  looks_like_game  %-34s -> %s" % (tag, core.looks_like_game(p)))
    print("      data_dir_of  %s" % core.data_dir_of(p).relative_to(FAKE).as_posix())

print()
print("=== resolve_game_dir（玩家会怎么填）===")
for tag, s in [
    ("拖 .app 进来", str(app)),
    ("填 .app 所在目录（+自动下探）", str(app)),
    ("填 Contents/Resources", str(app / "Contents" / "Resources")),
    ("带引号+尾部斜杠", '"%s/"' % app),
    ("Windows 风格（本机游戏）", str(core.find_game())),
]:
    p, why = core.resolve_game_dir(s)
    print("  %-28s -> %s" % (tag, p if p else ("[X] " + why.replace("\n", " ")[:60])))

print()
print("=== streaming_assets / managed_dll ===")
print("  managed_dll      %s" % core.managed_dll(app).relative_to(FAKE).as_posix())
print("  streaming_assets %s" % core.streaming_assets(app).relative_to(FAKE).as_posix())

print()
print("=== 本机（Windows）不受影响 ===")
g = core.find_game()
print("  find_game        %s" % g)
if g:
    print("  managed_dll      %s" % core.managed_dll(g))
    print("  streaming_assets %s" % core.streaming_assets(g))
    print("  looks_like_game  %s" % core.looks_like_game(g))
shutil.rmtree(FAKE, ignore_errors=True)
