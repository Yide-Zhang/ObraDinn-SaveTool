"""Obra Dinn 存档工具 —— 本地 web GUI 的后端。

零第三方依赖（只用标准库 http.server），便于 PyInstaller 打成单文件 exe / .app。

    python -m gui.server            # 启动并打开浏览器
    python run_gui.py               # 等价入口

设计：
  * 只绑定 127.0.0.1，端口自动挑选
  * 所有 path 参数都必须落在「允许的根目录」内（游戏存档目录 ∪ 存档库），
    防止页面被诱导读写任意文件
  * 任何写入都先备份
"""
from __future__ import annotations

import json
import mimetypes
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 允许以 `python gui/server.py` 直接跑：把仓库根目录加进 sys.path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from save_tool import (SLOTS, describe, game_dir, load_checked, save_save,  # noqa: E402
                       sha256, slot_path, get_gender, set_gender)

try:
    from gui.data import CREW, OFFICE, SHIP
except ImportError:                                     # 直接跑脚本时
    from data import CREW, OFFICE, SHIP                 # type: ignore

from gui.web import INDEX_HTML                          # noqa: E402

APP_NAME = "ObraDinnSaveTool"
APP_VERSION = "0.1.0"

# 开发热重载：为 True 时每次 GET / 都重新导入 gui.web，
# 这样改 CSS/JS 只需刷新浏览器，不用重启服务
DEV_RELOAD = os.environ.get("OBRADINN_GUI_DEV") == "1"


# ------------------------------------------------------------------ 目录
def app_dir() -> Path:
    """打包后 = exe / .app 所在目录；源码运行时 = 仓库根目录"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def library_dir() -> Path:
    """存档库：优先放在程序旁边（便携），macOS 打包后放 ~/Documents（bundle 内不该写）"""
    env = os.environ.get("OBRADINN_LIBRARY")
    if env:
        p = Path(env)
        p.mkdir(parents=True, exist_ok=True)
        return p

    frozen_mac = getattr(sys, "frozen", False) and sys.platform == "darwin"
    if not frozen_mac:
        cand = app_dir() / "saves"
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return cand
        except OSError:
            pass

    fallback = Path.home() / "Documents" / "ObraDinnSaves"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def allowed_roots() -> list[Path]:
    return [game_dir(), library_dir(), presets_dir()]


def presets_dir() -> Path:
    """预制存档目录（随程序分发，**只读**）

    和 `gui/fonts` 一样由 `--add-data` 带进 exe，所以不能放进存档库 ——
    那个目录用户可写可删，删掉就再也回不来了。
    """
    return resource_dir() / "gui" / "presets"


PRESET_META = "presets.json"        # 文件名 -> 注释名（显示名映射）


def is_preset(p: Path) -> bool:
    """判断一个路径是不是预制存档（预制存档一律不许就地改写）"""
    try:
        Path(p).resolve().relative_to(presets_dir().resolve())
        return True
    except (ValueError, OSError):
        return False


def resource_dir() -> Path:
    """静态资源根：源码运行时 = 仓库根；PyInstaller 打包后 = _MEIPASS"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def font_dir() -> Path:
    return resource_dir() / "gui" / "fonts"


FONT_EXTS = {".ttf", ".otf", ".woff", ".woff2"}


def font_file(name: str) -> Path:
    """只允许 font_dir() 下的字体文件，防目录穿越"""
    root = font_dir().resolve()
    p = (root / Path(urllib.parse.unquote(name)).name).resolve()
    if p.suffix.lower() not in FONT_EXTS or p.parent != root or not p.is_file():
        raise ApiError(f"字体不存在: {name}")
    return p


def safe_path(raw: str | None) -> Path:
    """把请求里的路径限制在允许的根目录内"""
    if not raw:
        raise ApiError("缺少 path 参数")
    p = Path(raw).resolve()
    for root in allowed_roots():
        try:
            p.relative_to(root.resolve())
            return p
        except ValueError:
            continue
    raise ApiError(f"路径不在允许范围内（存档目录 / 存档库）: {raw}")


class ApiError(Exception):
    pass


def same_origin(origin: str | None, port: int) -> bool:
    """挡掉网页对本地服务的跨站 POST

    浏览器对 POST 一定会带 `Origin`（沙箱 iframe 是 `null`），所以：
    没带 = 非浏览器客户端（curl 等）放行；带了就比端口
    —— 这样 `127.0.0.1` 和 `localhost` 两种写法都认。

    只给「退出程序」这种被外部网页顺手触发很讨厌的接口用。
    """
    if not origin:
        return True
    try:
        return urllib.parse.urlparse(origin).port == port
    except ValueError:
        return False


