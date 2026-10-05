#!/usr/bin/env python3
"""难度补丁核心引擎（玩家侧与开发侧共用）。

职责
----
    定位游戏  ->  读状态  ->  换档（还原 + 打 DLL + 装语言包 + 对齐存档）  ->  还原

设计约定（细节见 hardcore/DESIGN.md / PATCH-SPEC.md）
--------------------------------------------------
* **换档 = 先还原再打新配方**，从不叠加。
* 首次打补丁时，把原始 DLL 与 14 个语言包备份到用户数据目录；之后都从备份还原。
* 只认已验证的游戏版本：DLL 与语言包都用 sha256 和预编译产物比对，
  既能精确判档，也顺带确认「装上去的就是我们验证过的那些字节」。
* 对齐存档只改 `markedCorrect`，不动玩家填的下落（nameId / fateId）。

命令行（调试用）
--------------
    python -m patcher.core state           # 打印当前状态 JSON
    python -m patcher.core levels          # 列出档位
    python -m patcher.core probe <dll>     # 探单个 DLL
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PATCHER_DIR = Path(__file__).resolve().parent
REPO = PATCHER_DIR.parent
# 打包后 PyInstaller 把模块和数据放在 sys._MEIPASS 下；hardcore/ 里那几个
# 模块是按顶层名字互相 import 的，所以那个目录也必须在 sys.path 上。
for _p in (str(REPO), getattr(sys, "_MEIPASS", None)):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

from patcher import langpatch_tool as lpt                  # noqa: E402

APP_NAME = "ObraDinnDifficultyPatcher"


def _utf8_stdout() -> None:
    """控制台默认 GBK，印中文/阿拉伯语会直接抛异常（langtool 那边同一个毛病）。"""
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_utf8_stdout()

# --------------------------------------------------------------------------
# 档位表
# --------------------------------------------------------------------------
LEVEL_NAMES = {
    3: "简单（原版）",
    4: "容易",
    6: "中等",
    9: "偏高",
    14: "较难",
    29: "困难",
    58: "硬核",
}
#: 原版档位（= 3 人一批），不需要打补丁，只需要还原
VANILLA = 3
#: 需要预编译产物的档位
PATCH_LEVELS: tuple[int, ...] = (4, 6, 9, 14, 29, 58)

#: 原版 Assembly-CSharp.dll 的哈希（用于确认没被别的 mod 改过）
VANILLA_DLL_SHA256 = (
    "4ce056de4339ceef70c6674289d4edb26add0483f1fc03a89a15609170a1c5e6")

DLL_NAME = "Assembly-CSharp.dll"
#: 开发期存的那份 mac 官方原版（与 Windows 那份是不同 build）
MAC_ORIG_NAME = "Assembly-CSharp-mac.dll.orig"
#: 数据目录的名字。Windows 是 `ObraDinn_Data`；mac 的 .app 里是 `Contents/Resources/Data`
GAME_SUBPATH = Path("ObraDinn_Data")
DATA_SUBPATHS = ("ObraDinn_Data", "Data")
#: mac 的 .app 把数据藏在下面几层（玩家可能填到 .app、Contents 或 Contents/Resources）
MAC_TAILS = (Path("Contents") / "Resources", Path("Resources"), Path("Contents"))
MANAGED_REL = GAME_SUBPATH / "Managed" / DLL_NAME
SA_REL = GAME_SUBPATH / "StreamingAssets"

#: A 处常量锚点（PATCH-SPEC.md）：`stloc.s V_7` 之后紧跟这段
CONST_ANCHOR = bytes.fromhex("11061a3b0800000011061840")

#: C 处（总时长恒定）的封印签名，token 通配
_TOK = rb"[\x00-\xff]{4}"
SEAL_VANILLA_RE = re.compile(rb"\x73" + _TOK + rb"\x22\x9a\x99\x99\x3f\x14\x28")
SEAL_PATCHED_RE = re.compile(
    rb"\x73" + _TOK + rb"\x22\x9a\x99\x19\x40\x03\x6f" + _TOK + rb"\x17\x59\x6b\x5b\x14\x28")

#: B2 处（音效索引取模）：`ldarg.0; ldloc.2; ldloc.1; ldelem.ref`
B2_VANILLA = b"\x02\x08\x07\x9a"
B2_PATCHED = b"\x02\x08\x07\x19\x5d\x9a"

#: B1 处：分支的目标必须是 `ldc.i4.3; newarr`（即「建 3 元素数组」那一处）。
#: 同方法里另有两处 ldc.i4.2 + 分支也紧跟在 get_Count 后面，只靠 get_Count 会
#: 撞上错的那一处 —— 对**已打过补丁**的 DLL 实测撞到过 IL_00F2。
_B1_ARR = b"\x19\x8d"


def _looks_vanilla(path: Path) -> bool:
    """看上去是没打过补丁的原版。只看**形状**，不比哈希 —— 哈希随 build 变。"""
    if not path.is_file():
        return False
    buf = path.read_bytes()
    val, _, _ = _const_value(buf)
    return (bool(SEAL_VANILLA_RE.search(buf))
            and not SEAL_PATCHED_RE.search(buf) and val == VANILLA)


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
def app_root() -> Path:
    """程序所在目录 —— 打包后是 PyInstaller 解出来的那个内部目录。

    资源是用 `--add-data patcher/assets;patcher/assets` 塞进去的，
    PyInstaller 会把它们放在 `sys._MEIPASS` 下，所以冻结时必须看那里，
    不然打包后就会找不到 DLL / langtool.exe / 字体。
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return Path(base)
        return Path(sys.executable).resolve().parent
    return REPO


