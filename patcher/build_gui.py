#!/usr/bin/env python3
"""把难度补丁器打包成可执行文件。

    python -m patcher.build_gui            # 默认：目录版（onedir），不弹控制台
    python -m patcher.build_gui --console  # 调试用：带控制台窗口
    python -m patcher.build_gui --onefile  # 单文件（不推荐，见下）
    python -m patcher.build_gui --check    # 只做前置检查，不打包

为什么默认**目录版**：要带约 13 MB 资源 —— 自包含 langtool.exe（改语言包 +
就地给 DLL 打补丁）、官方原版 DLL、子集化字体、文本指纹表。目录版启动快，
langtool.exe 也就在旁边看得见；单文件每次启动都要把这些解到临时目录，
既慢又容易撞上杀软。

（发布用的 Windows 包就是 `--onefile` 打的：实测首次可用约 2 秒、19.7 MB、
解压出来只有一个 exe；目录版仍保留为默认值，调试时能直接看见 langtool.exe。）

产物：
    dist/ObraDinnDifficultyPatcher/ObraDinnDifficultyPatcher[.exe]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PATCHER_DIR = Path(__file__).resolve().parent
ROOT = PATCHER_DIR.parent
ENTRY = ROOT / "run_patch_gui.py"
APP = "ObraDinnDifficultyPatcher"

#: exe 图标：由 icon-difficulty.png 生成。**必须含 16×16** —— 资源管理器
#: 「小图标」视图只认那一档，缺了就回落成 PyInstaller 的默认图标。
ICON_PNG = ROOT / "icon-difficulty.png"
ICON_ICO = ROOT / "icon-difficulty.ico"
ICON_ICNS = ROOT / "icon-difficulty.icns"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# PyInstaller 静态分析跟不到的（动态 import / 条件 import）
HIDDEN = (
    "patcher", "patcher.core", "patcher.server", "patcher.web",
    "patcher.langpatch_tool",
    "lz4", "lz4.block",
    "tkinter", "tkinter.filedialog", "tkinter.messagebox",
    "arabic_reshaper",          # 只有阿拉伯语用得上，缺了会走兜底
)

ADD_DATA = (
    ("patcher/assets", "patcher/assets"),
    ("patcher/data", "patcher/data"),
    # numbers.py 是**按文件路径**加载的（不是 import），所以必须是真实文件
    ("hardcore/_lang/numbers.py", "hardcore/_lang"),
    # parse_assets 会去读这个目录（游戏资产的文本导出，实测只有 30 KB）
    ("txtAssetDump", "txtAssetDump"),
    ("ids_reference.json", "."),
)

# 额外的模块搜索路径。
# hardcore/ 里的模块是**按顶层名字**互相 import 的（例如
# `from make_hardcore_edge import set_face`），PyInstaller 的静态分析只认
# --paths，不给 hardcore/ 就解析不到 —— 冻结后会在读存档时报
# ModuleNotFoundError: No module named 'make_hardcore_edge'。
EXTRA_PATHS = ("hardcore",)

# 明确排除的开发期依赖。
# 实测：不排除时产物 56.7 MB —— fontTools（在子集化脚本里“延迟 import”）和
# lxml 就占掉 10 MB，而且它们运行时根本用不到（子集化/验证只在开发机上跑）。
EXCLUDE = (
    "fontTools", "lxml", "brotli", "PIL", "numpy", "pytest",
    "setuptools", "pip", "pkg_resources",
    # 只给开发机用的模块，打包后不跑（打包时用的是源码里的版本）
    "patcher.build_gui", "patcher.subset_fonts",
    "patcher.verify_font_coverage", "patcher.prepare_assets",
    "patcher.gui_smoke", "patcher.selftest",
)


def _utf8() -> None:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def check_pyinstaller() -> bool:
    try:
        import PyInstaller                                # noqa: F401, PLC0415
        return True
    except ImportError:
        print("[X] 没装 pyinstaller。先运行：")
        print("      %s -m pip install --upgrade pyinstaller" % sys.executable)
        return False


def _patchdll_smoke() -> bool:
    """拿随附的官方原版打一版 lv4，四处逐个验；有参照产物就再逐字节比一次。"""
    import tempfile
    from patcher import core                              # noqa: PLC0415

    st = core._patchdll_state()
    print("  patchdll     : %s  %s"
          % ("可用" if st["ok"] else "不可用", st["detail"]))
    if not st["ok"]:
        return False

    od = core.original_dll()
    if od is None or not od.is_file():
        print("  patchdll 自检: 跳过（没有随附的官方原版 DLL）")
        return True

    game = core.find_game()
    deps = core.managed_dll(game).parent if game else None
    if deps is None or not deps.is_dir():
        print("  patchdll 自检: 跳过（本机找不到游戏，拿不到 UnityEngine 依赖）")
        return True

    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "t.dll"
            core.lpt.patch_dll(od, 4, out, deps=deps)
            vok, vwhy = core.verify_patched_dll(out, 4)
            if not vok:
                print("  patchdll 自检: [X] %s" % vwhy)
                return False
            ref = core.patched_dir() / "lc-lv4.dll"
            if ref.is_file():
                same = core.sha256_file(out) == core.sha256_file(ref)
                print("  patchdll 自检: 四处到位，与 lc-lv4.dll %s"
                      % ("逐字节一致 [OK]" if same else "不一致 [X]"))
                return same
            print("  patchdll 自检: 四处到位 [OK]（无参照产物可比）")
            return True
    except Exception as e:                                  # noqa: BLE001
        print("  patchdll 自检: [X] %s: %s" % (type(e).__name__, e))
        return False


def preflight() -> bool:
    """打包前把该有的都点一遍 —— 少东西宁可现在失败，别让玩家遇到。"""
    sys.path.insert(0, str(ROOT))
    from patcher import core, verify_font_coverage         # noqa: PLC0415

    ok = True
    out = PATCHER_DIR / "assets"

    # DLL 就地打补丁这条路必须真能跑通 —— 拿随附的官方原版打一版 lv4，
    # 四处逐个验；手边有已验证产物的话再逐字节比一次。
    ok &= _patchdll_smoke()

    od = core.original_dll()
    if od is None or not od.is_file():
        print("  原版 DLL      : 缺")
        ok = False
    else:
        # 硬编码的那个哈希是 Windows 那份的；mac 是另一份 build，只能按结构判
        same = core.sha256_file(od) == core.VANILLA_DLL_SHA256
        shape = core._looks_vanilla(od)                          # noqa: SLF001
        print("  原版 DLL      : %s  %s"
              % (od.name, "哈希对得上" if same
                 else ("原版形态（另一个 build）" if shape
                       else "既不是已知原版、形态也不对")))
        ok &= (same or shape)

    exe = core.lpt.standalone_exe()
    have_langtool = exe is not None and exe.is_file()
    print("  langtool.exe  : %s" % (exe if have_langtool else "缺（换难度要靠它）"))
    ok &= have_langtool

    fonts = sorted((out / "fonts").glob("*")) if (out / "fonts").is_dir() else []
    print("  界面字体      : %s" % [p.name for p in fonts])
    ok &= len(fonts) == 2

    fp = core.fingerprint_file()
    print("  文本指纹表    : %s" % (fp if fp.is_file() else "缺"))
    ok &= fp.is_file()

    # 字体与文案的一致性 —— 这正是之前漏过字的地方，必须过
    print("  --- 字体覆盖检查 ---")
    if verify_font_coverage.main([]) != 0:
        print("  [X] 字体检查没过")
        ok = False

    # 运行时要用的第三方模块
    # ⚠ lz4 是**真的**要：`patcher/langpatch_tool.py` 的 `bundle_values()` 会
    #   延迟 import `hardcore.lang_bundle`（读玩家语言包的 UnityFS），而它
    #   `import lz4.block`。曾经以为 lz4 只是开发期依赖、从检查里去掉了，
    #   结果 mac 上换档直接挂在 “No module named 'lz4'”。
    for mod in ("lz4.block", "tkinter"):
        try:
            __import__(mod)
            print("  运行时依赖 %-12s: 有" % mod)
        except ImportError as e:
            print("  运行时依赖 %-12s: 缺（%s）" % (mod, e))
            ok = False
    return ok


def make_ico() -> Path | None:
    """icon-difficulty.png → icon-difficulty.ico（多尺寸）。已生成且不比 png 旧就复用。"""
    if not ICON_PNG.is_file():
        print("[!] 找不到图标源 %s，exe 用默认图标" % ICON_PNG.name)
        return None
    if ICON_ICO.is_file() and ICON_ICO.stat().st_mtime >= ICON_PNG.stat().st_mtime:
        return ICON_ICO
    try:
        from PIL import Image                                  # noqa: PLC0415
    except ImportError:
        print("[!] 没装 Pillow，生成不了 .ico，exe 用默认图标")
        return None
    img = Image.open(ICON_PNG).convert("RGBA")
    if max(img.size) < ICO_SIZES[-1]:
        # 源图比 256 小的时候 Pillow 不会放大，256 那档会**直接少掉**
        img = img.resize((ICO_SIZES[-1], ICO_SIZES[-1]), Image.LANCZOS)
    img.save(ICON_ICO, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print("  图标: %s（%d~%d 共 %d 档，%.1f KB）"
          % (ICON_ICO.name, ICO_SIZES[0], ICO_SIZES[-1], len(ICO_SIZES),
             ICON_ICO.stat().st_size / 1024))
    return ICON_ICO


def build(onefile: bool, console: bool, clean: bool) -> int:
    if not check_pyinstaller():
        return 2

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm",
           "--name", APP, "--paths", str(ROOT)]
    for ep in EXTRA_PATHS:
        cmd += ["--paths", str(ROOT / ep)]
    if clean:
        cmd.append("--clean")
    cmd.append("--onefile" if onefile else "--onedir")
    cmd.append("--console" if console else "--windowed")
    for h in HIDDEN:
        cmd += ["--hidden-import", h]
    for m in EXCLUDE:
        cmd += ["--exclude-module", m]
    for src, dst in ADD_DATA:
        p = ROOT / src
        if not p.exists():
            print("[X] 找不到要打包的资源: %s" % p)
            return 2
        cmd += ["--add-data", "%s%s%s" % (p, os.pathsep, dst)]
        print("  打包资源: %-34s -> %s" % (src, dst))

    if sys.platform == "win32":
        ico = make_ico()
        if ico:
            cmd += ["--icon", str(ico)]
    elif sys.platform == "darwin":
        if ICON_ICNS.is_file():
            cmd += ["--icon", str(ICON_ICNS)]
            print("  图标: %s" % ICON_ICNS.name)
        else:
            print("[i] 没有 %s，.app 用默认图标" % ICON_ICNS.name)

    cmd.append(str(ENTRY))
    print()
    print("[i] 开始打包（首次会慢一些）…")
    print("[i] 排除的开发期依赖：%s" % ", ".join(EXCLUDE[:6]))
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        print("[X] PyInstaller 返回 %d" % r.returncode)
        return r.returncode

    if onefile:
        dist = ROOT / "dist" / (APP + (".exe" if os.name == "nt" else ""))
        size = dist.stat().st_size if dist.is_file() else 0
    else:
        dist = ROOT / "dist" / APP
        size = (sum(p.stat().st_size for p in dist.rglob("*") if p.is_file())
                if dist.is_dir() else 0)
    print()
    print("=" * 66)
    print("  产物 : %s" % dist)
    print("  体积 : %.1f MB" % (size / 1048576))
    print("=" * 66)
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8()
    ap = argparse.ArgumentParser(description="打包难度补丁器")
    ap.add_argument("--onefile", action="store_true")
    ap.add_argument("--console", action="store_true")
    ap.add_argument("--no-clean", action="store_true")
    ap.add_argument("--check", action="store_true", help="只做前置检查")
    a = ap.parse_args(argv)

    print("=" * 66)
    print("前置检查")
    print("=" * 66)
    if not preflight():
        print()
        print("[X] 前置检查没过，先补齐再打包")
        return 1
    print()
    print("[OK] 前置检查都过了")

    if a.check:
        return 0
    return build(a.onefile, a.console, not a.no_clean)


if __name__ == "__main__":
    sys.exit(main())