# ------------------------------------------------------------------ 数据组装
def _info_or_error(path: Path) -> dict:
    try:
        d = describe(path, CREW, SHIP, OFFICE)
        d.pop("file", None)
        return {"ok": True, "info": d}
    except Exception as e:                              # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _row(path: Path) -> dict:
    st = path.stat()
    return {"path": str(path), "name": path.name, "bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "mtime_ts": st.st_mtime}


def slots_state() -> list[dict]:
    out = []
    for s in SLOTS:
        p = slot_path(s)
        row = {"slot": s, "path": str(p), "exists": p.exists()}
        if p.exists():
            row.update(_row(p))
            row.update(_info_or_error(p))
        out.append(row)
    return out


def library_state() -> list[dict]:
    lib = library_dir()
    rows = []
    for p in sorted(lib.glob("*.txt")):
        row = _row(p)
        row["exists"] = True
        row.update(_info_or_error(p))
        rows.append(row)
    rows.sort(key=lambda r: r["mtime_ts"], reverse=True)
    return rows


def presets_state() -> list[dict]:
    """预制存档列表：注释名取自 presets.json，顺序也跟它走"""
    d = presets_dir()
    if not d.is_dir():
        return []
    meta: dict = {}
    mf = d / PRESET_META
    if mf.is_file():
        try:
            meta = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:               # noqa: BLE001
            print(f"[!] 读不了 {mf}: {e}", file=sys.stderr)
    rows = []
    for p in sorted(d.glob("*.txt")):
        row = _row(p)
        row["exists"] = True
        row["comment"] = (meta.get(p.name) or {}).get("name") or p.stem
        row.update(_info_or_error(p))
        rows.append(row)
    order = {name: i for i, name in enumerate(meta)}
    rows.sort(key=lambda r: order.get(r["name"], len(order)))
    return rows


def backups_state(slot: str) -> list[dict]:
    from save_tool import list_backups
    rows = []
    # 必须传内置名单：exe 里没有 txtAssetDump/，不传会去读资产表而报错
    for r in list_backups(slot, crew=CREW, ship=SHIP, office=OFFICE):
        item = {"path": r["path"], "name": r["name"], "bytes": r["bytes"],
                "mtime": r["mtime"], "source": _backup_source(r["path"])}
        if "info" in r:
            item["ok"] = True
            item["info"] = {k: r["info"][k] for k in
                            ("fates_correct", "crew_total", "era", "phase", "gender",
                             "ending", "delivery", "bytes", "sha256_16")}
        else:
            item["ok"] = False
            item["error"] = r.get("error", "无法解析")
        rows.append(item)
    return rows


def _backup_source(path: str) -> str:
    p = Path(path)
    if p.name.endswith("-Recent.txt"):
        return "游戏自动"
    if p.parent.name == "Backup":
        return "写入前"
    return "工作区"


# ------------------------------------------------------------------ 动作
# ---------------------------------------------------------------- 难度（可选）
# 存档里并不写自己的难度，只能看「已登记人数」落在哪些档位的可达链上；
# 游戏当前的档位则要从 Assembly-CSharp.dll 里读。这两套工具都在仓库的
# hardcore/ 与 patcher/ 里，这边只做胶水，而且**懒导入**：
# 万一这两块不在（别人只拿了存档工具），程序照常能用，只是不做难度提醒。
def _difficulty_tools():
    """返回 (patcher.core, hardcore.align_save)，拿不到就给 (None, None)。"""
    try:
        from hardcore import align_save as al          # noqa: PLC0415
        from patcher import core as pc                  # noqa: PLC0415
        return pc, al
    except Exception:                                   # noqa: BLE001
        return None, None


def difficulty_state(path: Path | None = None) -> dict:
    """游戏安装目录 / 当前档位 / 这份存档能不能通关。"""
    pc, al = _difficulty_tools()
    if pc is None:
        return {"available": False, "why": "找不到难度工具（patcher / hardcore）"}
    game = pc.find_game()
    out: dict = {"available": True,
                 "installDir": str(game) if game else None,
                 "installFound": game is not None,
                 "level": None, "levelName": None, "levels": [],
                 "compatible": None, "compatibleLevels": [], "report": ""}
    if game is not None:
        try:
            info = pc.probe_dll(pc.managed_dll(game))
            out["level"] = info.get("level")
            out["levelName"] = pc.LEVEL_NAMES.get(info.get("level"))
            out["dllKind"] = info.get("kind")
        except Exception as e:                          # noqa: BLE001
            out["why"] = "读 DLL 失败：%s: %s" % (type(e).__name__, e)
    if out["level"] is None:
        out.setdefault("why", "认不出游戏当前档位")
        return out
    out["levels"] = [{"level": k, "name": v}
                     for k, v in sorted(pc.LEVEL_NAMES.items())]
    if path is None:
        return out
    try:
        _text, xml = al.load_save(path)
        _crew, ship, office = al.build_zones()
        lv_ok = al.compatible_levels(xml)
        out["compatibleLevels"] = sorted(lv_ok)
        out["compatible"] = out["level"] in lv_ok
        out["report"] = "船上已登记 %d 人，办公室已登记 %d 人" % (
            al.zone_marked(xml, ship), al.zone_marked(xml, office))
    except Exception as e:                              # noqa: BLE001
        out["why"] = "读存档失败：%s: %s" % (type(e).__name__, e)
    return out


def act_align(path: Path) -> dict:
    """把这份存档对齐到游戏当前档位（对齐前会先备份）。"""
    pc, _al = _difficulty_tools()
    if pc is None:
        raise ApiError("找不到难度工具")
    st = difficulty_state(path)
    if not st.get("level"):
        raise ApiError(st.get("why") or "认不出游戏当前档位")
    if is_preset(path):
        raise ApiError("这是随程序发的预设，不能就地修改（先导出/导入一份再改）")
    ok, detail, extra = pc.align_save_file(path, st["level"])
    return {"ok": ok, "message": detail, "level": st["level"],
            "levelName": st["levelName"], **extra}


def pick_folder(prompt: str) -> tuple[str, str]:
    """弹系统原生的「选择文件夹」。返回 (路径, 错误)；用户取消 = ("", "")。

    不用 tk：这里是 HTTP 工作线程。提示语只能 ASCII —— PowerShell 5.1
    按 ANSI 读命令行，中文会乱。
    """
    import subprocess
    try:
        if sys.platform == "win32":
            ps = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                  f"$d.Description = '{prompt}';"
                  "$d.ShowNewFolderButton = $false;"
                  "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
                  " { [Console]::Out.Write($d.SelectedPath) }")
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                               capture_output=True, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif sys.platform == "darwin":
            r = subprocess.run(["osascript", "-e",
                                f'POSIX path of (choose folder with prompt "{prompt}")'],
                               capture_output=True, text=True)
        else:
            return "", "这个系统还没有文件夹选择器，请把路径手动填进来"
    except OSError as e:
        return "", f"打不开选择器：{e}"
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        return ("", "") if "ancel" in err else ("", err[:200] or "选择器出错")
    return (r.stdout or "").strip(), ""