def _resolved(env: str, *candidates: Path) -> Path:
    raw = os.environ.get(env)
    if raw:
        p = Path(raw).expanduser()
        if p.is_dir():
            return p
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def lang_dir() -> Path:
    """预编译的语言包：<级别>/lang-<code>"""
    return _resolved("OBRADINN_PATCH_LANGS",
                     app_root() / "patcher" / "assets" / "lang",
                     REPO / "hardcore" / "_lang" / "out")


def data_dir() -> Path:
    """用户数据目录（备份 + 日志）。"""
    raw = os.environ.get("OBRADINN_PATCH_DATA")
    if raw:
        p = Path(raw).expanduser()
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        p = Path(base) / APP_NAME
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def fingerprint_file() -> Path:
    return PATCHER_DIR / "data" / "lang_fingerprints.json"


# --------------------------------------------------------------------------
# 玩家设置（主要是手动指定的游戏目录 —— 破解版/非 Steam 安装都靠它）
# --------------------------------------------------------------------------
SETTINGS_NAME = "settings.json"


def settings_path() -> Path:
    return data_dir() / SETTINGS_NAME


def load_settings() -> dict:
    p = settings_path()
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(d: dict) -> None:
    settings_path().write_text(json.dumps(d, ensure_ascii=False, indent=1),
                               encoding="utf-8")


def data_dir_in(root: Path) -> Path | None:
    """在 root 里找游戏的数据目录（Windows 的 `ObraDinn_Data`，mac 的 `Data`）。

    mac 的 .app 把它藏在 `Contents/Resources/Data`，所以一并往下探。
    """
    for base in (root, *(root / t for t in MAC_TAILS)):
        for name in DATA_SUBPATHS:
            p = base / name
            if (p / "Managed" / DLL_NAME).is_file():
                return p
    return None


def looks_like_game(p: Path) -> bool:
    """这个目录像不像游戏根目录（Windows 含 ObraDinn_Data；mac 含 …/Resources/Data）。"""
    return data_dir_in(p) is not None


def data_dir_of(game: Path) -> Path:
    d = data_dir_in(game)
    return d if d is not None else (game / GAME_SUBPATH)


def resolve_game_dir(raw: str) -> tuple[Path | None, str]:
    """把玩家输入的路径归一成游戏根目录。返回 (目录, 不行的原因)。

    容忍几种常见输入：
      * 直接是根目录
      * 指向 ObraDinn.exe（多数人拖的就是它）
      * 带引号、带尾部斜杠、带空格
      * 是 mac 的 Return of the Obra Dinn.app / …/Contents/Resources
    """
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        return None, "没有填写路径"
    p = Path(s).expanduser()

    if p.is_file():
        if p.name.lower() == "obradinn.exe":
            p = p.parent
        else:
            p = p.parent
    for cand in (p, p.parent,
                 p / "Return of the Obra Dinn.app" / "Contents" / "Resources",
                 p / "ObraDinn.app" / "Contents" / "Resources"):
        if looks_like_game(cand):
            return cand, ""
    return None, ("这个目录里找不到游戏的数据文件夹"
                  "（Windows 是 ObraDinn_Data，mac 的 .app 里是 Contents/Resources/Data）。\n"
                  "Windows 请选 **ObraDinn.exe 所在的目录**，例如 …\\common\\ObraDinn；\n"
                  "mac 请选 **Return of the Obra Dinn.app 所在的目录**。")


def set_game_dir(raw: str) -> dict:
    """记住玩家手动指定的游戏目录。"""
    p, why = resolve_game_dir(raw)
    if p is None:
        return {"ok": False, "error": why}
    s = load_settings()
    s["game_dir"] = str(p)
    try:
        save_settings(s)
    except OSError as e:
        return {"ok": False, "error": "保存设置失败：%s" % e}
    return {"ok": True, "game": str(p), "state": state()}


# --------------------------------------------------------------------------
# 定位游戏
# --------------------------------------------------------------------------
STEAM_ROOTS_WIN = (
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"D:\Steam",
    r"E:\Steam",
)
STEAM_ROOTS_MAC = (
    "~/Library/Application Support/Steam",
)


def _library_folders(steam_root: Path) -> list[Path]:
    """从 libraryfolders.vdf 里挖出所有库目录（正则版，够用且不引入依赖）。"""
    out: list[Path] = []
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if not vdf.is_file():
        return out
    try:
        txt = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
        p = Path(m.group(1).replace("\\\\", "\\"))
        out.append(p)
    return out


def candidate_games() -> list[Path]:
    """所有可能含 ObraDinn 的路径（按可信度排序）。"""
    found: list[Path] = []

    raw = os.environ.get("OBRADINN_GAME")
    if raw:
        found.append(Path(raw).expanduser())

    if sys.platform == "darwin":
        # 非 Steam 安装（GOG / itch / 直接拖进 Applications）很常见，
        # 实测这台机器就是 /Applications/Return of the Obra Dinn.app
        for base in (Path("/Applications"), Path.home() / "Applications"):
            for name in ("Return of the Obra Dinn.app", "ObraDinn.app"):
                found.append(base / name)

    roots = STEAM_ROOTS_WIN if sys.platform == "win32" else STEAM_ROOTS_MAC
    steam_roots = [Path(r) for r in roots]
    # 从常见盘符补一批 Steam 根目录
    if sys.platform == "win32":
        for drive in "CDEFGH":
            steam_roots += [Path(f"{drive}:\\Steam"),
                            Path(f"{drive}:\\SteamLibrary"),
                            Path(f"{drive}:\\Program Files (x86)\\Steam")]

    libs: list[Path] = []
    for sr in steam_roots:
        if not sr.is_dir():
            continue
        libs.append(sr)
        libs += _library_folders(sr)

    seen: set[Path] = set()
    for lib in libs:
        if lib in seen:
            continue
        seen.add(lib)
        for name in ("ObraDinn", "Return of the Obra Dinn"):
            p = lib / "steamapps" / "common" / name
            found.append(p)
            found.append(p / "Return of the Obra Dinn.app" / "Contents" / "Resources")
    return found


