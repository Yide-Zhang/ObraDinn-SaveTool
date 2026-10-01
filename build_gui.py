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

# 动态 import / 条件 import 的兜底，避免 PyInstaller 漏收。
# 注意：那几个 make_*_save 只有造预制存档时才用得上，精简版仓库里不一定有，
# 所以下面按「这个文件到底在不在」过滤 —— 否则 PyInstaller 会对每个缺失的
# hidden-import 各报一条 warning，看着像出错。
HIDDEN = [
    "gui", "gui.server", "gui.web", "gui.data",
    "save_tool", "make_envelope_save", "make_killer_captain_save",
    "make_ending_save", "make_blank_save",
    "parse_assets", "tea_decrypt", "test_roundtrip",
]


def available_hidden() -> list[str]:
    out = []
    for h in HIDDEN:
        p = ROOT.joinpath(*h.split("."))
        if p.with_suffix(".py").exists() or p.is_dir():
            out.append(h)
    return out


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

    if sys.platform == "darwin":
        cmd += ["--osx-bundle-identifier", BUNDLE_ID]
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