def act_game_dir(raw: str, detect: bool = False) -> dict:
    """设置游戏安装目录（读难度需要它）；detect=true 时重新自动探测。"""
    pc, _al = _difficulty_tools()
    if pc is None:
        raise ApiError("找不到难度工具")
    if detect:                       # 自动探测：find_game() 会扫常见安装位置
        found = pc.find_game()
        if found is None:
            raise ApiError("自动没找到游戏，请用「选择…」手动指定")
        res = pc.set_game_dir(str(found))
        if not res.get("ok"):
            raise ApiError(res.get("error") or "自动找到的目录用不了")
        return {"installDir": res["game"],
                "message": "自动找到并记住了：%s" % res["game"]}
    if not raw.strip():
        raise ApiError("没有填路径")
    res = pc.set_game_dir(raw.strip())   # 内部会 resolve（容忍 exe、.app、引号等）
    if not res.get("ok"):
        # core 里那段说明是按 markdown 写的（给窗式界面用），这里是纯文本提示，
        # 把 ** 去掉，不然玩家会看到字面的星号。
        raise ApiError((res.get("error") or "这个目录不像是游戏目录").replace("**", ""))
    return {"installDir": res["game"],
            "message": "已记住游戏目录：%s" % res["game"]}


def safe_maker_name(raw: str) -> str:
    """制作器传上来的文件名：只允许字母/数字（含汉字）/点/下划线/短横，且限 .txt。"""
    n = Path((raw or "").strip()).name
    if not n.lower().endswith(".txt"):
        n += ".txt"
    stem = n[:-4]
    if not stem or len(n) > 96:
        raise ApiError("文件名太长或者空了")
    for ch in stem:
        if not (ch.isalnum() or ch in "._-"):      # 汉字 isalnum() 为真，/ \ : 为假
            raise ApiError("文件名里不能有「%s」" % ch)
    return n