def find_game() -> Path | None:
    """返回游戏根目录（Windows 是含 ObraDinn_Data 的那一层；mac 是 .app）。

    玩家手动指定的优先 —— 破解版、非 Steam 安装、把游戏挪到别处的，都靠它。
    """
    raw = load_settings().get("game_dir")
    if raw:
        p = Path(str(raw)).expanduser()
        if looks_like_game(p):
            return p
    for p in candidate_games():
        if looks_like_game(p):
            return p
    return None


def managed_dll(game: Path) -> Path:
    return data_dir_of(game) / "Managed" / DLL_NAME


def streaming_assets(game: Path) -> Path:
    return data_dir_of(game) / "StreamingAssets"


# --------------------------------------------------------------------------
# 哈希 / 探针
# --------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _const_candidates(buf: bytes) -> tuple[list[int], str]:
    """从 A 处锚点反推写进去的档位常量。

    ⚠ 单看字节会有歧义，必须**按编码长短定优先级**：`ldc.i4.s 29` 是 `1f 1d`，
    而 `1d` 又恰好落在 `ldc.i4.0..8` 的区间里 —— 早期版本两个都收，29 档会
    读出候选 `[7, 29]`（当时靠哈希白名单挑一个才没出事；取消白名单后就露了）。
    现在 `0x1F` 出现在 `end-2` 就直接判为 `ldc.i4.s`，不再重复收短形态。
    """
    pos = buf.find(CONST_ANCHOR)
    if pos < 0:
        return [], "找不到锚点（不是本补丁认识的版本）"
    if buf.find(CONST_ANCHOR, pos + 1) >= 0:
        return [], "锚点不唯一"
    end = pos - 2                      # 锚点前是 `stloc.s V_7`（2 字节）
    if end < 6:
        return [], "锚点位置异常"

    # ① ldc.i4.s <int8>（2 字节）：前缀 0x1F 是决定性的，先判它
    if buf[end - 2] == 0x1F:
        return [int.from_bytes(buf[end - 1:end], "little", signed=True)], ""
    # ② ldc.i4.m1 / ldc.i4.0..8（1 字节）
    if buf[end - 1] == 0x15:
        return [-1], ""
    if 0x16 <= buf[end - 1] <= 0x1E:
        return [buf[end - 1] - 0x16], ""
    # ③ ldc.i4 <int32>（5 字节）—— 我们自己的产物不会用，留着认别的实现
    if buf[end - 5] == 0x20:
        return [int.from_bytes(buf[end - 4:end], "little", signed=True)], ""
    return [], "常量指令不可识别（…%s）" % buf[end - 5:end].hex()


def _const_value(buf: bytes) -> tuple:
    """A 处常量：能唯一读出来就给出值。返回 (值|None, 候选表, 说明)。"""
    cands, why = _const_candidates(buf)
    return (cands[0] if len(cands) == 1 else None), cands, why


def can_patch(buf: bytes) -> tuple:
    """这份 DLL 能不能就地打难度补丁。返回 (能不能, 不行的话为什么)。

    **不看哈希、不看版本号** —— 只看四个站点在不在、形状对不对。
    不同游戏 build 的哈希天然不同，但站点是结构性的，任何 build 都一样。
    """
    n = buf.count(CONST_ANCHOR)
    if n != 1:
        return False, "A 处锚点出现 %d 次（应为 1 次）" % n
    _, cands, why = _const_value(buf)
    if not cands:
        return False, why or "A 处常量读不出来"
    if not (SEAL_VANILLA_RE.search(buf) or SEAL_PATCHED_RE.search(buf)):
        return False, "找不到 C 处（盖章步进）站点"
    if B2_PATCHED not in buf and B2_VANILLA not in buf:
        return False, "找不到 B2 处（音效取模）站点"
    return True, ""


def _b1_branch_op(buf: bytes) -> int | None:
    """找到 B1 站点的那条分支，返回操作码字节（认不出返回 None）。

    站点形状：`callvirt get_Count` -> `ldc.i4.2` -> 分支，
    且该分支的目标是 `ldc.i4.3; newarr`（建 3 元素数组那处）。
    原版是 bne.un（0x40/0x2e），补丁后是 br（0x38/0x2b）。
    """
    for m in re.finditer(rb"\x18([\x2b\x2e\x38\x40])", buf):
        if m.start() < 5 or buf[m.start() - 5] != 0x6f:      # 前面应是 callvirt
            continue
        # ★ bytes 正则的 group() 返回的是 bytes，不是 int ——
        #   直接 `op in (0x38, 0x40)` 永远为假（踩过：判断结果全 False）
        op = m.group(1)[0]
        after = m.end()
        if op in (0x38, 0x40):
            if after + 4 > len(buf):
                continue
            tgt = after + 4 + int.from_bytes(buf[after:after + 4], "little", signed=True)
        else:
            if after + 1 > len(buf):
                continue
            tgt = after + 1 + int.from_bytes(buf[after:after + 1], "little", signed=True)
        if 0 <= tgt < len(buf) - 1 and buf[tgt:tgt + 2] == _B1_ARR:
            return op
    return None


