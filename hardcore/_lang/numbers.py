#!/usr/bin/env python3
"""各语言的「人数」措辞表 —— 用于替换 4 个文案键里写死的「三」。

要改的键（扫描确认，见 hardcore/_dump/scan_num3_all.txt）：
    welldone_3_first, welldone_3_more          形态 W
    help_faceclear_fates0                      形态 S0
    help_faceclear_fates1                      形态 S1

每张表是 {3: 原文里的词, 4/6/9/14/29/58: 替换词}。
替换方式：把该键的值里**所有**出现的「3 的那个词」按词边界换成目标词。
（西语 "de tres en tres" 有两处、都会换成 "de cuatro en cuatro"，所以是「全部替换」。）

数字样式与游戏保持一致：
    ja / ko 用**阿拉伯数字**；其余语言用**数词**。
    de 的 fates0 用 "zu dritt" 这种与格惯用式，所以 S0 单独一张表。
    ru 的 fates0（属格）与 fates1（宾格）在 6 以上会分叉，也单独处理。

ar 存的是**表现形**（U+FE70–FEFF）：先把值 NFKC 规范化再替换，最后整体 reshape 写回。
    ★ 已验证：这 4 个键的 reshape 能**逐字还原**原文（见 hardcore/_dump/ar_reshaping.txt）。
"""
from __future__ import annotations

import re
import unicodedata

# 中日韩没有词边界（汉字/假名本身就是 word 字符），只能用子串匹配
CJK_LANGS = frozenset({"ja", "ko", "zh-s", "zh-t"})

def _replace(lang: str, text: str, old: str, new: str) -> tuple[str, int]:
    """按词边界替换（中日韩用子串）。返回 (新串, 替换次数)。

    ★ 必须用词边界：意大利语 "Altre tre sorti" 里，子串匹配会把 **Altre**
      里的 tre 也当成原词，得到 "Alcinquantotto cinquantotto"。
    """
    if lang in CJK_LANGS:
        return text.replace(old, new), text.count(old)
    pat = re.compile(r"\b" + re.escape(old) + r"\b")
    n = len(pat.findall(text))
    # 用 lambda 作替换值，避免 new 里的 \ 被当成反向引用
    return pat.sub(lambda _m: new, text), n

LEVELS = (4, 6, 9, 14, 29, 58)

KEY_SHAPE = {
    "welldone_3_first": "W",
    "welldone_3_more": "W",
    "help_faceclear_fates0": "S0",
    "help_faceclear_fates1": "S1",
}

