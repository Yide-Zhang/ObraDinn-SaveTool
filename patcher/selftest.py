#!/usr/bin/env python3
"""补丁器自检：把 core.state() 的结果打印成人能看的几行。

用法：
    python -m patcher.selftest
"""
from __future__ import annotations

import json
import sys

from patcher import core


def main() -> int:
    st = core.state()

    print("游戏目录 : %s" % (st["game"] or "**没找到**"))
    print("游戏状态 : %s" % ("运行中（不能改文件）" if st["game_running"] else "未运行"))
    print("存档目录 : %s" % st["saves_dir"])
    print()

    dd = st["dll"]
    print("DLL      : kind=%s level=%s const=%s candidates=%s"
          % (dd.get("kind"), dd.get("level"), dd.get("const"), dd.get("const_candidates")))
    print("           签名 vanilla=%s patched=%s b1=%s b2=%s  note=%s"
          % (dd.get("seal_vanilla"), dd.get("seal_patched"),
             dd.get("b1_patched"), dd.get("b2_patched"), dd.get("const_note")))
    print("           可就地改=%s  %s"
          % (dd.get("patchable"), dd.get("patch_note") or ""))
    for w in dd.get("warnings", []) or []:
        print("           [!] %s" % w)

    ll = st["langs"]
    langs = ll.get("langs", {})
    lv = {}
    for code, row in langs.items():
        lv.setdefault(row.get("level"), []).append(code)
    print("语言包   : %d 个 -> %s"
          % (len(langs), {k: len(v) for k, v in sorted(lv.items(), key=lambda x: (x[0] is None, x[0]))}))
    print("           level=%s consistent=%s %s"
          % (ll.get("level"), ll.get("consistent"), ll.get("detail") or ""))

    print("一致性   : DLL=%s 语言包=%s -> %s"
          % (st.get("dll_level"), st.get("lang_level"),
             {True: "[OK] 一致", False: "[X] 不一致", None: "? 无法判定"}[st.get("consistent")]))
    print()

    bp = st["backup"]
    print("原始备份 : %s  DLL=%s 原版形态=%s  语言包=%s 个  (%s)"
          % (bp["dir"], bp["dll"], bp["vanilla"], bp["lang_count"],
             (bp["dll_sha256"] or "-")[:16]))

    asx = st["assets"]
    print("工具     : langtool %s | %s"
          % ("可用" if asx["langtool"]["ok"] else "不可用",
             asx["langtool"]["detail"]))
    print("           patchdll %s | %s"
          % ("可用" if asx["dll_patch"]["ok"] else "不可用",
             asx["dll_patch"]["detail"]))
    print()

    for s in st["slots"]:
        if not s["exists"]:
            print("槽位 %s   : 空" % s["slot"])
            continue
        if "error" in s:
            print("槽位 %s   : 读不出来 -> %s" % (s["slot"], s["error"]))
            continue
        print("槽位 %s   : %s  已登记 %s / 共 %s 人  (%s, %d B)"
              % (s["slot"], s.get("zone") or "?", s.get("marked"), s.get("faces"),
                 s["sha256_16"], s["size"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