def _b1_patched(buf: bytes) -> bool:
    return _b1_branch_op(buf) in (0x38, 0x2B)


def verify_patched_dll(path: Path, level: int) -> tuple:
    """打出来的 DLL 真的到位了吗 —— 四处逐个验。

    单靠 langtool 的返回码不够：它找不到站点时会「警告并继续」，
    这样会产出一个「只改了一半」的 DLL。
    """
    if not path.is_file():
        return False, "输出文件不存在"
    buf = path.read_bytes()
    _, cands, why = _const_value(buf)
    if level not in cands:
        return False, "A 处常量 = %s（应为 %d）%s" % (
            cands or "读不出", level, why)
    if not SEAL_PATCHED_RE.search(buf):
        return False, "C 处（盖章步进）没改上"
    if B2_PATCHED not in buf:
        return False, "B2 处（音效取模）没改上"
    if not _b1_patched(buf):
        return False, "B1 处（2 元素数组分支）没改上"
    return True, ""


def probe_dll(path: Path) -> dict:
    """探一个 Assembly-CSharp.dll。

    判档**不看哈希白名单**：不同游戏 build 的 DLL 哈希天然不同，
    但 A 处常量、B1 的分支形状、B2 的取模、C 处的盖章签名都是结构性的，
    在任何 build 上都一样 —— 用它们判档才对所有版本通用。
    """
    info: dict = {"path": str(path), "exists": path.is_file()}
    if not info["exists"]:
        info["kind"] = "missing"
        info["detail"] = "文件不存在"
        return info

    info["size"] = path.stat().st_size
    info["sha256"] = sha256_file(path)
    buf = path.read_bytes()

    val, cands, why = _const_value(buf)
    info["const"] = val
    info["const_candidates"] = cands
    info["const_note"] = why
    info["seal_vanilla"] = bool(SEAL_VANILLA_RE.search(buf))
    info["seal_patched"] = bool(SEAL_PATCHED_RE.search(buf))
    info["b2_patched"] = B2_PATCHED in buf
    info["b1_patched"] = _b1_patched(buf)

    if info["seal_patched"]:
        info["kind"] = "patched"
    elif info["seal_vanilla"] and val == VANILLA:
        info["kind"] = "vanilla"
    else:
        info["kind"] = "unknown"
    if info["kind"] == "patched" and not (info["b2_patched"] and info["b1_patched"]):
        info.setdefault("warnings", []).append(
            "C 处是补丁形态，但 B1/B2 没跟上 —— 像是只改了一半")

    info["level"] = (VANILLA if info["kind"] == "vanilla"
                     else val if (info["kind"] == "patched" and val in LEVEL_NAMES)
                     else None)
    info["name"] = LEVEL_NAMES.get(info["level"]) if info["level"] else None

    ok, note = can_patch(buf)
    info["patchable"] = ok
    info["patch_note"] = note
    return info


def _lang_codes(sa: Path) -> list[str]:
    """语言代码列表。注意目录里还有 `lang-xx.manifest`，要排掉。"""
    return sorted(p.name[5:] for p in sa.glob("lang-*")
                  if p.is_file() and not p.name.endswith(".manifest"))


def _langtool_state() -> dict:
    """langtool（改语言包要用的外部工具）当前可用吗。"""
    try:
        ok, how = lpt.have_framework()
        cmd = lpt.tool_command() if ok else None
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "detail": "%s: %s" % (type(e).__name__, e),
                "cmd": None}
    return {"ok": ok, "detail": how, "cmd": " ".join(cmd) if cmd else None}


_PATCHDLL_CACHE: dict = {}


def _patchdll_state() -> dict:
    """langtool 是不是带 patchdll 子命令的那版（旧版没有）。

    只探一次：状态每 5 秒轮询一次，每次都 spawn 一个 10 MB 的 exe 太浪费
    （以前就因为这类事弹过一个“每 5 秒一个黑窗”的风暴）。
    """
    if _PATCHDLL_CACHE:
        return dict(_PATCHDLL_CACHE)
    ok, how = lpt.have_framework()
    if not ok:
        _PATCHDLL_CACHE.update({"ok": False, "detail": how})
        return dict(_PATCHDLL_CACHE)
    try:
        r = lpt.run_langtool("--check-patchdll")
    except Exception as e:                                  # noqa: BLE001
        _PATCHDLL_CACHE.update({"ok": False,
                                "detail": "%s: %s" % (type(e).__name__, e)})
        return dict(_PATCHDLL_CACHE)
    text = (r.stdout or "") + (r.stderr or "")
    if "patchdll" in text:
        _PATCHDLL_CACHE.update(
            {"ok": True, "detail": "langtool 支持 patchdll（DLL 就地改四个点）"})
    else:
        _PATCHDLL_CACHE.update({
            "ok": False,
            "detail": "langtool 是旧版、没有 patchdll 子命令 —— "
                      "重新构建并重新发布 hardcore/langtool 再打包"})
    return dict(_PATCHDLL_CACHE)


_LANG_CACHE: dict[str, tuple] = {}