def act_maker_export(b: dict) -> dict:
    """把「存档制作器」搭出来的存档收进存档库。

    落盘前先自己解一遍（load_checked），解不开就不留下——别让制作器
    的半成品脏了玩家的存档库。写盘编码跟 save_save() 保持一致。
    """
    text = b.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError("存档内容是空的")
    name = safe_maker_name(str(b.get("name") or ""))
    lib = library_dir()
    lib.mkdir(parents=True, exist_ok=True)
    dst = lib / name
    if dst.exists():
        raise ApiError("存档库里已经有同名文件：%s" % name)
    try:
        with open(dst, "w", encoding="iso-8859-1", newline="") as f:
            f.write(text)
    except (OSError, UnicodeEncodeError) as e:
        raise ApiError("写文件失败：%s" % e) from e
    try:
        load_checked(dst)
    except Exception as e:                              # noqa: BLE001
        try:
            dst.unlink()
        except OSError:
            pass
        raise ApiError("这份存档解不开：%s" % e) from e
    return {"name": name, "bytes": dst.stat().st_size,
            "message": "已导出到存档库：%s" % name}


def act_gender(path: Path, gender: str) -> dict:
    if is_preset(path):
        raise ApiError("预制存档是只读的，换性别请先「装到 P1/P2/P3」")
    if gender not in ("male", "female", "toggle"):
        raise ApiError("gender 只能是 male / female / toggle")
    container, xml = load_checked(path)
    cur = get_gender(xml)
    want = (cur != "female") if gender == "toggle" else (gender == "female")
    if want == (cur == "female"):
        return {"changed": False, "gender": cur, "backups": []}
    backups = _backup_for(path, "gender")
    xml = set_gender(xml, want)
    save_save(container, xml, path)
    _, back = load_checked(path)
    new = get_gender(back)
    if new != ("female" if want else "male"):
        raise ApiError("写入后回读校验失败，请用备份恢复")
    return {"changed": True, "gender": new, "backups": backups}


def act_import(slot: str, path: Path) -> dict:
    from save_tool import import_save
    r = import_save(path, slot, workspace=library_dir())
    return {"dst": r["dst"], "backups": r["backups"],
            "bytes": r["bytes"], "sha256_16": r["sha256_16"]}


def act_export(path: Path, name: str | None) -> dict:
    load_checked(path)                                  # 先证明源可用
    lib = library_dir()
    name = (name or path.name).strip() or path.name
    if not name.endswith(".txt"):
        name += ".txt"
    name = "".join(c for c in name if c not in '<>:"/\\|?*')
    dst = lib / name
    if dst.exists():
        stem, ext = dst.stem, dst.suffix
        dst = lib / f"{stem}-{datetime.now().strftime('%H%M%S')}{ext}"
    dst.write_bytes(path.read_bytes())
    if sha256(path) != sha256(dst):
        raise ApiError("导出后哈希不一致")
    return {"dst": str(dst), "bytes": dst.stat().st_size, "sha256_16": sha256(dst)[:16]}


def act_delete(path: Path) -> dict:
    lib = library_dir().resolve()
    p = path.resolve()
    if p.parent != lib:
        raise ApiError("只能删除存档库里的文件")
    trash = lib / "_trash"
    trash.mkdir(exist_ok=True)
    dst = trash / f"{p.stem}-{datetime.now().strftime('%Y%m%d%H%M%S')}{p.suffix}"
    p.replace(dst)
    return {"moved_to": str(dst)}


def _backup_for(path: Path, tag: str) -> list[str]:
    """就地改写前的备份：槽位进游戏 Backup\\ + 库内 _backups；库文件进 _backups"""
    from save_tool import backup_dir
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    made = []
    gd = game_dir()
    try:
        path.relative_to(gd.resolve())
        is_slot = True
    except ValueError:
        is_slot = False
    targets = [path.parent / "Backup"] if is_slot else []
    targets.append(backup_dir(library_dir()))
    for d in targets:
        d.mkdir(parents=True, exist_ok=True)
        dst = d / f"{path.stem}-before{tag}-{ts}{path.suffix}"
        dst.write_bytes(path.read_bytes())
        made.append(str(dst))
    return made


