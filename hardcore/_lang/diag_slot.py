"""看一眼某个槽位存档的明文状态（教程标志位、书本进度）。用法：diag_slot.py [P1|P2|P3]"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hardcore"))
from make_envelope_save import load_save                        # noqa: E402
from patcher import core                                        # noqa: E402

slots = sys.argv[1:] or ["P1", "P2", "P3"]
FLAGS = ("helpedBookFatesCheck", "helpedBookFaceClear", "helpedBookFaceBlur",
         "helpedBookDifficulty", "helpedBookUsage", "helpedBookBookmarks")

for s in slots:
    if "/" in s or "\\" in s or s.endswith(".txt"):
        p = Path(s)
    else:
        p = core.slot_path(s)
    print("=" * 70)
    print("%s  %s  (%s)" % (s, p, "存在" if p.is_file() else "**不存在**"))
    if not p.is_file():
        continue
    try:
        _text, xml = load_save(p)
    except Exception as e:                                       # noqa: BLE001
        print("  读不出来: %s: %s" % (type(e).__name__, e))
        continue
    print("  %d B 明文" % len(xml))
    for f in FLAGS:
        m = re.search(r'\b%s="([^"]*)"' % f, xml)
        print("    %-24s %s" % (f, m.group(1) if m else "(缺)"))
    for f in ("era", "playerFemale"):
        m = re.search(r'\b%s="([^"]*)"' % f, xml)
        print("    %-24s %s" % (f, m.group(1) if m else "(缺)"))
    faces = re.findall(r"<face\b[^>]*/>", xml)
    filled_n = sum(1 for t in faces if 'nameId="unknown"' not in t)
    filled_f = sum(1 for t in faces if 'fateId="unknown"' not in t)
    print("    faces 共 %d；填了身份 %d；填了下落 %d" % (len(faces), filled_n, filled_f))
    try:
        from make_test_save import crew_fates, face_attr, pending_list   # noqa: PLC0415
        fates = crew_fates()
        pend = pending_list(xml, fates)
        unfilled = [c for c in fates
                    if face_attr(xml, c, "nameId") in (None, "", "unknown")]
        print("    pending（填对但未登记）= %d 人" % len(pend))
        print("    完全没填的            = %d 人  %s" % (len(unfilled), unfilled))
    except Exception as e:                                       # noqa: BLE001
        print("    pending 算不出来: %s: %s" % (type(e).__name__, e))
    # 剧情分区
    for tag in ("ship", "office"):
        m = re.search(r'<%s\b[^>]*>' % tag, xml)
        if m:
            print("    <%s> %s" % (tag, m.group(0)[:110]))