def probe_langs(sa: Path) -> dict:
    """探 StreamingAssets 下的语言包：**读包里那 4 个键的文本**来判档。

    为什么不再比对哈希：补丁语言包不再随程序分发（改成在玩家自己的包上原地改），
    没有“预编译产物哈希”可比了。读文本还顺带能认出被别的 mod 改过的包。

    结果按 (路径, 大小, mtime) 缓存 —— 界面每 5 秒轮询一次，不能每次都解包。
    """
    info: dict = {"dir": str(sa), "exists": sa.is_dir(), "langs": {}}
    if not info["exists"]:
        info["detail"] = "目录不存在"
        return info

    codes = _lang_codes(sa)
    info["codes"] = codes
    if not codes:
        return info

    for code in codes:
        p = sa / ("lang-" + code)
        try:
            st = p.stat()
        except OSError as e:
            info["langs"][code] = {"level": None, "kind": "unknown",
                                   "error": str(e)}
            continue
        ck = (str(p), st.st_size, st.st_mtime_ns)
        hit = _LANG_CACHE.get(code)
        if hit and hit[0] == ck:
            info["langs"][code] = dict(hit[1])
            continue

        row: dict = {"size": st.st_size}
        try:
            vals = lpt.bundle_values(p)
            lv = lpt.level_of(code, vals)
            row["level"] = lv
            if lv is None:
                row["kind"] = "unknown"
                row["detail"] = "这 4 个键的文本对不上任何一个档位（可能被别的 mod 改过）"
            elif lv == VANILLA:
                row["kind"] = "vanilla"
            else:
                row["kind"] = "patched"
        except Exception as e:                              # noqa: BLE001
            row["level"] = None
            row["kind"] = "unknown"
            row["error"] = "%s: %s" % (type(e).__name__, e)
        _LANG_CACHE[code] = (ck, row)
        info["langs"][code] = dict(row)

    lv_set = {r["level"] for r in info["langs"].values()}
    unknown = [c for c, r in info["langs"].items() if r["level"] is None]
    if len(lv_set - {None}) == 1 and not unknown:
        info["level"] = next(iter(lv_set))
        info["consistent"] = True
    elif not lv_set - {None}:
        info["level"] = None
        info["consistent"] = None
        info["detail"] = "所有语言包都认不出档位"
    else:
        info["level"] = None
        info["consistent"] = False
        info["detail"] = ("各语言档位不一致：%s"
                         % sorted((c, r["level"]) for c, r in info["langs"].items())
                         if not unknown else
                         "这些语言包认不出：%s" % unknown)
    return info


# --------------------------------------------------------------------------
# 存档
# --------------------------------------------------------------------------
def saves_dir() -> Path:
    raw = os.environ.get("OBRADINN_SAVES")
    if raw:
        return Path(raw).expanduser()
    if sys.platform == "win32":
        base = (os.environ.get("USERPROFILE") or str(Path.home()))
        return Path(base) / "AppData" / "LocalLow" / "3909" / "ObraDinn"
    if sys.platform == "darwin":
        # ★ 实测 mac 用的是 bundle id `co.3909.ObraDinn`；
        #   早期 Unity 版本会写成 `unity.3909.ObraDinn`，两个都试。
        sup = Path.home() / "Library" / "Application Support"
        for name in ("co.3909.ObraDinn", "unity.3909.ObraDinn"):
            if (sup / name).is_dir():
                return sup / name
        return sup / "co.3909.ObraDinn"
    return Path.home() / ".config" / "unity3d" / "3909" / "ObraDinn"


SLOTS = ("P1", "P2", "P3")


def slot_path(slot: str, d: Path | None = None) -> Path:
    return (d or saves_dir()) / ("ObraDinnSave-%s.txt" % slot)


def read_slot_xml(p: Path) -> str:
    """读出存档明文 XML。

    槽位文件是加密信封，得先解密；万一格式变了就退回当纯文本看（至少
    能让界面显示个大概，而不是整块崩掉）。
    """
    from hardcore.align_save import load_save                 # noqa: PLC0415
    _text, xml = load_save(p)
    return xml


def slots_state() -> list[dict]:
    d = saves_dir()
    out = []
    for s in SLOTS:
        p = slot_path(s, d)
        row: dict = {"slot": s, "path": str(p), "exists": p.is_file()}
        if row["exists"]:
            row["size"] = p.stat().st_size
            row["mtime"] = p.stat().st_mtime
            row["sha256_16"] = sha256_file(p)[:16]
            try:
                xml = read_slot_xml(p)
                m = re.search(r"<general\b[^>]*?\bera=\"(\d+)\"", xml)
                row["era"] = int(m.group(1)) if m else None
                row["zone"] = ("办公室" if row["era"] == 3
                               else "船上" if row["era"] is not None else None)
                row["marked"] = len(re.findall(
                    r'<face\b[^>]*?markedCorrect="true"', xml))
                row["faces"] = len(re.findall(r"<face\b", xml))
            except Exception as e:                       # noqa: BLE001
                row["error"] = "%s: %s" % (type(e).__name__, e)
        out.append(row)
    return out


def align_save_file(src: Path, level: int) -> tuple[bool, str, dict]:
    """原地做难度对齐（先备份到用户数据目录）。

    依赖全部从 `hardcore.align_save` 拿：那个模块开头已经把仓库根和
    `hardcore/` 都加进 sys.path 了，它导入过的东西我们直接复用，
    省得再猜一遍 `make_envelope_save` 到底在哪个目录。
    """
    from hardcore.align_save import (align, crew_fates, load_save,  # noqa: PLC0415
                                     save_save, LEVEL_NAMES as _LN)

    if level not in _LN:
        return False, "不是标准档位: %s" % level, {}

    bak = data_dir() / "save-backups" / ("%s.%s.bak" % (src.name, _stamp()))
    bak.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, bak)

    text, xml = load_save(src)
    marked0 = xml.count('markedCorrect="true"')
    fates = crew_fates()
    xml2, ok = align(xml, level, fates, dry=False)
    save_save(text, xml2, src)

    _t, x3 = load_save(src)
    marked1 = x3.count('markedCorrect="true"')
    detail = "登记 %d -> %d 人" % (marked0, marked1)
    return ok, detail, {"backup": str(bak), "marked_before": marked0,
                        "marked_after": marked1}