# ------------------------------------------------------------------ HTTP
def _html() -> str:
    """开发模式下每次重新读 gui/web.py，改样式刷新即生效"""
    if not DEV_RELOAD:
        return INDEX_HTML
    import importlib
    from gui import web as web_mod
    importlib.reload(web_mod)
    return web_mod.INDEX_HTML


class Handler(BaseHTTPRequestHandler):
    server_version = f"{APP_NAME}/{APP_VERSION}"
    protocol_version = "HTTP/1.1"

    # ---------- 工具
    def log_message(self, fmt, *args):                  # 静音，避免刷屏
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        hdrs = {"Cache-Control": "no-store"}
        hdrs.update(extra or {})
        for k, v in hdrs.items():
            self.send_header(k, v)
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, msg: str, code: int = 400):
        self._json({"ok": False, "error": msg}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:                               # noqa: BLE001
            return {}

    # ---------- GET
    def do_GET(self):                                   # noqa: N802
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                self._send(200, _html().encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            elif u.path == "/maker":
                # 存档制作器（deck_state.py 生成的页面）。前端拿 ?embed=1 打开：
                # 藏右栏、无滚动条、只从空白档起步，改完 POST /api/maker-export。
                p = resource_dir() / "deck-state.html"
                if not p.is_file():
                    raise ApiError("找不到 deck-state.html，先跑 python deck_state.py", 404)
                self._send(200, p.read_bytes(), "text/html; charset=utf-8",
                           {"Cache-Control": "no-store"})
            elif u.path.startswith("/fonts/"):
                p = font_file(u.path[len("/fonts/"):])
                ctype = "font/ttf" if p.suffix.lower() == ".ttf" else "font/otf"
                # 不缓存：字体是本地文件，代价为零；留缓存的话重裁子集后
                # 浏览器还会接着用旧的那份，字形「悄悄回落」根本看不出来。
                self._send(200, p.read_bytes(), ctype,
                           {"Cache-Control": "no-store"})
            elif u.path == "/api/state":
                gd, lib = game_dir(), library_dir()
                self._json({"ok": True,
                            "app": {"name": APP_NAME, "version": APP_VERSION},
                            "platform": platform.platform(),
                            "python": sys.version.split()[0],
                            "saveDir": str(gd), "saveDirExists": gd.exists(),
                            "libraryDir": str(lib),
                            "slots": slots_state(),
                            "presets": presets_state(),
                            "library": library_state(),
                            "difficulty": difficulty_state()})
            elif u.path == "/api/difficulty":
                raw = (q.get("path") or [""])[0]
                self._json({"ok": True,
                            **difficulty_state(safe_path(raw) if raw else None)})
            elif u.path == "/api/backups":
                slot = (q.get("slot") or [""])[0].upper()
                if slot not in SLOTS:
                    return self._err("slot 必须是 P1/P2/P3")
                self._json({"ok": True, "slot": slot, "backups": backups_state(slot)})
            elif u.path == "/api/download":
                p = safe_path((q.get("path") or [""])[0])
                if not p.exists():
                    return self._err("文件不存在", 404)
                ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                self._send(200, p.read_bytes(), ctype,
                           {"Content-Disposition": f'attachment; filename="{p.name}"'})
            else:
                self._err("未知路径", 404)
        except ApiError as e:
            self._err(str(e))
        except Exception as e:                          # noqa: BLE001
            traceback.print_exc()
            self._err(f"内部错误: {e}", 500)

    # ---------- HEAD（复用 GET，仅不发 body）
    def do_HEAD(self):                                  # noqa: N802
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    # ---------- POST
    def do_POST(self):                                  # noqa: N802
        u = urllib.parse.urlparse(self.path)
        try:
            b = self._body()
            if u.path == "/api/gender":
                r = act_gender(safe_path(b.get("path")), b.get("gender", "toggle"))
                return self._json({"ok": True, **r})
            if u.path == "/api/align":
                return self._json({"ok": True, **act_align(safe_path(b.get("path")))})
            if u.path == "/api/game-dir":
                return self._json({"ok": True, **act_game_dir(str(b.get("path") or ""),
                                                             bool(b.get("detect")))})
            if u.path == "/api/pick-dir":
                got, err = pick_folder("Select the Obra Dinn game folder")
                if not got:
                    raise ApiError(err or "已取消")
                return self._json({"ok": True, "path": got})
            if u.path == "/api/maker-export":
                return self._json({"ok": True, **act_maker_export(b)})
            if u.path == "/api/import":
                slot = str(b.get("slot", "")).upper()
                if slot not in SLOTS:
                    return self._err("slot 必须是 P1/P2/P3")
                r = act_import(slot, safe_path(b.get("path")))
                return self._json({"ok": True, **r})
            if u.path == "/api/export":
                r = act_export(safe_path(b.get("path")), b.get("name"))
                return self._json({"ok": True, **r})
            if u.path == "/api/delete":
                r = act_delete(safe_path(b.get("path")))
                return self._json({"ok": True, **r})
            if u.path == "/api/quit":
                # 打包成 --windowed 后没有控制台，Ctrl+C 用不了，
                # 所以必须有个正经的退出入口（否则只能靠任务管理器）
                if not same_origin(self.headers.get("Origin"),
                                   self.server.server_address[1]):
                    return self._err("不允许跨站调用", 403)
                self._json({"ok": True})
                print("[i] 收到退出请求，服务即将关闭")
                threading.Timer(0.4, self.server.shutdown).start()
                return
            if u.path == "/api/upload":
                name = "".join(c for c in str(b.get("name", "upload.txt"))
                               if c not in '<>:"/\\|?*') or "upload.txt"
                if not name.endswith(".txt"):
                    name += ".txt"
                data = b.get("data")
                if not isinstance(data, str) or not data:
                    return self._err("缺少 data（base64）")
                import base64
                raw = base64.b64decode(data)
                tmp = library_dir() / f".upload-{datetime.now().strftime('%H%M%S%f')}.txt"
                tmp.write_bytes(raw)
                try:
                    load_checked(tmp)                   # 先验证是不是有效存档
                except Exception:                       # noqa: BLE001
                    tmp.unlink(missing_ok=True)
                    return self._err("这个文件不是有效的 Obra Dinn 存档")
                dst = library_dir() / name
                if dst.exists():
                    dst = library_dir() / f"{Path(name).stem}-{datetime.now().strftime('%H%M%S')}.txt"
                tmp.replace(dst)
                return self._json({"ok": True, "dst": str(dst),
                                   "bytes": dst.stat().st_size})
            return self._err("未知路径", 404)
        except ApiError as e:
            self._err(str(e))
        except Exception as e:                          # noqa: BLE001
            traceback.print_exc()
            self._err(f"内部错误: {e}", 500)


# ------------------------------------------------------------------ 启动
DEFAULT_PORT = 8722

# 能用 `--app=<url>` 开无地址栏窗口的浏览器（Chromium 系都支持）
CHROMIUM_EXES = ("chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe",
                 "chromium.exe", "google-chrome", "chromium",
                 "chromium-browser", "microsoft-edge")


def _default_browser_exe() -> Path | None:
    """Windows：从注册表读出默认浏览器的可执行文件"""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations"
            r"\UrlAssociations\http\UserChoice",
        ) as k:
            progid = winreg.QueryValueEx(k, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            rf"{progid}\shell\open\command") as k:
            raw = winreg.QueryValueEx(k, "")[0].strip()
    except OSError:
        return None
    exe = raw[1:raw.find('"', 1)] if raw.startswith('"') else raw.split(" ")[0]
    p = Path(exe)
    return p if p.exists() else None


def _chromium_candidates() -> list[Path]:
    """已知的 Chromium 系安装位置（默认浏览器不是 Chromium 时的備选）"""
    out: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        for sub, roots in (
            (r"Google\Chrome\Application\chrome.exe", (local, pf, pf86)),
            (r"Microsoft\Edge\Application\msedge.exe", (pf86, pf)),
            (r"BraveSoftware\Brave-Browser\Application\brave.exe", (pf, local)),
        ):
            for root in roots:
                if root and (root / sub).exists():
                    out.append(Path(root) / sub)
    elif sys.platform == "darwin":
        for sub in ("Google Chrome", "Microsoft Edge", "Brave Browser"):
            p = Path(f"/Applications/{sub}.app/Contents/MacOS/{sub}")
            if p.exists():
                out.append(p)
    else:
        for name in ("google-chrome", "chromium", "chromium-browser",
                     "microsoft-edge", "brave-browser"):
            w = shutil.which(name)
            if w:
                out.append(Path(w))
    return out


def screen_bounds() -> tuple[int, int, int, int] | None:
    """主屏 bounds (x, y, w, h)；拿不到就返回 None

    Windows：SPI_GETWORKAREA，已扣掉任务栏。
    macOS：CoreGraphics 的 CGDisplayBounds —— **不需要任何权限**，
          比问 Finder（`bounds of window of desktop`）少一次「自动化」授权弹窗。

    ⚠️ 非 DPI 感知进程在 Windows 上拿到的是**缩放后的逻辑像素**，
    而这正好是 Chromium `--window-size` 想要的单位（DIP）。
    """
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            SPI_GETWORKAREA = 0x0030
            rect = wintypes.RECT()
            if not ctypes.windll.user32.SystemParametersInfoW(
                    SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                return None
            return (rect.left, rect.top,
                    rect.right - rect.left, rect.bottom - rect.top)
        except Exception:                               # noqa: BLE001
            return None
    if sys.platform == "darwin":
        try:
            import ctypes
            import ctypes.util

            class _Point(ctypes.Structure):
                _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

            class _Size(ctypes.Structure):
                _fields_ = [("w", ctypes.c_double), ("h", ctypes.c_double)]

            class _Rect(ctypes.Structure):
                _fields_ = [("origin", _Point), ("size", _Size)]

            cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
            cg.CGMainDisplayID.restype = ctypes.c_uint32
            cg.CGDisplayBounds.restype = _Rect
            cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
            r = cg.CGDisplayBounds(cg.CGMainDisplayID())
            return (int(r.origin.x), int(r.origin.y),
                    int(r.size.w), int(r.size.h))
        except Exception:                               # noqa: BLE001
            return None
    return None


def _mac_app_name(exe: str) -> str | None:
    """从 `/Applications/X.app/Contents/MacOS/X` 反推 AppleScript 要用的应用名"""
    for p in Path(exe).resolve().parents:
        if p.suffix == ".app":
            return p.stem
    return None


def _maximize_win(title: str, timeout: float) -> bool:
    """Windows：找到窗口句柄 → ShowWindow(SW_MAXIMIZE)"""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.FindWindowW.restype = wintypes.HWND
        SW_MAXIMIZE = 3
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hwnd = u.FindWindowW(None, title)
            if hwnd:
                u.ShowWindow(hwnd, SW_MAXIMIZE)
                return True
            time.sleep(0.3)
    except Exception as e:                              # noqa: BLE001
        print(f"[!] 最大化窗口失败：{e}")
    return False


def _maximize_mac(browser_exe: str, timeout: float = 10.0) -> bool:
    """macOS：让浏览器把自己的 front window 撑到屏幕大小

    实测：AppleScript 直接命令浏览器（而不是 System Events 的 UI scripting），
    所以只需要「自动化」权限、不需要「辅助功能」权限；
    Chromium 会自己把 bounds 夹到菜单栏/程序坞以内
    （实测请求 0,0,2143,1200 → 实际 0,31,2143,1110）✓

    权限被拒（-1743）或拿不到尺寸时直接返回 False，不影响使用。
    """
    app = _mac_app_name(browser_exe)
    if not app:
        return False
    rect = screen_bounds()
    if rect:
        x, y, w, h = rect
        script = (f'tell application "{app}" to set bounds of front window '
                  f'to {{{x}, {y}, {x + w}, {y + h}}}')
    else:
        script = ('tell application "Finder" to set r to bounds of window of desktop\n'
                  f'tell application "{app}" to set bounds of front window to r')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=25)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"[!] AppleScript 执行不了：{e}")
            return False
        if r.returncode == 0:
            return True
        lines = (r.stderr or "").strip().splitlines()
        msg = lines[0] if lines else f"rc={r.returncode}"
        # 窗口还没出来（-1728/-1719/-1708）就再等等；其他错误（权限 -1743）直接放弃
        if any(code in msg for code in ("-1728", "-1719", "-1708")):
            time.sleep(0.5)
            continue
        print(f"[!] 最大化窗口失败：{msg}")
        return False
    return False


