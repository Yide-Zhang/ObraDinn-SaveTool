"""对比 originalDLLWin 的 DLL 与我们的各版本：四个补丁位点是否可定位。"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from patcher import core                                    # noqa: E402

GAME = Path(r"F:\AceAttorneySeries\gameFiles\steamapps\common\ObraDinn"
            r"\ObraDinn_Data\Managed\Assembly-CSharp.dll")

TARGETS = [
    ("新给的 originalDLLWin", ROOT / "originalDLLWin" / "Assembly-CSharp.dll"),
    ("我们的原版 .orig",      ROOT / "hardcore" / "_backup" / "Assembly-CSharp.dll.orig"),
    ("hardcore/_patched lv4", ROOT / "hardcore" / "_patched" / "lc-lv4.dll"),
    ("随附产物 assets/dll lv4", ROOT / "patcher" / "assets" / "dll" / "lc-lv4.dll"),
    ("游戏里现在那份",        GAME),
    ("Cecil 对照(原版->lv4)",  ROOT / "hardcore" / "_lang" / "_newbuild" / "ctl-lv4.dll"),
    ("Cecil 新build->lv4",     ROOT / "hardcore" / "_lang" / "_newbuild" / "new-lv4.dll"),
]

RE_B2_V = re.compile(rb"\x02\x08\x07\x9a")            # ldarg.0 ldloc.2 ldloc.1 ldelem.ref
RE_B2_P3 = re.compile(rb"\x02\x08\x07\x19\x5d\x9a")   # + ldc.i4.3 rem
RE_B2_P2 = re.compile(rb"\x02\x08\x07\x18\x5d\x9a")   # + ldc.i4.2 rem（规格书锚点表写法）


def find_b1(buf):
    """找 bne.un/br 目标落在 `19 8d`(ldc.i4.3;newarr) 的分支 —— B1 站点。"""
    out = []
    for m in re.finditer(rb"\x18.{0,14}?[\x40\x38]", buf, re.S):
        j = m.end() - 1
        if buf[j] not in (0x40, 0x38):
            continue
        off = j + 5
        tgt = off + int.from_bytes(buf[j + 1:j + 5], "little", signed=True)
        if 0 <= tgt < len(buf) - 1 and buf[tgt:tgt + 2] == b"\x19\x8d":
            out.append((m.start(), j, buf[j], tgt))
    return out


def versions(buf):
    seen = []
    for m in re.finditer(rb"(?<![\d.])(\d\.\d{1,2}\.\d{1,3})(?![\d.])", buf):
        s = m.group(1).decode()
        if s not in seen:
            seen.append(s)
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){4,24}", buf):
        s = m.group(0).decode("utf-16-le", "ignore")
        if re.fullmatch(r"\d\.\d{1,2}\.\d{1,3}", s) and s not in seen:
            seen.append(s)
    return seen


for tag, p in TARGETS:
    print("=" * 78)
    print("%s\n  %s" % (tag, p))
    if not p.is_file():
        print("  不存在")
        continue
    buf = p.read_bytes()
    print("  %d B  sha256=%s" % (len(buf), hashlib.sha256(buf).hexdigest()))

    info = core.probe_dll(p)
    print("  kind=%-8s level=%-4s const=%-4s seal_vanilla=%-5s seal_patched=%s"
          % (info.get("kind"), info.get("level"), info.get("const"),
             info.get("seal_vanilla"), info.get("seal_patched")))

    # A
    a = buf.find(core.CONST_ANCHOR)
    print("  A  锚点@%s  出现 %d 次" % ("0x%06X" % a if a >= 0 else "无",
                                        buf.count(core.CONST_ANCHOR)))
    if a >= 0:
        end = a - 2
        for ln, ch in ((5, 0x20), (2, 0x1F), (1, None)):
            if ch and end - ln >= 0 and buf[end - ln] == ch:
                v = int.from_bytes(buf[end - ln + 1:end], "little", signed=True)
                print("      常量读数 = %d  (ldc.i4 %d 字节)" % (v, ln))
                break
            if ch is None and end - 1 >= 0 and 0x16 <= buf[end - 1] <= 0x1E:
                print("      常量读数 = %d  (ldc.i4.%d)" % (buf[end - 1] - 0x16, buf[end - 1] - 0x16))
                break

    # B1
    b1 = find_b1(buf)
    print("  B1 目标指向 `19 8d` 的分支 %d 处" % len(b1))
    for s, j, op, tgt in b1[:6]:
        print("      ldc.i4.2@0x%06X  %s@0x%06X -> 0x%06X" % (s, "br" if op == 0x38 else "bne.un", j, tgt))
    print("      （原版应为 bne.un=0x40，补丁后应为 br=0x38）")

    # B2
    print("  B2 原版形态 %d 处 / 补丁形态(19 5d) %d 处 / (18 5d) %d 处"
          % (len(RE_B2_V.findall(buf)), len(RE_B2_P3.findall(buf)), len(RE_B2_P2.findall(buf))))

    # C
    sv = core.SEAL_VANILLA_RE.search(buf)
    sp = core.SEAL_PATCHED_RE.search(buf)
    print("  C  原版签名@%s / 补丁签名@%s"
          % ("0x%06X" % sv.start() if sv else "无",
             "0x%06X" % sp.start() if sp else "无"))

    print("  版本号候选: %s" % (versions(buf)[:8] or "无"))