# --------------------------------------------------------------------------
# 备份 / 还原
# --------------------------------------------------------------------------
def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backup_dir() -> Path:
    d = data_dir() / "original"
    d.mkdir(parents=True, exist_ok=True)
    return d


def original_dll() -> Path | None:
    """随附的**官方原版** DLL。

    Windows 和 mac 各是一份**不同的 build**，哈希不一样，所以开发期这两份
    分开放；发布时只需带上当前平台那份。
    """
    cands = [app_root() / "patcher" / "assets" / "original" / DLL_NAME]
    if sys.platform == "darwin":
        cands.append(REPO / "hardcore" / "_backup" / MAC_ORIG_NAME)
    cands.append(REPO / "hardcore" / "_backup" / (DLL_NAME + ".orig"))
    for c in cands:
        if c.is_file():
            return c
    return None


def patched_dir() -> Path:
    """预编译补丁 DLL 的目录 —— **仅开发期的比对基准**，不随包分发。

    mac 是另一份 build，打出来的字节天然不同，所以分开放。
    """
    return REPO / "hardcore" / ("_patched-mac" if sys.platform == "darwin"
                                else "_patched")


def original_lang_dir() -> Path | None:
    """随附的**真原版**语言包目录。"""
    for c in (app_root() / "patcher" / "assets" / "original" / "lang",
              REPO / "_backups" / "StreamingAssets-original",
              REPO / "hardcore" / "_backups" / "StreamingAssets-original",
              REPO / "hardcore" / "_lang"):
        if c.is_dir() and any(p for p in c.glob("lang-*")
                              if not p.name.endswith(".manifest")):
            return c
    return None


def backup_state() -> dict:
    d = backup_dir()
    dll = d / DLL_NAME
    langs = sorted(p.name[5:] for p in d.glob("lang-*")
                   if p.is_file() and not p.name.endswith(".manifest"))
    sha = sha256_file(dll) if dll.is_file() else None
    return {
        "dir": str(d),
        "dll": dll.is_file(),
        "dll_sha256": sha,
        # ★ 「原版形态」按**结构**判：哈希随 build 变，别的 build 的原版哈希
        #   照样对不上「我知道的那个原版哈希」，拿它当判据会给出误导性警告。
        "vanilla": _looks_vanilla(dll) if dll.is_file() else None,
        "official": (sha == VANILLA_DLL_SHA256) if sha else None,
        "lang_count": len(langs),
        "langs": langs,
    }


