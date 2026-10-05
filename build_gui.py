#!/usr/bin/env python3
"""把 GUI 打包成 Windows .exe / macOS .app。

    python build_gui.py                # 默认：单文件、不弹控制台、启动后自动开浏览器
    python build_gui.py --console      # 调试用：带上控制台窗口
    python build_gui.py --onedir       # 打成目录（macOS 默认）

产物：
    Windows  dist/ObraDinnSaveTool.exe
    macOS    dist/ObraDinnSaveTool.app

双击就像普通程序：没有黑窗，直接开系统默认浏览器。
没有控制台就没了 Ctrl+C，所以退出靠页面右上角的「退出程序」。

依赖：pyinstaller（脚本会提示安装命令）。整个项目零第三方运行时依赖，
      所以打包出来的东西很小，也不需要 --add-data（除了字体和预制存档）。
"""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "run_gui.py"
APP = "ObraDinnSaveTool"
BUNDLE_ID = "com.obradinn.savetool"

#: exe 图标：由 icon_save.png 生成。**必须含 16×16** —— 资源管理器「小图标」
#: 视图只认那一档，缺了就回落成 exe 自带的默认图标（这个坑踩过一次）。
ICON_PNG = ROOT / "icon_save.png"
ICON_ICO = ROOT / "icon_save.ico"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# 动态 import / 条件 import 的兜底，避免 PyInstaller 漏收。
# 注意：那几个 make_*_save 只有造预制存档时才用得上，精简版仓库里不一定有，
# 所以下面按「这个文件到底在不在」过滤 —— 否则 PyInstaller 会对每个缺失的
# hidden-import 各报一条 warning，看着像出错。
HIDDEN = [
    "gui", "gui.server", "gui.web", "gui.data",
    "save_tool", "make_envelope_save", "make_killer_captain_save",
    "make_ending_save", "make_blank_save",
    "parse_assets", "tea_decrypt", "test_roundtrip",
    # 「装载存档前对一下难度」靠这两个包（gui.server 里是延迟 import，
    # PyInstaller 的静态分析看不到）：patcher 读游戏当前难度，
    # hardcore.align_save 算这份存档能不能通关。
    "patcher", "patcher.core", "hardcore", "hardcore.align_save",
]


def available_hidden() -> list[str]:
    out = []
    for h in HIDDEN:
        p = ROOT.joinpath(*h.split("."))
        if p.with_suffix(".py").exists() or p.is_dir():
            out.append(h)
    return out