def maximize_window(title: str, browser_exe: str = "",
                    timeout: float = 8.0) -> bool:
    """让 app 窗口铺满屏幕；成功与否都不影响启动

    ⚠️ 为什么不能只靠命令行：`--start-maximized` / `--window-size` 都是
    **浏览器启动期**标志。浏览器已经在跑时新窗口由既有进程创建，这些标志
    会被直接丢掉 —— Windows 实测不管加哪个都是 838x892、IsZoomed=False。
    所以只能**事后**去调窗口。
    """
    if sys.platform == "win32":
        return _maximize_win(title, timeout)
    if sys.platform == "darwin":
        return _maximize_mac(browser_exe, timeout)
    return False


def app_mode_cmd(url: str) -> list[str] | None:
    """找出能用 `--app=` 开无地址栏窗口的命令；找不到就返回 None

    先看用户自己的默认浏览器（尊重他们的选择），不是 Chromium 系才退到
    Chrome / Edge。都不是就交给调用方退到普通标签页。

    ⚠️ **`--start-maximized` 对 `--app` 窗口无效**（实测 Edge 仍开 838x892、
    `IsZoomed=False`），所以直接给 `--window-size` + `--window-position`，
    让它一开就铺满主屏工作区；浏览器已经在跑时这两个标志也会被丢，
    再由 `maximize_window()` 事后补一刀。
    """
    exe = _default_browser_exe()
    if exe is None or exe.name.lower() not in CHROMIUM_EXES:
        cands = _chromium_candidates()
        exe = cands[0] if cands else None
    if exe is None:
        return None
    cmd = [str(exe), f"--app={url}"]
    area = screen_bounds()
    if area:
        x, y, w, h = area
        cmd += [f"--window-size={w},{h}", f"--window-position={x},{y}"]
    else:
        cmd.append("--start-maximized")                # 非 Windows：尽人事
    return cmd