def ensure_backup(game: Path) -> dict:
    """把玩家**自己的原始文件**备份下来（只在首次做）。

    DLL 也照他当前的字节存 —— 不管那是原版、是我们打过的补丁版、还是
    别的 build。理由：
      * 「撤销」的语义就是「回到你第一次用本工具之前」，那就得是他自己的字节
      * 现在打补丁是**就地改他那份**（不再整份替换），所以拿他的字节当基准
        才对；否则打出来会变成「官方原版的壳 + 我们那个 build 的内容」。
    （早先的写法是「不是原版就改用随附原版」，那会把不同 build 的玩家
      悄悄换成我们的 build，撤销也回不到他自己的样子。）
    """
    d = backup_dir()
    sa = streaming_assets(game)
    did: list[str] = []
    notes: list[str] = []

    # --- DLL ---
    dst = d / DLL_NAME
    if not dst.is_file():
        cur = managed_dll(game)
        if not cur.is_file():
            raise RuntimeError("游戏里找不到 %s" % cur)
        shutil.copy2(cur, dst)
        did.append(DLL_NAME)
        pok, pwhy = can_patch(cur.read_bytes())
        notes.append("%s：照你当前的字节存了一份%s"
                     % (DLL_NAME, "" if pok else "（但这份认不出来：%s）" % pwhy))

    # --- 语言包 ---
    # 一律照玩家的**原始字节**存一份：还原时用它。
    # （指纹表里那套是我们自己的措辞，拿它“还原”会把玩家装过的其他语言包补丁抹掉。）
    for code in _lang_codes(sa):
        p = sa / ("lang-" + code)
        dst = d / p.name
        if not dst.is_file():
            shutil.copy2(p, dst)
            did.append(p.name)

    # `.manifest` 我们从没改过，照原样拷一份就行
    for p in sorted(sa.glob("lang-*.manifest")):
        dst = d / p.name
        if not dst.is_file():
            shutil.copy2(p, dst)
            did.append(p.name)
    for p in sorted(sa.glob("StreamingAssets.manifest")):
        dst = d / p.name
        if not dst.is_file():
            shutil.copy2(p, dst)
            did.append(p.name)

    meta = d / "backup.json"
    if did or not meta.is_file():
        meta.write_text(json.dumps({
            "created": _stamp(),
            "game": str(game),
            "notes": notes,
            "dll_sha256": sha256_file(d / DLL_NAME) if (d / DLL_NAME).is_file() else None,
            "files": sorted(p.name for p in d.iterdir() if p.is_file()),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"did": did, "notes": notes, **backup_state()}


def _is_game_running() -> bool:
    """游戏在跑就不许动文件。

    Windows 用 tasklist —— 必须带 `CREATE_NO_WINDOW`：打包后没控制台，
    每 spawn 一次都会闪个黑窗，而这个函数是状态轮询（每 5 秒）里调的。
    mac 用 pgrep 按 .app 里的可执行路径匹配（不能用进程名：macOS 的短名
    会被截到 16 字符，而且 -i 匹配 "obradinn" 会撞上补丁器自己）。
    """
    if sys.platform == "darwin":
        for pat in ("Obra Dinn.app/Contents/MacOS", "ObraDinn.app/Contents/MacOS"):
            try:
                r = subprocess.run(["pgrep", "-f", pat],
                                   capture_output=True, text=True, timeout=15)
            except (OSError, subprocess.SubprocessError):
                return False
            if r.returncode == 0 and (r.stdout or "").strip():
                return True
        return False
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ObraDinn.exe", "/NH"],
            capture_output=True, text=True, timeout=15,
            **lpt.no_window_kwargs()).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "ObraDinn.exe" in out


def restore() -> dict:
    """还原为原版：DLL 用备份，语言包也用备份（玩家自己的那份字节）。"""
    if _is_game_running():
        return {"ok": False, "error": "游戏正在运行，请先退出再还原"}

    game = find_game()
    if game is None:
        return {"ok": False, "error": "找不到游戏目录"}
    d = backup_dir()
    src_dll = d / DLL_NAME
    if not src_dll.is_file():
        return {"ok": False,
                "error": "没有原始备份。请用 Steam「验证游戏文件完整性」还原",
                "hint": "backup_missing"}

    did = []
    shutil.copy2(src_dll, managed_dll(game))
    did.append(DLL_NAME)

    sa = streaming_assets(game)
    for code in _lang_codes(sa):
        src_pack = d / ("lang-" + code)
        if src_pack.is_file():
            shutil.copy2(src_pack, sa / src_pack.name)
            did.append(src_pack.name)

    log = ["已还原 %d 个文件（DLL + 语言包，语言包用的是备份里玩家自己的字节）"
           % len(did)]
    return {"ok": True, "restored": did, "log": log, "state": state()}


# --------------------------------------------------------------------------
# 换档
# --------------------------------------------------------------------------
def apply_level(level: int, *, align: bool = True) -> dict:
    """换到指定档位。

    语言包改成**在玩家自己的包上原地改**（不再随程序分发 33 MB 预编译包）：
        备份玩家的包 -> 逐语言推演/校验/兜底 -> langtool 写回
    每次都直接算出目标文本，所以反复切换不会累积误差。
    """
    if level not in LEVEL_NAMES:
        return {"ok": False, "error": "不是标准档位: %s" % level}
    if _is_game_running():
        return {"ok": False, "error": "游戏正在运行，请先退出再换档"}

    game = find_game()
    if game is None:
        return {"ok": False, "error": "找不到游戏目录"}

    log: list[str] = []

    # 0) 改语言包要靠 langtool，先确认能用，免得改到一半失败
    ok, how = lpt.have_framework()
    log.append("langtool：%s" % how)
    if not ok:
        return {"ok": False, "log": log,
                "error": "改语言包需要 langtool，但它不可用：%s" % how}
    if level != VANILLA:
        st = _patchdll_state()
        if not st["ok"]:
            return {"ok": False, "log": log,
                    "error": "改 DLL 需要 langtool 的 patchdll 子命令，但它不可用：%s"
                             % st["detail"]}

    # 1) 备份原始 DLL + 玩家当前的语言包
    try:
        b = ensure_backup(game)
    except (OSError, RuntimeError) as e:
        return {"ok": False, "error": "备份原始文件失败：%s" % e, "log": log}
    if b["did"]:
        log.append("已备份原始文件 %d 个 -> %s" % (len(b["did"]), b["dir"]))
    log.extend(b.get("notes") or [])
    if not _looks_vanilla(backup_dir() / DLL_NAME):
        log.append("注意：备份里那份 DLL 不是原版形态，"
                   "「撤销」后会回到它原来的样子（可能仍带着别的改动）")

    sa = streaming_assets(game)
    packs = [sa / ("lang-" + c) for c in _lang_codes(sa)]
    if not packs:
        return {"ok": False, "error": "StreamingAssets 里没有 lang-* 文件",
                "log": log}

    # DLL：一律拿**备份里玩家自己那份**就地改这四个点。
    # 为什么不整份替换成预编译产物：不同游戏 build 的 DLL 内容不同，
    # 整份换会把他的 build 悄悄换走（还有可能跟他游戏里别的文件对不上）。
    src_dll = backup_dir() / DLL_NAME
    if not src_dll.is_file():
        return {"ok": False, "log": log,
                "error": "没有原始备份 DLL（%s）" % src_dll}

    if level == VANILLA:
        # 目标就是官方原版。备份里那份如果是原版形态最好（同一个 build）；
        # 不是的话退回随附的官方原版，并在日志里说清楚。
        if not _looks_vanilla(src_dll):
            cand = original_dll()
            if cand is None or not cand.is_file():
                return {"ok": False, "log": log,
                        "error": "备份里那份 DLL 不是原版形态，手边又没有随附的官方原版。\n"
                                 "请在 Steam 里「验证游戏文件的完整性」后重试。"}
            log.append("备份里那份 DLL 不是原版形态，改用随附的官方原版"
                       "（换回官方那个 build）")
            src_dll = cand
    else:
        pok, pwhy = can_patch(src_dll.read_bytes())
        if not pok:
            return {"ok": False, "log": log,
                    "error": "这份 DLL 认不出来，不能就地改（%s）。\n"
                             "请在 Steam 里「验证游戏文件的完整性」后重试。" % pwhy}

    # 2) **先全部转换到临时文件**，全部成功才就位。
    #
    # 为什么要这样：换一次档要 spawn 近 30 次 langtool，实测偶发失败；如果直接
    # 就地改，中途挂掉就会留下“DLL 是新的、语言包一半新的”——既不能玩也说不清。
    # 现在失败只影响临时目录，游戏文件一个字没动。
    # 临时目录放在 StreamingAssets 里，就是为了跟目标文件同卷，好走 os.replace。
    tmp = sa / ".obradinn-patch-tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, Path]] = []
    n_changed = 0
    try:
        for p in packs:
            code = p.name[5:]
            dst = tmp / p.name
            rep = lpt.patch_langfile(p, level, out=dst)
            if rep.get("changed"):
                n_changed += 1
            for note in rep.get("notes") or []:
                log.append("  %s：%s" % (code, note))
            if dst.is_file() and dst.stat().st_size > 0:
                staged.append((dst, p))
        log.append("语言包 %d 个：%d 个需要改写（已在临时目录备好）"
                   % (len(packs), n_changed))

        # 3) DLL 也先备好：就地改那份副本，改完自检四处都到位
        staged_dll = tmp / DLL_NAME
        if level == VANILLA:
            shutil.copy2(src_dll, staged_dll)
        else:
            # Cecil 写盘时要能解析 UnityEngine.* 才能重建元数据，
            # 所以把游戏的 Managed 目录告诉它（PATCH-SPEC.md 里记的“坑 1”）
            lpt.patch_dll(src_dll, level, staged_dll,
                          deps=managed_dll(game).parent)
            vok, vwhy = verify_patched_dll(staged_dll, level)
            if not vok:
                raise RuntimeError("打出来的 DLL 自检没过：%s" % vwhy)

        # 4) 就位：同一卷内 os.replace 是原子的，单个文件不会出现半截
        for dst, target in staged:
            os.replace(dst, target)
        os.replace(staged_dll, managed_dll(game))
        log.append("已就位：语言包 %d 个 + %s（档位 %d）"
                   % (len(staged), DLL_NAME, level))
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "log": log,
                "error": "换档失败，**游戏文件没有改动**：%s" % e}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 4) 对齐存档
    align_report: list[dict] = []
    if align and level != VANILLA:
        for s in SLOTS:
            p = slot_path(s)
            if not p.is_file():
                continue
            try:
                ok, detail, extra = align_save_file(p, level)
            except Exception as e:                       # noqa: BLE001
                align_report.append({"slot": s, "ok": False, "detail": str(e)})
                continue
            row = {"slot": s, "ok": ok, "detail": detail, **extra}
            align_report.append(row)
        if align_report:
            log.append("已对齐存档 %d 个" % len(align_report))
    elif align and level == VANILLA:
        log.append("原版档位：跳过存档对齐（原版链本身就是全档可达）")

    return {"ok": True, "level": level, "name": LEVEL_NAMES[level],
            "log": log, "align": align_report, "state": state()}