def make_ico() -> Path | None:
    """icon_save.png → icon_save.ico（多尺寸）。已生成且不比 png 旧就复用。"""
    if not ICON_PNG.is_file():
        print(f"[!] 找不到图标源 {ICON_PNG.name}，exe 用默认图标")
        return None
    if ICON_ICO.is_file() and ICON_ICO.stat().st_mtime >= ICON_PNG.stat().st_mtime:
        return ICON_ICO
    try:
        from PIL import Image                            # noqa: PLC0415
    except ImportError:
        print("[!] 没装 Pillow，生成不了 .ico，exe 用默认图标")
        return None
    img = Image.open(ICON_PNG).convert("RGBA")
    if max(img.size) < ICO_SIZES[-1]:
        # 源图比 256 小的时候 Pillow 不会放大，256 那档会**直接少掉**
        # （资源管理器「超大图标」就只能拿 128 顶）——先自己补到 256。
        img = img.resize((ICO_SIZES[-1], ICO_SIZES[-1]), Image.LANCZOS)
    img.save(ICON_ICO, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print("[i] 生成 %s：%d~%d 共 %d 档（%.1f KB）"
          % (ICON_ICO.name, ICO_SIZES[0], ICO_SIZES[-1], len(ICO_SIZES),
             ICON_ICO.stat().st_size / 1024))
    return ICON_ICO


def check_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        print("[-] 没装 pyinstaller。先运行：")
        print(f"      {sys.executable} -m pip install --upgrade pyinstaller")
        return False


def build(onefile: bool, console: bool, clean: bool) -> int:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--name", APP,
           "--paths", str(ROOT)]
    # hardcore/ 里的模块是**按顶层名字**互相 import 的（align_save.py 里
    # `from make_envelope_save import …`），不把 hardcore 本身加进搜索路径，
    # 冻结后会 ModuleNotFoundError: No module named 'make_envelope_save'。
    if (ROOT / "hardcore").is_dir():
        cmd += ["--paths", str(ROOT / "hardcore")]
    if clean:
        cmd.append("--clean")
    cmd.append("--onefile" if onefile else "--onedir")
    cmd.append("--console" if console else "--windowed")
    hidden = available_hidden()
    if len(hidden) != len(HIDDEN):
        missing = [h for h in HIDDEN if h not in hidden]
        print(f"[i] 跳过不存在的模块: {missing}")
    for h in hidden:
        cmd += ["--hidden-import", h]
    fonts = ROOT / "gui" / "fonts"
    if fonts.is_dir():
        cmd += ["--add-data", f"{fonts}{os.pathsep}gui/fonts"]
        print(f"[i] 内置字体: {[p.name for p in sorted(fonts.iterdir())]}")

    # 预制存档也随程序分发（只读模板区），没带上 exe 里就一个都看不到
    presets = ROOT / "gui" / "presets"
    preset_txt = sorted(presets.glob("*.txt")) if presets.is_dir() else []
    if preset_txt:
        cmd += ["--add-data", f"{presets}{os.pathsep}gui/presets"]
        print(f"[i] 内置预制存档: {[p.name for p in preset_txt]}")
    else:
        print("[!] gui/presets/ 里没有预制存档，先跑：python gen_presets.py")

    # 存档制作器页面（deck_state.py 生成）：服务端 /maker 直接从资源根取它
    maker = ROOT / "deck-state.html"
    if maker.is_file():
        cmd += ["--add-data", f"{maker}{os.pathsep}."]
        print(f"[i] 内置存档制作器: deck-state.html ({maker.stat().st_size // 1024} KB)")
    else:
        print("[!] 没有 deck-state.html，先跑：python deck_state.py")

    if sys.platform == "win32":
        ico = make_ico()
        if ico:
            cmd += ["--icon", str(ico)]
    if sys.platform == "darwin":
        # macOS 要 .icns（由 _remote/build-savetool-mac.sh 用 sips+iconutil 生成）
        icns = ROOT / "icon_save.icns"
        if icns.is_file():
            cmd += ["--icon", str(icns)]
            print(f"[i] .app 图标: {icns.name}")
        else:
            print("[i] 没有 icon_save.icns，.app 用默认图标")
        cmd += ["--osx-bundle-identifier", BUNDLE_ID]

    # 目标还在运行的时候，PyInstaller 会甩一大段 PermissionError 出来，先拦一下说人话
    if sys.platform == "win32" and onefile:
        target = ROOT / "dist" / (APP + ".exe")
        if target.is_file():
            try:
                with open(target, "ab"):
                    pass
            except OSError:
                print(f"[!] {target.name} 正被占用 —— 先关掉正在运行的存档工具，再打包")
                return 1
    cmd.append(str(ENTRY))

    print("[i] " + " ".join(cmd))
    rc = subprocess.call(cmd, cwd=ROOT)
    if rc != 0:
        print("[-] 打包失败")
        return rc

    ext = ".app" if sys.platform == "darwin" else (".exe" if onefile else "")
    out = ROOT / "dist" / (APP + ext if ext else APP)
    print(f"[+] 完成：{out}")
    print("    直接把可执行文件拷走即可；存档库默认建在同目录的 saves/")
    return 0


def main():
    ap = argparse.ArgumentParser(description="打包 Obra Dinn 存档工具 GUI")
    ap.add_argument("--onefile", action="store_true",
                    default=(platform.system() == "Windows"),
                    help="打成单文件（Windows 默认开）")
    ap.add_argument("--onedir", dest="onefile", action="store_false",
                    help="打成目录（macOS 默认）")
    ap.add_argument("--console", dest="console", action="store_true",
                    default=False,
                    help="带上控制台窗口（默认关：双击不弹黑窗，像普通程序）")
    ap.add_argument("--noconsole", dest="console", action="store_false",
                    help="不显示控制台窗口（默认就是这个，写了也无妨）")
    ap.add_argument("--no-clean", dest="clean", action="store_false", default=True)
    a = ap.parse_args()

    if not check_pyinstaller():
        return 1
    return build(a.onefile, a.console, a.clean)


if __name__ == "__main__":
    sys.exit(main())