# ---------------------------------------------------------------- 措辞表
NUMBERS: dict[str, dict[str, dict[int, str]]] = {
    "ar": {
        "W":  {3: "ثلاثة", 4: "أربعة", 6: "ستة", 9: "تسعة",
               14: "أربعة عشر", 29: "تسعة وعشرون", 58: "ثمانية وخمسون"},
        "S0": {3: "ثلاثة", 4: "أربعة", 6: "ستة", 9: "تسعة",
               14: "أربعة عشر", 29: "تسعة وعشرون", 58: "ثمانية وخمسون"},
        "S1": {3: "ثلاثة", 4: "أربعة", 6: "ستة", 9: "تسعة",
               14: "أربعة عشر", 29: "تسعة وعشرون", 58: "ثمانية وخمسون"},
    },
    "de": {
        "W":  {3: "Drei", 4: "Vier", 6: "Sechs", 9: "Neun",
               14: "Vierzehn", 29: "Neunundzwanzig", 58: "Achtundfünfzig"},
        # "Schicksale werden immer zu dritt bestätigt."
        # ★ 原词取 "zu dritt"（含介词），替换成 "in Gruppen von N" —— 否则 "zu 14" 不成话。
        #   （"zu vierzehnt" 这类只到十位数还行，再往上就不通顺了。）
        "S0": {3: "zu dritt", 4: "in Gruppen von vier", 6: "in Gruppen von sechs",
               9: "in Gruppen von neun", 14: "in Gruppen von vierzehn",
               29: "in Gruppen von neunundzwanzig", 58: "in Gruppen von achtundfünfzig"},
        "S1": {3: "drei", 4: "vier", 6: "sechs", 9: "neun",
               14: "vierzehn", 29: "neunundzwanzig", 58: "achtundfünfzig"},
    },
    "en": {
        "W":  {3: "Three", 4: "Four", 6: "Six", 9: "Nine",
               14: "Fourteen", 29: "Twenty-nine", 58: "Fifty-eight"},
        "S0": {3: "three", 4: "four", 6: "six", 9: "nine",
               14: "fourteen", 29: "twenty-nine", 58: "fifty-eight"},
        "S1": {3: "three", 4: "four", 6: "six", 9: "nine",
               14: "fourteen", 29: "twenty-nine", 58: "fifty-eight"},
    },
    "es": {
        "W":  {3: "Tres", 4: "Cuatro", 6: "Seis", 9: "Nueve",
               14: "Catorce", 29: "Veintinueve", 58: "Cincuenta y ocho"},
        # "de tres en tres" —— 两处 "tres" 都替换
        "S0": {3: "tres", 4: "cuatro", 6: "seis", 9: "nueve",
               14: "catorce", 29: "veintinueve", 58: "cincuenta y ocho"},
        "S1": {3: "tres", 4: "cuatro", 6: "seis", 9: "nueve",
               14: "catorce", 29: "veintinueve", 58: "cincuenta y ocho"},
    },
    "fr": {
        "W":  {3: "Trois", 4: "Quatre", 6: "Six", 9: "Neuf",
               14: "Quatorze", 29: "Vingt-neuf", 58: "Cinquante-huit"},
        "S0": {3: "trois", 4: "quatre", 6: "six", 9: "neuf",
               14: "quatorze", 29: "vingt-neuf", 58: "cinquante-huit"},
        "S1": {3: "trois", 4: "quatre", 6: "six", 9: "neuf",
               14: "quatorze", 29: "vingt-neuf", 58: "cinquante-huit"},
    },
    "it": {
        "W":  {3: "Tre", 4: "Quattro", 6: "Sei", 9: "Nove",
               14: "Quattordici", 29: "Ventinove", 58: "Cinquantotto"},
        "S0": {3: "tre", 4: "quattro", 6: "sei", 9: "nove",
               14: "quattordici", 29: "ventinove", 58: "cinquantotto"},
        "S1": {3: "tre", 4: "quattro", 6: "sei", 9: "nove",
               14: "quattordici", 29: "ventinove", 58: "cinquantotto"},
    },
    "ja": {          # 阿拉伯数字
        "W":  {3: "3名", 4: "4名", 6: "6名", 9: "9名", 14: "14名", 29: "29名", 58: "58名"},
        "S0": {3: "3件", 4: "4件", 6: "6件", 9: "9件", 14: "14件", 29: "29件", 58: "58件"},
        "S1": {3: "3名", 4: "4名", 6: "6名", 9: "9名", 14: "14名", 29: "29名", 58: "58名"},
    },
    "ko": {          # 阿拉伯数字
        "W":  {3: "3개", 4: "4개", 6: "6개", 9: "9개", 14: "14개", 29: "29개", 58: "58개"},
        "S0": {3: "3명", 4: "4명", 6: "6명", 9: "9명", 14: "14명", 29: "29명", 58: "58명"},
        "S1": {3: "3명", 4: "4명", 6: "6명", 9: "9명", 14: "14명", 29: "29명", 58: "58명"},
    },
    "pl": {
        "W":  {3: "trzech", 4: "czterech", 6: "sześciu", 9: "dziewięciu",
               14: "czternastu", 29: "dwudziestu dziewięciu", 58: "pięćdziesięciu ośmiu"},
        # "Losy są zatwierdzane trójkami." -> 换成普适的「w grupach po N」
        "S0": {3: "trójkami", 4: "w grupach po cztery", 6: "w grupach po sześć",
               9: "w grupach po dziewięć", 14: "w grupach po czternaście",
               29: "w grupach po dwadzieścia dziewięć", 58: "w grupach po pięćdziesiąt osiem"},
        "S1": {3: "trzech", 4: "czterech", 6: "sześciu", 9: "dziewięciu",
               14: "czternastu", 29: "dwudziestu dziewięciu", 58: "pięćdziesięciu ośmiu"},
    },
    "pt": {
        "W":  {3: "Três", 4: "Quatro", 6: "Seis", 9: "Nove",
               14: "Catorze", 29: "Vinte e nove", 58: "Cinquenta e oito"},
        "S0": {3: "três", 4: "quatro", 6: "seis", 9: "nove",
               14: "catorze", 29: "vinte e nove", 58: "cinquenta e oito"},
        "S1": {3: "três", 4: "quatro", 6: "seis", 9: "nove",
               14: "catorze", 29: "vinte e nove", 58: "cinquenta e oito"},
    },
    "ru": {
        # "Участь троих определена верно."
        "W":  {3: "троих", 4: "четверых", 6: "шестерых", 9: "девятерых",
               14: "четырнадцати", 29: "двадцати девяти", 58: "пятидесяти восьми"},
        # "участи трех человек" —— 属格
        "S0": {3: "трех", 4: "четырех", 6: "шести", 9: "девяти",
               14: "четырнадцати", 29: "двадцати девяти", 58: "пятидесяти восьми"},
        # "хотя бы трех человек" —— 宾格（6 以上与属格分叉）
        "S1": {3: "трех", 4: "четырех", 6: "шесть", 9: "девять",
               14: "четырнадцать", 29: "двадцать девять", 58: "пятьдесят восемь"},
    },
    "uk": {
        "W":  {3: "три", 4: "чотири", 6: "шість", 9: "дев'ять",
               14: "чотирнадцять", 29: "двадцять дев'ять", 58: "п'ятдесят вісім"},
        "S0": {3: "три", 4: "чотири", 6: "шість", 9: "дев'ять",
               14: "чотирнадцять", 29: "двадцять дев'ять", 58: "п'ятдесят вісім"},
        "S1": {3: "три", 4: "чотири", 6: "шість", 9: "дев'ять",
               14: "чотирнадцять", 29: "двадцять дев'ять", 58: "п'ятдесят вісім"},
    },
    "zh-s": {
        "W":  {3: "三个", 4: "四个", 6: "六个", 9: "九个",
               14: "十四个", 29: "二十九个", 58: "五十八个"},
        "S0": {3: "三个", 4: "四个", 6: "六个", 9: "九个",
               14: "十四个", 29: "二十九个", 58: "五十八个"},
        "S1": {3: "三人", 4: "四人", 6: "六人", 9: "九人",
               14: "十四人", 29: "二十九人", 58: "五十八人"},
    },
    "zh-t": {
        "W":  {3: "三人", 4: "四人", 6: "六人", 9: "九人",
               14: "十四人", 29: "二十九人", 58: "五十八人"},
        "S0": {3: "三人", 4: "四人", 6: "六人", 9: "九人",
               14: "十四人", 29: "二十九人", 58: "五十八人"},
        "S1": {3: "三人", 4: "四人", 6: "六人", 9: "九人",
               14: "十四人", 29: "二十九人", 58: "五十八人"},
    },
}