# --------------------------------------------------------------------------
# 汇总状态
# --------------------------------------------------------------------------
def state() -> dict:
    game = find_game()
    out: dict = {
        "game": str(game) if game else None,
        "game_found": game is not None,
        "game_running": _is_game_running(),
        "saves_dir": str(saves_dir()),
        "levels": [{"level": k, "name": v, "vanilla": k == VANILLA}
                   for k, v in sorted(LEVEL_NAMES.items())],
        "assets": {
            "langtool": _langtool_state(),
            "dll_patch": _patchdll_state(),
        },
        "backup": backup_state(),
    }
    if game is None:
        out["dll"] = {"exists": False, "kind": "missing", "detail": "找不到游戏"}
        out["langs"] = {"exists": False}
        out["consistent"] = None
    else:
        dd = probe_dll(managed_dll(game))
        ll = probe_langs(streaming_assets(game))
        out["dll"] = dd
        out["langs"] = ll
        dll_lv = dd.get("level")
        lang_lv = ll.get("level")
        out["dll_level"] = dll_lv
        out["lang_level"] = lang_lv
        out["consistent"] = (None if dll_lv is None or lang_lv is None
                             else dll_lv == lang_lv)
    out["slots"] = slots_state()
    return out


# --------------------------------------------------------------------------
# CLI（调试）
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "state"

    if cmd == "state":
        print(json.dumps(state(), ensure_ascii=False, indent=1))
        return 0
    if cmd == "levels":
        for lv in sorted(LEVEL_NAMES):
            tag = "（原版）" if lv == VANILLA else ""
            print("%3d  %s%s" % (lv, LEVEL_NAMES[lv], tag))
        return 0
    if cmd == "probe":
        if len(argv) < 2:
            print("用法: probe <dll>")
            return 2
        print(json.dumps(probe_dll(Path(argv[1])),
                         ensure_ascii=False, indent=1))
        return 0
    if cmd == "align":
        if len(argv) < 3:
            print("用法: align <存档> <档位>")
            return 2
        ok, detail, extra = align_save_file(Path(argv[1]), int(argv[2]))
        print(json.dumps({"ok": ok, "detail": detail, **extra},
                         ensure_ascii=False, indent=1))
        return 0 if ok else 1
    if cmd == "apply":
        if len(argv) < 2:
            print("用法: apply <档位> [--no-align]")
            return 2
        rep = apply_level(int(argv[1]), align="--no-align" not in argv)
        for line in rep.get("log") or []:
            print("   " + line)
        print(json.dumps({k: v for k, v in rep.items() if k != "state"},
                         ensure_ascii=False, indent=1)[:4000])
        return 0 if rep.get("ok") else 1
    if cmd == "restore":
        rep = restore()
        for line in rep.get("log") or []:
            print("   " + line)
        print("ok=%s %s" % (rep.get("ok"), rep.get("error") or ""))
        return 0 if rep.get("ok") else 1

    print(__doc__.strip().splitlines()[-6])
    print("未知命令: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
