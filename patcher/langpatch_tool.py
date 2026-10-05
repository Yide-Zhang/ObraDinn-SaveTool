#!/usr/bin/env python3
"""用 langtool（C# + AssetsTools.NET）改玩家**自己**的语言包。

就是你描述的那套三步：
    1. langtool export <包> <tsv>          —— 把包里的资产掏出来
    2. Python 按「语言 + 档位」算出那 4 个键的新文本，写 edits.txt
    3. langtool set <包> <新包> <edits> --pack=lzma   —— 塞回去

不搬运整包：改的是玩家机器上那份包，改完就位（原包由上层先备份）。

为什么用 C# 的 AssetsTools.NET 而不是自己解包：
    * 它已经被验证过 —— hardcore/_lang/out/ 里那 84 个语言包就是它产出的，
      并且在游戏里实测可用
    * 代价只有一个：目标机器需要 .NET 运行时（langtool 是 net8.0）

用法：
    python -m patcher.langpatch_tool <包> --level 58 [--out 新包]
    python -m patcher.langpatch_tool <包> --check      # 只报当前 4 个键的值
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PATCHER_DIR = Path(__file__).resolve().parent
REPO = PATCHER_DIR.parent

KEYS = ("welldone_3_first", "welldone_3_more",
        "help_faceclear_fates0", "help_faceclear_fates1")

LEVELS = (3, 4, 6, 9, 14, 29, 58)


def no_window_kwargs() -> dict:
    """Windows 上别弹控制台窗口。

    打包成 `--windowed` 后本身没有控制台，这时每 spawn 一个控制台程序都会
    闪一个黑窗。而状态是每 5 秒轮询一次、每次都跑一次 tasklist —— 实测就是
    每 5 秒弹一个窗。langtool 那 30 次 spawn 也一样。
    """
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}      # CREATE_NO_WINDOW
    return {}


# --------------------------------------------------------------------------
# 工具定位
# --------------------------------------------------------------------------
class ToolMissing(RuntimeError):
    pass


def find_langtool() -> Path:
    """找 langtool.dll（以及配套的 AssetsTools.NET.dll）。"""
    cands = sorted(REPO.glob("hardcore/langtool/bin/*/net*/langtool.dll"))
    cands += sorted(REPO.glob("patcher/assets/bin/**/langtool.dll"))
    for c in cands:
        if (c.parent / "AssetsTools.NET.dll").is_file():
            return c
    raise ToolMissing(
        "找不到 langtool.dll。先构建一次：\n"
        "    dotnet build hardcore/langtool/LangTool.csproj -c Release")


def _exec_ok(p: Path) -> Path:
    """补可执行位。

    自包含的 langtool 在 mac/linux 上必须是可执行的；从 zip / 网盘 / 同步工具
    拿到的文件经常丢掉这一位（实测：在 Windows 上打的 tar 解到 mac 就只有 644，
    直接 PermissionError）。玩家那边同样会遇到，所以代码里兜一道。
    """
    if sys.platform != "win32" and p.is_file():
        try:
            mode = p.stat().st_mode
            if not (mode & 0o111):
                p.chmod(mode | 0o755)
        except OSError:
            pass
    return p


def standalone_exe() -> Path | None:
    """自包含发布的 langtool（有它就不需要 .NET 运行时）。

    优先看环境变量，其次找打包目录里附带的那份。
    """
    import os
    raw = os.environ.get("OBRADINN_LANGTOOL_EXE")
    if raw:
        p = Path(raw)
        if p.is_file():
            return _exec_ok(p)
    for c in (PATCHER_DIR / "assets" / "bin" / "langtool.exe",
              PATCHER_DIR / "assets" / "bin" / "langtool"):
        if c.is_file():
            return _exec_ok(c)
    return None


def dotnet_exe() -> str:
    exe = shutil.which("dotnet")
    if exe is None:
        raise ToolMissing("找不到 dotnet 命令。langtool 需要 .NET 运行时。")
    return exe


def tool_command() -> list[str]:
    """要执行 langtool 的命令行前缀。

    自包含版直接跑 exe；否则用 `dotnet langtool.dll`（需机器上有 .NET 8）。
    """
    exe = standalone_exe()
    if exe is not None:
        return [str(exe)]
    return [dotnet_exe(), str(find_langtool())]


def have_framework() -> tuple[bool, str]:
    """能不能跑 langtool：有自包含 exe 就直接行，否则要有 .NET 8。"""
    exe = standalone_exe()
    if exe is not None:
        return True, "自带独立版 %s（无需 .NET）" % exe.name
    try:
        exe_cmd = dotnet_exe()
    except ToolMissing as e:
        return False, str(e)
    try:
        out = subprocess.run([exe_cmd, "--list-runtimes"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=30, **no_window_kwargs()).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return False, "跑 dotnet --list-runtimes 失败：%s" % e
    for line in out.splitlines():
        if line.startswith("Microsoft.NETCore.App 8."):
            return True, line.strip()
    return False, "没装 .NET 8 运行时（只有：%s）" % (
        ", ".join(l.split()[1] for l in out.splitlines()
                  if l.startswith("Microsoft.NETCore.App")) or "无")


def run_langtool(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """调 langtool。注意必须显式指定 UTF-8：

    subprocess 默认用控制台的 GBK 去解码子进程输出，而 langtool 用 UTF-8，
    撞上中文（比如路径里有“桌面”）就会在线程里抛 UnicodeDecodeError。
    """
    import os
    env = dict(os.environ)
    env["DOTNET_ROLL_FORWARD"] = "Major"
    return subprocess.run(
        [*tool_command(), *args],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=timeout, env=env, **no_window_kwargs())


# --------------------------------------------------------------------------
# 文本计算（复用开发期那套 numbers.py）
# --------------------------------------------------------------------------
def _numbers():
    p = REPO / "hardcore" / "_lang" / "numbers.py"
    spec = importlib.util.spec_from_file_location("obradinn_lang_numbers", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _unesc(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] in "ntr\\":
            out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}[s[i + 1]])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _esc(s: str) -> str:
    return (s.replace("\\", "\\\\").replace("\n", "\\n")
            .replace("\t", "\\t").replace("\r", "\\r"))


def read_tsv(path: Path) -> dict[str, str]:
    d: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("\t")
        d[k] = _unesc(v)
    return d


def current_values(bundle: Path) -> dict[str, str]:
    """掏出包，读那 4 个键当前的值（调 langtool，慢但权威）。"""
    with tempfile.TemporaryDirectory() as td:
        tsv = Path(td) / "dump.tsv"
        r = run_langtool("export", str(bundle), str(tsv))
        if r.returncode != 0 or not tsv.is_file():
            raise RuntimeError("langtool export 失败：\n%s\n%s"
                               % (r.stdout[-2000:], r.stderr[-2000:]))
        d = read_tsv(tsv)
    missing = [k for k in KEYS if k not in d]
    if missing:
        raise RuntimeError("包里缺这些键：%s" % missing)
    return {k: d[k] for k in KEYS}


# --------------------------------------------------------------------------
# 指纹表：每个语言 × 每个档位下那 4 个键的**权威文本**
#
# 有了它，改包就是「把那 4 个键设成目标文本」，不再需要从原文里做替换推演，
# 也就不需要知道“玩家手上这份现在是什么”，反复切换都不会累积误差。
# 这张表就来自 make_fingerprints.py，与已验证产物同源。
# --------------------------------------------------------------------------
_FP: dict | None = None


def fingerprints() -> dict:
    global _FP
    if _FP is None:
        p = PATCHER_DIR / "data" / "lang_fingerprints.json"
        _FP = json.loads(p.read_text(encoding="utf-8"))
    return _FP


def target_values(code: str, level: int) -> dict[str, str]:
    """该语言在该档位下，这 4 个键应该是什么文本。"""
    fp = fingerprints()
    per = fp["languages"].get(code)
    if per is None:
        raise ValueError("指纹表里没有语言 %r（有：%s）"
                         % (code, ", ".join(sorted(fp["languages"]))))
    got = per.get(str(level))
    if got is None:
        raise ValueError("指纹表里没有档位 %s" % level)
    return {k: got[k] for k in KEYS}


def bundle_values(bundle: Path) -> dict[str, str]:
    """纯 Python 从包里读出那 4 个键的值。

    不调 langtool —— 因为状态轮询会反复用到，调外部进程太慢。
    也不需要解析对象表：直接按「小端长度 + 内容」找字符串就行。
    """
    from hardcore.lang_bundle import Bundle                    # noqa: PLC0415
    data = Bundle(bundle).data()
    out: dict[str, str] = {}
    for k in KEYS:
        needle = struct.pack("<I", len(k.encode())) + k.encode()
        pos = data.find(needle)
        if pos < 0:
            raise ValueError("包里找不到键 %s" % k)
        vstart = (pos + 4 + len(k.encode()) + 3) & ~3
        vlen, = struct.unpack_from("<I", data, vstart)
        out[k] = data[vstart + 4:vstart + 4 + vlen].decode("utf-8", "replace")
    return out


def level_of(code: str, values: dict[str, str]) -> int | None:
    """从这 4 个键的值反推档位；认不出返回 None。

    先用指纹表**整句**比对（最可靠）；没有整句全中时，允许**一个键**的措辞不同
    —— 实测 mac 版 zh-s 的 `help_faceclear_fates1` 与 Windows 版写法就不一样
    （"…以将信息录入书中。" vs "…，并将信息印入书中。"），整句比会永远判不出来。
    档位差异体现在**数量词**上、四个键都会跟着变，所以「差一个键」不会把档位认错。
    """
    per = fingerprints()["languages"].get(code)
    if not per:
        return None
    best_lv, best_hit = None, 0
    for lv_s, kv in per.items():
        hit = sum(1 for k in KEYS if values.get(k) == kv[k])
        if hit == len(KEYS):
            return int(lv_s)
        if hit > best_hit:
            best_lv, best_hit = int(lv_s), hit
    return best_lv if best_hit >= len(KEYS) - 1 else None


def _vanilla_text(code: str, key: str, old: str) -> str:
    """把玩家当前文本里的「数量词」换回**原版(3)**的写法。

    `numbers.make_value` 只会拿原版词当「原词」去找，所以玩家包一旦已经打过补丁
    （句子里是「五十八」而不是「三」），它就找不到、直接失败。这里先把当前词还原
    成原版词，再交给 make_value —— 玩家自己的措辞、标点、换行仍然原样保留。

    实测：文本本来就是原版时这一步是恒等变换，所以对没装过补丁的玩家没有影响。
    """
    NUM = _numbers()
    numbers = getattr(NUM, "NUMBERS", {})
    shapes = getattr(NUM, "KEY_SHAPE", {})
    table = numbers.get(code, {}).get(shapes.get(key, ""))
    if not table:
        return old
    base = table.get(3)
    if not base:
        return old
    for lv, tok in sorted(table.items()):
        if lv == 3 or not tok:
            continue
        for cand in (tok, tok.lower(), tok[:1].upper() + tok[1:]):
            if not cand or cand not in old:
                continue
            if cand == tok:
                repl = base
            elif cand == tok.lower():
                repl = base.lower()
            else:
                repl = base[:1].upper() + base[1:]
            return old.replace(cand, repl)
    return old


def derive_values(code: str, level: int,
                  old: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """在玩家**当前文本**的基础上推演目标文本 —— 这是首选路径。

    为什么首选它：玩家可能装过别的语言包补丁（重译/润色）。做法是在他现有的
    句子里替换「数量词」，这样他的措辞、标点、换行都保留下来，我们只改数字。

    推演前先 `_vanilla_text` 把当前词还原成原版词，所以**无论当前是哪个档位**
    都能推演（这正是反复换档不累积误差的原因）。

    推不出来的那一条逐条校验：结果里必须出现该档位的数量词；不通过就用内置措辞。

    返回 (目标文本, 说明列表)。
    """
    NUM = _numbers()
    numbers = getattr(NUM, "NUMBERS", {})
    shapes = getattr(NUM, "KEY_SHAPE", {})
    fallback = target_values(code, level)

    out: dict[str, str] = {}
    notes: list[str] = []
    for k in KEYS:
        want = fallback[k]
        base = _vanilla_text(code, k, old.get(k, ""))
        try:
            got = NUM.make_value(code, k, level, base)
        except Exception as e:                             # noqa: BLE001
            got = None
            notes.append("%s：推演失败（%s）" % (k, e))
        # 校验：结果里要出现该档位的数量词，否则说明是在胡拼
        word = numbers.get(code, {}).get(shapes.get(k, ""), {}).get(level, "")
        ok = bool(got) and (not word or word.lower() in got.lower())
        if ok:
            out[k] = got
        else:
            out[k] = want
            if got and got != want:
                notes.append("%s：认不出句子里的数量词，已改用内置措辞" % k)
    return out, notes


def patch_langfile(bundle: Path, level: int, out: Path | None = None,
                   values: dict[str, str] | None = None) -> dict:
    """把**这个**语言包改到目标档位。

    values 显式给了就直接用（指纹表的绝对文本）；
    没给就**优先按玩家当前文本推演**，推不出来的那些条再退回指纹表。
    """
    if level not in LEVELS:
        raise ValueError("不是标准档位: %s（可选 %s）" % (level, list(LEVELS)))
    code = bundle.name[5:] if bundle.name.startswith("lang-") else bundle.stem

    NUM = _numbers()
    known = sorted(getattr(NUM, "NUMBERS", {}))
    if code not in known:
        raise ValueError(
            "从文件名认出的语言代码 %r 不认识（认识的：%s）。\n"
            "语言包的文件名必须是 lang-<code>。" % (code, ", ".join(known)))

    old = bundle_values(bundle)
    notes: list[str] = []
    if values is not None:
        new = values
    else:
        new, notes = derive_values(code, level, old)
    changed = {k: v for k, v in new.items() if v != old.get(k)}

    if not changed:
        return {"ok": True, "code": code, "level": level, "changed": {},
                "old": {}, "notes": notes, "note": "值已经就是目标，跳过"}

    with tempfile.TemporaryDirectory() as td:
        edits = Path(td) / "edits.txt"
        edits.write_text("".join("%s\t%s\n" % (k, _esc(v))
                                 for k, v in changed.items()),
                         encoding="utf-8")
        dst = out or (Path(td) / ("out-" + bundle.name))
        # 重试一次：换一次档要连续 spawn 近 30 次 langtool，实测偶发遇到
        # “返回非零但没有任何输出”（像是被杀软/系统拦了一下）。重试几乎
        # 每次都能过，但报错时必须把返回码带上，否则无从查起。
        r = None
        for attempt in (1, 2):
            r = run_langtool("set", str(bundle), str(dst), str(edits),
                             "--pack=lzma")
            if r.returncode == 0 and dst.is_file():
                break
            print("  [i] %s：langtool set 第 %d 次没成（返回码 %d），重试…"
                  % (code, attempt, r.returncode))
            time.sleep(0.6)
        if r.returncode != 0 or not dst.is_file():
            raise RuntimeError(
                "langtool set 失败（返回码 %d）\n"
                "  包：%s\n  输出：%r\n  错误：%r"
                % (r.returncode, bundle.name, r.stdout[-1500:], r.stderr[-1500:]))
        # 自证：把写出来的包再掏一遍，确认 4 个键都对
        tsv2 = Path(td) / "again.tsv"
        r2 = run_langtool("export", str(dst), str(tsv2))
        if r2.returncode != 0 or not tsv2.is_file():
            raise RuntimeError("复读失败：%s" % r2.stderr[-1000:])
        back = read_tsv(tsv2)
        bad = [k for k in KEYS if back.get(k, "") != new[k]]
        if bad:
            raise RuntimeError("复读对不上：%s\n  期望 %s\n  实际 %s"
                               % (bad, [new[k] for k in bad],
                                  [back.get(k) for k in bad]))
        if out is None:
            # 没指定输出就原地覆盖
            shutil.copy2(dst, bundle)

    return {"ok": True, "code": code, "level": level, "changed": changed,
            "old": {k: old[k] for k in changed}, "notes": notes,
            "value_count": len(back)}


# --------------------------------------------------------------------------
# DLL：就地给玩家的 Assembly-CSharp.dll 打难度补丁
# --------------------------------------------------------------------------
def patch_dll(src: Path, level: int, out: Path, deps: Path | None = None) -> dict:
    """把 `src`（玩家自己那份 DLL）改到目标档位，写到 `out`。

    **不整份替换**：只改 A / B1 / B2 / C 四个点（配方见 hardcore/PATCH-SPEC.md），
    定位靠类型名 + 方法名 + 语义 —— 所以对任何游戏 build 都通用，
    玩家 build 里别的东西（包括他装过的其他 DLL 补丁）都原样保留。

    deps: 解析依赖用的目录，就是游戏里的 `ObraDinn_Data/Managed`。
          Cecil 写盘时要解析 UnityEngine.* 才能重建元数据，缺了会抛
          AssemblyResolutionException（规格书里记的“坑 1”）。
          玩家机器上这个目录本来就在，所以就地作业是天然的。

    注意：**返回 0 不等于改对了** —— langtool 找不到站点时会「警告并继续」。
    上层必须用 `core.verify_patched_dll()` 复验四处都到位。
    """
    if level not in LEVELS:
        raise ValueError("不是标准档位: %s（可选 %s）" % (level, list(LEVELS)))
    if not src.is_file():
        raise FileNotFoundError("找不到 DLL: %s" % src)
    out.parent.mkdir(parents=True, exist_ok=True)

    args = ["patchdll", str(src), str(out), str(level)]
    if deps is not None and Path(deps).is_dir():
        args.append("--deps=%s" % deps)

    r = None
    for attempt in (1, 2):
        r = run_langtool(*args)
        if r.returncode == 0 and out.is_file() and out.stat().st_size > 0:
            return {"ok": True, "level": level, "out": out,
                    "size": out.stat().st_size,
                    "log": (r.stdout or "").strip()}
        print("  [i] langtool patchdll 第 %d 次没成（返回码 %d），重试…"
              % (attempt, r.returncode))
        time.sleep(0.6)

    raise RuntimeError(
        "langtool patchdll 失败（返回码 %d）\n  输入：%s\n  输出：%r\n  错误：%r"
        % (r.returncode, src.name, r.stdout[-1500:], r.stderr[-1500:]))


# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="用 langtool 改语言包")
    ap.add_argument("bundle")
    ap.add_argument("--level", type=int)
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true", help="只报当前 4 个键的值")
    a = ap.parse_args(argv)

    ok, how = have_framework()
    print("dotnet 8 运行时：%s  %s" % ("有" if ok else "没有", how))
    if not ok:
        print("[X] 这条路需要 .NET 8。")
        return 2
    try:
        tool = tool_command()
    except ToolMissing as e:
        print("[X] %s" % e)
        return 2
    print("langtool：%s" % " ".join(tool))

    b = Path(a.bundle)
    if a.check:
        for k, v in current_values(b).items():
            print("   %-24s %r" % (k, v))
        return 0

    if a.level is None:
        print("[X] 需要 --level")
        return 2
    rep = patch_langfile(b, a.level, Path(a.out) if a.out else None)
    print()
    print("语言 %s -> 档位 %d" % (rep["code"], a.level))
    for k, v in rep["changed"].items():
        print("   %-24s %r -> %r" % (k, rep["old"][k], v))
    print("复读自证：全部对得上 [OK]" if rep["changed"] else "（无需改动）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
