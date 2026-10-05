#!/usr/bin/env python3
"""难度补丁器本地服务：静态前端 + 一个很小的 JSON API。

用法（一般不用直接跑，用 run_patch_gui.py）：
    python -m patcher.server [--port 8723] [--no-browser]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from patcher import core
from patcher.web import INDEX_HTML

PATCHER_DIR = Path(__file__).resolve().parent

APP_TITLE = "《奥伯拉丁的回归》难度补丁"
DEFAULT_PORT = 8723

FONT_EXTS = {".ttf", ".otf", ".woff", ".woff2"}

_LOCK = threading.Lock()
_BUSY = {"flag": False, "what": ""}


def font_dir() -> Path:
    """界面字体目录。用的是存档工具同款的两款字体（已子集化）。"""
    return PATCHER_DIR / "assets" / "fonts"


def font_file(name: str) -> Path | None:
    """只允许 font_dir() 下的字体文件，防目录穿越。"""
    root = font_dir().resolve()
    p = (font_dir() / name).resolve()
    if p.suffix.lower() not in FONT_EXTS or p.parent != root or not p.is_file():
        return None
    return p


def pick_folder(initial: str | None = None) -> dict:
    """弹一个系统目录选择框（弹在**服务所在的那台机器**上）。

    浏览器拿不到本地真实路径，所以只能让服务端弹。tkinter 是标准库，
    但打包时得确保它被带进去；用不了就退回手动填写。
    """
    try:
        import tkinter                                      # noqa: PLC0415
        from tkinter import filedialog                       # noqa: PLC0415
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False,
                "error": "系统目录选择框不可用（%s），请手动填写路径" % e}
    try:
        root = tkinter.Tk()
        root.withdraw()
        try:
            chosen = filedialog.askdirectory(
                title="选择 ObraDinn.exe 所在的目录",
                initialdir=initial or "", mustexist=True)
        finally:
            root.destroy()
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False,
                "error": "打开目录选择框失败（%s），请手动填写路径" % e}
    if not chosen:
        return {"ok": False, "cancelled": True}
    return {"ok": True, "path": chosen}


class Handler(BaseHTTPRequestHandler):
    server_version = "ObraDinnPatchGUI"
    protocol_version = "HTTP/1.1"

    # ---------- 工具 ----------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def log_message(self, fmt, *args):        # 静音：日志我们自己管
        pass

    # ---------- GET ----------
    def do_GET(self) -> None:                                   # noqa: N802
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path.startswith("/fonts/"):
            p = font_file(path[len("/fonts/"):])
            if p is None:
                self._json({"error": "没有这个字体"}, 404)
            else:
                ctype = ("font/ttf" if p.suffix.lower() == ".ttf"
                         else "font/otf")
                self._send(200, p.read_bytes(), ctype)
        elif path == "/api/state":
            self._json({"state": core.state(), "busy": _BUSY})
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._json({"error": "未知路径: %s" % path}, 404)

    # ---------- POST ----------
    def do_POST(self) -> None:                                  # noqa: N802
        path = urlsplit(self.path).path
        body = self._read_json()

        # 这两个不碰游戏文件，也不抢互斥锁
        # （选目录的对话框会把请求阻塞很久，锁住的话界面就动不了了）
        if path == "/api/pick-folder":
            self._json(pick_folder(core.load_settings().get("game_dir")))
            return
        if path == "/api/set-game":
            try:
                self._json(core.set_game_dir(str(body.get("path") or "")))
            except Exception as e:                          # noqa: BLE001
                self._json({"error": "%s: %s" % (type(e).__name__, e)}, 500)
            return

        if path not in ("/api/apply", "/api/restore", "/api/align"):
            self._json({"error": "未知路径: %s" % path}, 404)
            return

        if not _LOCK.acquire(blocking=False):
            self._json({"error": "上一个操作还没跑完，请稍候"}, 409)
            return
        _BUSY["flag"] = True
        _BUSY["what"] = path
        try:
            if path == "/api/apply":
                lv = int(body.get("level"))
                res = core.apply_level(lv, align=bool(body.get("align", True)))
            elif path == "/api/restore":
                res = core.restore()
                if res.get("ok"):
                    res.setdefault("log", []).append("已还原原始 DLL 与语言包")
            else:
                slot = str(body.get("slot") or "")
                lv = int(body.get("level"))
                if slot not in core.SLOTS:
                    res = {"ok": False, "error": "不认识的槽位: %s" % slot}
                else:
                    p = core.slot_path(slot)
                    if not p.is_file():
                        res = {"ok": False, "error": "槽位 %s 是空的" % slot}
                    else:
                        ok, detail, extra = core.align_save_file(p, lv)
                        res = {"ok": ok, "slot": slot, "detail": detail, **extra}
            self._json(res)
        except Exception as e:                          # noqa: BLE001
            import traceback
            self._json({"error": "%s: %s" % (type(e).__name__, e),
                        "traceback": traceback.format_exc()}, 500)
        finally:
            _BUSY["flag"] = False
            _BUSY["what"] = ""
            _LOCK.release()


# --------------------------------------------------------------------------
# 起服务 / 开窗口
# --------------------------------------------------------------------------
def _port_free(port: int) -> bool:
    import socket
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port(preferred: int = DEFAULT_PORT) -> int:
    for p in range(preferred, preferred + 40):
        if _port_free(p):
            return p
    return preferred


def _browser_exe() -> Path | None:
    cands: list[Path] = []
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        for base in (pf, pf86):
            for rel in (r"Microsoft\Edge\Application\msedge.exe",
                        r"Google\Chrome\Application\chrome.exe"):
                cands.append(Path(base) / rel)
        for rel in (r"Google\Chrome\Application\chrome.exe",
                    r"Microsoft\Edge\Application\msedge.exe"):
            if local:
                cands.append(Path(local) / rel)
    else:
        for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"):
            cands.append(Path(p))
    for c in cands:
        if c.is_file():
            return c
    return None


def open_window(url: str) -> str:
    """尽量用 Chromium 的 app 模式开一个无地址栏窗口；不行就退回默认浏览器。"""
    exe = _browser_exe()
    if exe is None:
        try:
            webbrowser.open(url)
            return "默认浏览器"
        except Exception:                                    # noqa: BLE001
            return "没打开（请手动访问 %s）" % url
    profile = core.data_dir() / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    args = [str(exe), "--app=" + url,
            "--user-data-dir=" + str(profile),
            "--no-first-run", "--no-default-browser-check",
            "--start-maximized", "--window-size=1180,900"]
    try:
        kwargs: dict = {"stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008      # DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(args, **kwargs)
        return exe.name
    except OSError:
        try:
            webbrowser.open(url)
            return "默认浏览器"
        except Exception:                                    # noqa: BLE001
            return "没打开（请手动访问 %s）" % url


def serve(port: int = DEFAULT_PORT, open_browser: bool = True,
          watch_parent: bool = True) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = "http://127.0.0.1:%d/" % port

    print("=" * 66)
    print("  %s" % APP_TITLE)
    print("  服务地址：%s" % url)
    print("  游戏目录：%s" % (core.find_game() or "**没找到**"))
    print("  数据目录：%s" % core.data_dir())
    print("  关掉这个窗口（或按 Ctrl+C）即退出。")
    print("=" * 66)

    if open_browser:
        how = open_window(url)
        print("  已尝试用 %s 打开界面。" % how)
    if watch_parent:
        _spawn_parent_watch(httpd)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  收到 Ctrl+C，退出。")
    finally:
        httpd.server_close()


def _spawn_parent_watch(httpd: ThreadingHTTPServer) -> None:
    """用 --windowed 打包时，浏览器窗口关了但进程还在，这里做一次自退役。

    ⚠️ 两个必须的保守条件，实测漏了第一个就出事：界面还开着，服务却被自己
    关掉了（日志里留下「界面已关闭，服务退出。」，前端随后全是连接被拒）。
      1. **必须先成功探测过一次**，才开始把失败当真 —— 冷启动时端口未必就绪
      2. 连续失败要够多（12 次 = 约 60 秒），一次抖动不算
    """
    def beat() -> None:
        import time
        misses = 0
        seen_ok = False
        while True:
            time.sleep(5)
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/api/state" % httpd.server_port,
                        timeout=3) as r:
                    r.read(1)
                seen_ok = True
                misses = 0
            except Exception:                                # noqa: BLE001
                if not seen_ok:
                    continue
                misses += 1
                if misses >= 12:
                    print("  界面已关闭，服务退出。")
                    httpd.shutdown()
                    return
    threading.Thread(target=beat, daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=APP_TITLE)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    port = a.port or pick_port(DEFAULT_PORT)
    if not _port_free(port):
        print("端口 %d 被占用，换一个。" % port)
        port = pick_port(port + 1)
    serve(port, open_browser=not a.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