def page_title() -> str:
    """从页面里取 <title>：app 窗口的标题栏文本就是它，可以拿来定位窗口"""
    m = re.search(r"<title>(.*?)</title>", INDEX_HTML, re.S)
    return m.group(1).strip() if m else APP_NAME


def _spawn_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}            # CREATE_NO_WINDOW
    return {"start_new_session": True}


def open_window(url: str, app_mode: bool = True) -> str:
    """打开界面：优先无地址栏的 app 窗口，否则退到普通标签页；返回用了哪种"""
    if app_mode:
        cmd = app_mode_cmd(url)
        if cmd:
            try:
                subprocess.Popen(cmd, **_spawn_kwargs())
                # 既有的浏览器进程会忽略启动期标志，所以事后补一刀
                maximized = maximize_window(page_title(), cmd[0])
                return (f"app 窗口（{Path(cmd[0]).name}）"
                        + ("，已最大化" if maximized else ""))
            except OSError as e:                        # noqa: BLE001
                print(f"[!] app 模式启动失败（{e}），改用普通标签页")
    try:
        return "普通标签页" if webbrowser.open(url) else "普通标签页（未确认）"
    except Exception as e:                              # noqa: BLE001
        return f"打开失败：{e}"


def instance_alive(port: int) -> bool:
    """那个端口上是不是已经跑着我们的一个实例

    app 窗口关掉 ≠ 程序退出（浏览器拦不住），所以再启动时应该直接把窗口叫回来，
    而不是又起一个服务。
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state",
                                    timeout=1.5) as r:
            return r.headers.get("Server", "").startswith(APP_NAME)
    except Exception:                                   # noqa: BLE001
        return False


def free_port(preferred: int = DEFAULT_PORT) -> int:
    for port in [preferred, 0]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("找不到可用端口")


def serve(port: int | None = None, open_browser: bool = True,
          app_mode: bool = True) -> None:
    if port is None and open_browser and instance_alive(DEFAULT_PORT):
        url = f"http://127.0.0.1:{DEFAULT_PORT}/"
        print(f"[i] {DEFAULT_PORT} 端口已有实例在跑，只把窗口叫回来")
        print(f"[i] {open_window(url, app_mode)}")
        return
    port = port or free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"[i] {APP_NAME} {APP_VERSION}")
    print(f"[i] 游戏存档目录: {game_dir()}")
    print(f"[i] 存档库:       {library_dir()}")
    print(f"[i] 字体目录:     {font_dir()}")
    if not font_dir().is_dir():
        print("[!] 找不到字体目录，页面会回退到系统字体")
    if DEV_RELOAD:
        print("[i] 开发模式：改 gui/web.py 后刷新浏览器即生效")
    print(f"[i] 已在 {url} 启动")
    print("[i] 退出：窗口里的「退出程序」（打包后没有控制台，Ctrl+C 用不了）")
    if open_browser:
        threading.Timer(0.6, lambda: print(f"[i] 已打开: {open_window(url, app_mode)}")
                        ).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[i] 已退出")
    finally:
        print("[i] 服务已停止")
        httpd.server_close()

if __name__ == "__main__":
    serve()