LANGS = tuple(sorted(NUMBERS))


def _ar_reshape(text: str) -> str:
    import arabic_reshaper
    return arabic_reshaper.reshape(text)


def make_value(lang: str, key: str, level: int, original: str) -> str:
    """把 original 里对应形态的「三」换成 level 对应的写法。

    ar 走「NFKC 规范化 -> 替换 -> 整体 reshape」；其余语言直接替换。
    """
    table = NUMBERS[lang][KEY_SHAPE[key]]
    old, new = table[3], table[level]
    if old == new:
        return original

    if lang == "ar":
        norm = unicodedata.normalize("NFKC", original)
        if norm.count(old) != 1:
            raise ValueError("ar %s: 规范化后 %r 出现 %d 次（应为 1）"
                             % (key, old, norm.count(old)))
        return _ar_reshape(norm.replace(old, new))

    # 同一个 W 形态在两个键里可能大小写不同：_first 多半句首（"Tres"），
    # _more 在句中（"Otros tres sinos..."、"Altre tre sorti..."）。
    # 依次试 原样 / 全小写 / 首字母大写，让替换词的大小写跟随**实际出现**的那个。
    for cand, tok in ((old, new),
                      (old.lower(), new.lower()),
                      (old[:1].upper() + old[1:], new[:1].upper() + new[1:])):
        if not cand:
            continue
        text, n = _replace(lang, original, cand, tok)
        if n:
            return text

    raise ValueError("%s %s: 找不到原词 %r（大小写变体也没有）" % (lang, key, old))


if __name__ == "__main__":
    print("语言数: %d   %s" % (len(LANGS), ", ".join(LANGS)))
    print("档位  : %s（3 = 原版，不改）" % ", ".join(map(str, LEVELS)))
