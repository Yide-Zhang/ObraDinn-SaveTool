#!/usr/bin/env python3
"""启动 Obra Dinn 存档工具的本地 GUI。

    python run_gui.py                 # 启动并自动打开 app 窗口
    python run_gui.py --port 9000
    python run_gui.py --no-browser
    python run_gui.py --tab           # 用普通标签页，而不是 app 窗口

打包后没有终端可看，所以这里给 stdout/stderr **再挂一份日志文件**：

  Windows `--windowed` : `sys.stdout/stderr` 是 **None** —— 不接日志的话
                         `print()` 直接哑掉、`traceback.print_exc()` 可能报错，
                         表现就是「双击没反应」。
  macOS   `--windowed` : stdout/stderr 指向 /dev/null（**不是 None**），同样什么都查不到。

所以两个平台都用 tee 接一份，日志位置也按平台分开
（macOS 绝不能写进 .app 里面 —— bundle 应当是只读的）。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

LOG_NAME = "ObraDinnSaveTool.log"
LOG_MAX = 256 * 1024            # 超过就重开一个，避免无限增长


class _Tee:
    """一份写入同时送给多个流（日志 + 原流）；某个流坏了不影响其他流"""

    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, s):
        for f in self.streams:
            try:
                f.write(s)
            except Exception:                           # noqa: BLE001
                pass
        return len(s)

    def flush(self):
        for f in self.streams:
            try:
                f.flush()
            except Exception:                           # noqa: BLE001
                pass

    def isatty(self):
        return False


def _log_path() -> Path:
    """日志放哪：**macOS 打包后绝不能写进 .app 里面**（bundle 应当只读）"""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent / LOG_NAME
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Logs"
        d.mkdir(parents=True, exist_ok=True)
        return d / LOG_NAME
    return Path(sys.executable).resolve().parent / LOG_NAME


def _bootstrap_streams():
    """给 stdout/stderr 再挂一份日志文件，并写下本次运行的开始标记

    用追加而不是覆盖：两个实例不会互相冲掉对方的日志，
    「上次到底怎么了」也还能翻到。
    """
    try:
        log = _log_path()
        if log.exists() and log.stat().st_size > LOG_MAX:
            log.unlink()
        f = open(log, "a", encoding="utf-8", buffering=1)
    except OSError:                                     # 路径不可写就放弃记日志
        return None
    sys.stdout = _Tee(sys.stdout, f)
    sys.stderr = _Tee(sys.stderr, f)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n=== {stamp}  pid={os.getpid()} ===", file=sys.stderr, flush=True)
    return f


def _fatal(msg: str) -> None:
    """启动失败必须让用户看见 —— 打包后没有任何终端"""
    print(msg, file=sys.stderr, flush=True)
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, msg, "Obra Dinn 存档工具", 0x10)  # MB_ICONERROR
        elif sys.platform == "darwin":
            # AppleScript 的字符串字面量与 JSON 基本一致，直接借 json.dumps 转义
            script = 'display alert "Obra Dinn 存档工具" message ' + json.dumps(msg)
            subprocess.run(["osascript", "-e", script],
                           check=False, timeout=120)
    except Exception:                                   # noqa: BLE001
        pass


def main():
    _bootstrap_streams()
    ap = argparse.ArgumentParser(description="Obra Dinn 存档工具 GUI")
    ap.add_argument("--port", type=int, default=None, help="默认自动挑选")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--tab", action="store_true",
                    help="用普通浏览器标签页打开，而不是无地址栏的 app 窗口")
    a = ap.parse_args()
    try:
        from gui.server import serve
        serve(port=a.port, open_browser=not a.no_browser, app_mode=not a.tab)
    except Exception as e:                              # noqa: BLE001
        import traceback
        traceback.print_exc()
        try:
            where = f"\n\n详细日志：{_log_path()}"
        except OSError:
            where = ""
        _fatal(f"启动失败：{e}{where}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
