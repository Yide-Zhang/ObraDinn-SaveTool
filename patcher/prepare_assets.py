#!/usr/bin/env python3
"""把打补丁需要的资源汇总到 `patcher/assets/`，方便打包分发。

    patcher/assets/
      bin/        langtool.exe + classdata.tpk   ~11 MB  ← 改语言包 + 就地改 DLL
      original/   官方原版 DLL                    1 个    ~1 MB
      fonts/      子集化后的界面字体               2 个    ~0.6 MB
      data/       语言包文本指纹表                        ~44 KB

补丁 DLL 不再随包。以前是把 6 个预编译好的 Assembly-CSharp.dll（~6 MB）整份
覆盖过去，那会把玩家自己那个游戏 build 的代码换掉；现在改成让 langtool 的
patchdll 子命令**就地**改玩家那份 DLL 的四个点，任何 build 都通用。

官方原版 DLL 仍然随包：只在「玩家那份 DLL 认不出来、又想要官方原版」时兜底。

用法：
    python -m patcher.prepare_assets          # 汇总（已存在且大小一致就跳过）
    python -m patcher.prepare_assets --check  # 只检查，不写
    python -m patcher.prepare_assets --force  # 全部重拷
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from patcher import core


def _copy(src: Path, dst: Path, force: bool, dry: bool) -> tuple[bool, int]:
    """返回 (是否动了, 字节数)。"""
    if dst.is_file() and not force and dst.stat().st_size == src.stat().st_size:
        return False, 0
    if not dry:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return True, src.stat().st_size


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="汇总补丁器分发资源")
    ap.add_argument("--check", action="store_true", help="只检查，不写")
    ap.add_argument("--force", action="store_true", help="全部重拷")
    a = ap.parse_args(argv)

    out = core.PATCHER_DIR / "assets"
    print("目标目录：%s" % out)
    print()

    # 界面字体：从 font_src/ 的原件按本项目字符集裁一份
    # （用的是存档工具同款那两款字体）
    if not a.check:
        from patcher import subset_fonts, verify_font_coverage  # noqa: PLC0415
        print("--- 界面字体 ---")
        rc = subset_fonts.main([])
        if rc == 0:
            # 必须立刻验一遍：改了界面文案但没重新子集化的话，漏掉的字会静默
            # 回落到系统字体（实测漏过：想 话 累 积）
            rc = verify_font_coverage.main([])
        print()
        if rc != 0:
            print("[X] 界面字体有问题，先补齐再继续")
            return rc

    moved = 0
    total = 0
    for what, sub in (("原版 DLL", "original"), ("langtool", "bin")):
        n = 0
        nb = 0
        for src, rel in _sources(sub):
            did, size = _copy(src, out / sub / rel, a.force, a.check)
            if did:
                n += 1
                nb += size
            elif not a.check:
                pass
        moved += n
        total += nb
        print("  %-10s 需要更新 %d 个，%.1f MB" % (what, n, nb / 1048576))

    print()
    if a.check:
        print("（--check：没有写任何文件）")
        print("结论：%s" % ("已就绪" if moved == 0 else "有 %d 个文件需要汇总" % moved))
        return 0 if moved == 0 else 1
    print("已汇总 %d 个文件，共 %.1f MB" % (moved, total / 1048576))
    print()

    # 汇总完再走一遍自检
    print("自检：")
    od = core.original_dll()
    exe = core.lpt.standalone_exe()
    for label, p in (("original_dll", od), ("langtool.exe", exe)):
        print("  %-14s %s" % (label, p))
    if od is not None and od.is_file():
        h = core.sha256_file(od)
        same = h == core.VANILLA_DLL_SHA256
        shape = core._looks_vanilla(od)                          # noqa: SLF001
        print("  官方原版 DLL   %s  %s"
              % (h[:16], "哈希对得上 OK" if same
                 else ("原版形态（另一个 build，只能当兜底用）" if shape
                       else "既不是已知原版、形态也不对")))
    ok, how = core.lpt.have_framework()
    print("  langtool 可用   %s  %s" % (ok, how))
    pst = core._patchdll_state()
    print("  patchdll 可用   %s  %s" % (pst["ok"], pst["detail"]))
    print("  指纹表          %s" % core.fingerprint_file())
    return 0


def _sources(sub: str) -> list[tuple[Path, Path]]:
    """(源文件, 相对目标路径) 列表。"""
    out: list[tuple[Path, Path]] = []

    if sub == "original":
        # 官方原版 DLL：Windows 与 mac 是两份**不同的 build**，各取各的
        dll = (core.REPO / "hardcore" / "_backup"
               / (core.MAC_ORIG_NAME if sys.platform == "darwin"
                  else core.DLL_NAME + ".orig"))
        if dll.is_file():
            out.append((dll, Path(core.DLL_NAME)))
        return out

    if sub == "bin":
        # 两样都要随包：
        #   langtool      自包含发布版，自带运行时，不需要玩家装 .NET
        #                 （mac 上基本都没装 .NET，所以必须自包含）
        #   classdata.tpk MonoBehaviour 的字段表。langtool **必须**在它旁边
        #                 找到它，否则解析不出字段 —— 实测漏了它会换档失败一半，
        #                 把游戏留在半新半旧的状态。
        if sys.platform == "darwin":
            src = core.REPO / "hardcore" / "langtool" / "pub-osx-x64"
            name = "langtool"
        else:
            src = core.REPO / "hardcore" / "langtool" / "pub-trim"
            name = "langtool.exe"
        if (src / name).is_file():
            out.append((src / name, Path(name)))
        # classdata.tpk 就在发布目录里，优先用那份（开发机的 bin/ 不一定带着）
        if (src / "classdata.tpk").is_file():
            out.append((src / "classdata.tpk", Path("classdata.tpk")))
        else:
            tpk = sorted((core.REPO / "hardcore" / "langtool")
                         .glob("bin/*/net*/*.tpk"))
            if tpk:
                out.append((tpk[0], Path("classdata.tpk")))
        return out

    return out
    # 语言包不必随包 —— 目标是 3（原版）时的文本由指纹表直接给出，
    # 而“还原玩家装过的东西”靠的是启动时对玩家原文件的字节备份。


if __name__ == "__main__":
    sys.exit(main())
