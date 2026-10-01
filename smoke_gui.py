#!/usr/bin/env python3
"""对正在运行的 GUI 做一次冒烟测试（dev 服务或打包后的 exe 都能测）。

    python smoke_gui.py                              # 默认测 http://127.0.0.1:8722
    python smoke_gui.py http://127.0.0.1:8903
    python smoke_gui.py http://127.0.0.1:8903 --import-preset WIN --slot P2

`--import-preset` 会真的调 `/api/import`。为避免动到玩家的真实存档，
脚本**只在这个槽位当前内容与预制存档逐字节相同时**才执行 ——
那样写入的内容完全一样，是零风险的“真跑一遍”。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

KEY_TO_FILE = {
    "LOSE": "ObraDinnSave-END-FAIL.txt",
    "MID": "ObraDinnSave-END-MID.txt",
    "WIN": "ObraDinnSave-END-WIN.txt",
    "BLANK": "ObraDinnSave-BLANK.txt",
    "KILLERCAPTAIN": "ObraDinnSave-KILLERCAPTAIN.txt",
}

ok_all = True


def say(ok: bool, msg: str) -> None:
    global ok_all
    ok_all = ok_all and ok
    print(f"  [{'OK' if ok else 'X '}] {msg}")


def get(base: str, path: str, method: str = "GET"):
    req = urllib.request.Request(base.rstrip("/") + path, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read()
        return r.status, dict(r.headers), body


def post(base: str, path: str, payload: dict):
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8722")
    ap.add_argument("--import-preset", choices=sorted(KEY_TO_FILE))
    ap.add_argument("--slot", default="P2", choices=["P1", "P2", "P3"])
    ap.add_argument("--quit", action="store_true",
                    help="最后测「退出程序」（会真的关掉服务，别对自己的开发服务器用）")
    a = ap.parse_args()

    print(f"[i] 目标 {a.base}")
    _, _, body = get(a.base, "/api/state")
    st = json.loads(body)
    say(st.get("ok") is True, f"/api/state ok  app={st['app']['name']} {st['app']['version']}")
    print(f"      存档目录 {st['saveDir']}")
    print(f"      存档库   {st['libraryDir']}  ({len(st['library'])} 个)")

    print("\n--- 预制存档 ---")
    pre = st.get("presets") or []
    say(len(pre) == 5, f"数量 {len(pre)}（应为 5）")
    expect = {v: k for k, v in KEY_TO_FILE.items()}
    for r in pre:
        key = expect.get(r["name"], "?")
        say(r.get("ok") is True and bool(r.get("comment")),
            f"{key:<14} {r['name']:<34} {r.get('comment','')}  "
            f"{r['bytes']} B  {r['info']['fates_correct']}/{r['info']['crew_total']}")
    say(all(not r["path"].lower().startswith(st["libraryDir"].lower()) for r in pre),
        "预制存档不在存档库里（是独立的只读板块）")

    print("\n--- 字体 ---")
    for f in ("IMFeENrm28P.ttf", "SourceHanSerifSC-SemiBold-subset.otf"):
        code, h, _ = get(a.base, f"/fonts/{f}", "HEAD")
        say(code == 200, f"{f}  {code}  {int(h.get('Content-Length', 0)) // 1024} KB")

    print("\n--- 备份 ---")
    _, _, body = get(a.base, "/api/backups?slot=P1")
    bk = json.loads(body)["backups"]
    print(f"      P1 备份 {len(bk)} 条")
    for r in bk[:3]:
        say(r.get("ok") is True, f"{r['name']:<38} {r.get('info', {}).get('fates_correct', r.get('error'))}")

    if a.import_preset:
        fname = KEY_TO_FILE[a.import_preset]
        row = next(r for r in pre if r["name"] == fname)
        slot = next(s for s in st["slots"] if s["slot"] == a.slot)
        print(f"\n--- 装到 {a.slot}（{a.import_preset}）---")
        if not slot.get("exists"):
            say(True, f"{a.slot} 是空槽位，直接装")
        elif slot["info"]["sha256"] == row["info"]["sha256"]:
            say(True, f"{a.slot} 当前内容与预制存档逐字节相同 —— 写入是零风险的")
        else:
            print(f"      [跳过] {a.slot} 现在不是这份预制存档"
                  f"（{slot['info']['sha256_16']} != {row['info']['sha256_16']}），不动玩家存档")
            return 0 if ok_all else 1
        code, res = post(a.base, "/api/import", {"slot": a.slot, "path": row["path"]})
        say(code == 200 and res.get("ok"), f"导入于 {res.get('dst')}，自动备份 {len(res.get('backups', []))} 份")
        _, _, body = get(a.base, "/api/state")
        after = next(s for s in json.loads(body)["slots"] if s["slot"] == a.slot)
        say(after["info"]["sha256"] == row["info"]["sha256"],
            f"{a.slot} 回读哈希 = 预制存档哈希 ({after['info']['sha256_16']})")

    if a.quit:
        print("\n--- 退出程序 ---")
        code, res = post(a.base, "/api/quit", {})
        say(code == 200 and res.get("ok"), f"/api/quit -> {code}")
        time.sleep(1.5)
        try:
            get(a.base, "/api/state")
            say(False, "服务仍在运行（退出没生效）")
        except Exception as e:                          # noqa: BLE001
            say(True, f"服务已关闭（{type(e).__name__}）")

    print(f"\n{'[结论] 全部通过' if ok_all else '[结论] 有失败项'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
