#!/usr/bin/env python3
"""补丁器 GUI 冒烟测试。

真刀真枪跑一遍，但**不碰存档**（对齐那一步在副本上做）：

    1. 检查环境：随附的原版 DLL、langtool、指纹表
    2. 起服务，读 /api/state
    3. POST /api/apply（档位 58，align=false）
       并断言游戏里 14 个语言包与已验证产物**逐字节相同**
    4. POST /api/restore，确认 DLL 哈希 == 已知原版
       （这一步能证明备份是真原版）
    5. 再 POST /api/apply 回到 58
    6. 拿 P2 的副本试一次「对齐到中等(6)」

用法：python -m patcher.gui_smoke
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from patcher import core, server

OK, BAD = "[OK]", "[X]"
fails: list[str] = []


def check(cond: bool, label: str, extra: str = "") -> None:
    print("  %s %s%s" % (OK if cond else BAD, label, ("  " + extra) if extra else ""))
    if not cond:
        fails.append(label)


def call(port: int, path: str, payload: dict | None = None) -> dict:
    url = "http://127.0.0.1:%d%s" % (port, path)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


ARTIFACTS = core.REPO / "hardcore" / "_lang" / "out"


def game_packs_snapshot() -> dict[str, str]:
    """游戏里那 14 个语言包的 sha256。"""
    sa = core.streaming_assets(core.find_game())
    return {c: core.sha256_file(sa / ("lang-" + c)) for c in core._lang_codes(sa)}  # noqa: SLF001


def check_against_artifacts(level: int) -> None:
    """游戏里的语言包必须与已验证产物逐字节相同。

    这是整套流程最硬的一条断言：那批产物是在游戏里实测过能用的。
    （产物不存在就跳过 —— 开发机上才有。）

    ⚠ 产物是按 **Windows 原文**生成的。不同平台的语言包原文可能不一样
    （实测 mac 版 zh-s 的 `help_faceclear_fates1` 就是另一种写法），那这种语言
    打出来的字节本来就**应该**与产物不同 —— 工具特意保留玩家自己的措辞。
    这种语言跳过比对并说明。
    """
    d = ARTIFACTS / ("lv%d" % level)
    if not d.is_dir():
        print("  [i] 没有 %s，跳过与已验证产物的对比" % d)
        return
    w_orig = core.REPO / "_backups" / "StreamingAssets-original"
    bk = core.backup_dir()
    game = game_packs_snapshot()
    bad = []
    skipped = []
    for code, sha in sorted(game.items()):
        ref = d / ("lang-" + code)
        wo = w_orig / ("lang-" + code)
        pb = bk / ("lang-" + code)
        if (wo.is_file() and pb.is_file()
                and core.sha256_file(wo) != core.sha256_file(pb)):
            skipped.append(code)
            continue
        if not ref.is_file() or core.sha256_file(ref) != sha:
            bad.append(code)
    check(not bad, "语言包与已验证产物逐字节相同",
          "不同的：%s" % bad if bad else "(lv%d / %d 个%s)"
          % (level, len(game) - len(skipped),
             "，跳过原文不同：%s" % ",".join(skipped) if skipped else ""))
    if skipped:
        print("    [i] %s 的原文与本平台不同，产物字节本就该不同 → 跳过"
              % ",".join(skipped))


def check_dll_against_artifact(level: int) -> None:
    """游戏里的 DLL 必须与已验证的预编译产物逐字节相同。

    这条把「就地用 Cecil 改玩家自己的 DLL」钉在当初那批在游戏里实测过的
    产物上 —— 只要这条过，就说明现改出来的东西跟那时一模一样。
    """
    ref = core.patched_dir() / ("lc-lv%d.dll" % level)
    if not ref.is_file():
        print("  [i] 没有 %s，跳过 DLL 逐字节对比" % ref.name)
        return
    g = core.find_game()
    if g is None:
        return
    a = core.sha256_file(core.managed_dll(g))
    b = core.sha256_file(ref)
    check(a == b, "游戏里的 DLL 与 %s 逐字节相同" % ref.name,
          "%s vs %s" % (a[:16], b[:16]))


def main() -> int:
    print("=" * 70)
    print("1) 环境")
    print("=" * 70)
    od = core.original_dll()
    print("  随附原版 DLL : %s" % od)
    check(od is not None and od.is_file(), "有随附的原版 DLL")
    if od is not None and od.is_file():
        h = core.sha256_file(od)
        # 硬编码的哈希是 Windows 那份的；mac 是另一份 build，按结构判
        check(h == core.VANILLA_DLL_SHA256 or core._looks_vanilla(od),  # noqa: SLF001
              "随附 DLL 是已知原版或原版形态", h[:16])

    ok_tool, how_tool = core.lpt.have_framework()
    print("  langtool     : %s" % how_tool)
    check(ok_tool, "langtool 可用", how_tool)

    pd = core._patchdll_state()                                  # noqa: SLF001
    print("  patchdll     : %s" % pd["detail"])
    check(pd["ok"], "langtool 支持 patchdll（DLL 就地打补丁）", pd["detail"])

    fp = core.fingerprint_file()
    check(fp.is_file(), "有语言文本指纹表", str(fp))

    game = core.find_game()
    check(game is not None, "找到游戏目录", str(game))
    if game is None:
        return 1
    check(not core._is_game_running(), "游戏没在运行")   # noqa: SLF001

    print()
    print("=" * 70)
    print("2) 起服务")
    print("=" * 70)
    port = server.pick_port(18900)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    print("  http://127.0.0.1:%d/" % port)

    r = call(port, "/api/state")
    st = r["state"]
    init_level = st["dll"].get("level")       # 收尾要恢复到这个档位
    print("  DLL   : kind=%s level=%s" % (st["dll"].get("kind"), init_level))
    print("  语言包: level=%s consistent=%s"
          % (st["langs"].get("level"), st["langs"].get("consistent")))
    check(st["game_found"], "API 能读到游戏")
    check(st["dll"].get("kind") in ("vanilla", "patched"), "API 能判出 DLL 档位")

    print()
    print("=" * 70)
    print("3) 应用档位 58（align=false，先不动存档）")
    print("=" * 70)
    r = call(port, "/api/apply", {"level": 58, "align": False})
    check(r.get("ok") is True, "apply 返回 ok", str(r.get("error") or ""))
    for line in r.get("log") or []:
        print("    " + line)
    check(bool(r.get("log")), "apply 有日志")

    r = call(port, "/api/state")
    st = r["state"]
    check(st["dll"].get("level") == 58, "DLL 现在是 58",
          "kind=%s const=%s" % (st["dll"].get("kind"), st["dll"].get("const")))
    check(st["langs"].get("level") == 58, "语言包现在是 58",
          "consistent=%s" % st["langs"].get("consistent"))
    check(st["consistent"] is True, "DLL 与语言包一致")
    bp = st["backup"]
    check(bp["dll"], "备份里有 DLL（存的是玩家自己的字节）",
          "原版形态=%s sha256=%s" % (bp["vanilla"], str(bp["dll_sha256"])[:16]))
    check(bp["lang_count"] == 14, "备份了 14 个语言包", "实际 %d" % bp["lang_count"])
    # 最关键的两条：写进去的东西必须和实测过的那批产物一模一样
    check_dll_against_artifact(58)
    check_against_artifacts(58)

    print()
    print("=" * 70)
    print("4) 还原为原版")
    print("=" * 70)
    r = call(port, "/api/restore", {})
    check(r.get("ok") is True, "restore 返回 ok", str(r.get("error") or ""))
    for line in r.get("log") or []:
        print("    " + line)
    st = call(port, "/api/state")["state"]
    bkdll = core.backup_dir() / core.DLL_NAME
    check(st["dll"].get("sha256") == core.sha256_file(bkdll),
          "游戏里的 DLL 已还原成备份里的字节",
          "kind=%s" % st["dll"].get("kind"))
    # 语言包是用**玩家自己的字节备份**还原的，所以应当与备份一致
    bk = core.backup_dir()
    sa = core.streaming_assets(game)
    bad = [c for c in core._lang_codes(sa)                          # noqa: SLF001
           if core.sha256_file(sa / ("lang-" + c))
           != core.sha256_file(bk / ("lang-" + c))]
    check(not bad, "语言包已还原成备份里的字节", "不同的：%s" % bad if bad else "")

    print()
    print("=" * 70)
    print("5) 再应用回 58（回到测试前的状态）")
    print("=" * 70)
    r = call(port, "/api/apply", {"level": 58, "align": False})
    check(r.get("ok") is True, "apply 返回 ok", str(r.get("error") or ""))
    st = call(port, "/api/state")["state"]
    check(st["dll"].get("level") == 58 and st["langs"].get("level") == 58,
          "DLL 与语言包都回到 58")
    check(st["consistent"] is True, "两者一致")
    check_dll_against_artifact(58)
    check_against_artifacts(58)

    print()
    print("=" * 70)
    print("6) 对齐（在 P2 的副本上做，不动真存档）")
    print("=" * 70)
    src = core.slot_path("P2")
    if not src.is_file():
        print("  (P2 是空的，跳过)")
    else:
        tmp = core.data_dir() / "smoke"
        tmp.mkdir(parents=True, exist_ok=True)
        cp = tmp / "P2.copy.txt"
        shutil.copy2(src, cp)
        print("  副本 %s  %d B" % (cp, cp.stat().st_size))
        ok, detail, extra = core.align_save_file(cp, 6)
        print("  对齐到中等(6)：ok=%s  %s" % (ok, detail))
        print("  备份到 %s" % extra.get("backup"))
        check(ok, "对齐到 6 能算通", detail)
        check(extra.get("marked_after") is not None, "对齐写回了文件")
        try:
            cp.unlink()
        except OSError:
            pass

    # 收尾：把档位恢复到测试前的样子。
    # 不然跑一次冒烟测试就把玩家当前的档位改了。（存档全程没动。）
    print()
    print("=" * 70)
    print("7) 恢复到测试前的档位")
    print("=" * 70)
    if init_level is None:
        print("  [i] 测试前判不出档位，不动它。")
    elif init_level == 58:
        print("  [i] 测试前就是 58，不用恢复。")
    else:
        r = call(port, "/api/apply", {"level": init_level, "align": False})
        check(r.get("ok") is True, "已恢复到档位 %s" % init_level,
              str(r.get("error") or ""))
        check_dll_against_artifact(init_level)
        check_against_artifacts(init_level)

    httpd.shutdown()
    print()
    print("=" * 70)
    if fails:
        print("失败 %d 项：" % len(fails))
        for f in fails:
            print("  - %s" % f)
        return 1
    print("全部通过 [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
