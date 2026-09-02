"""按字素簇切分文本。

sse-streaming-spec §4：按字素簇切分，避免切开多字节字符与组合字符
（表情、变音符、Emoji ZWJ 序列）。切分依据为 Unicode 组合标记与
ZWJ / 变体选择符 / 区域指示符规则，近似 UAX #29 无需第三方依赖。
"""

import unicodedata

_ZWJ = "‍"
_VS_START = "︀"
_VS_END = "️"
_RI_START = "\U0001f1e6"
_RI_END = "\U0001f1ff"
_CONTINUATION_CATEGORIES = frozenset({"Mn", "Me", "Sk"})


def _is_continuation(category: str, ch: str) -> bool:
    if category in _CONTINUATION_CATEGORIES:
        return True
    if _VS_START <= ch <= _VS_END:
        return True
    return ch == _ZWJ


def split_graphemes(text: str) -> list[str]:
    """按字素簇切分文本为列表（每个元素一个完整字素）。"""
    graphemes: list[str] = []
    current = ""
    prev_zwj = False
    prev_ri = False
    for ch in text:
        category = unicodedata.category(ch)
        is_ri = _RI_START <= ch <= _RI_END
        if current and not (_is_continuation(category, ch) or prev_zwj or (prev_ri and is_ri)):
            graphemes.append(current)
            current = ch
        else:
            current += ch
        prev_zwj = ch == _ZWJ
        prev_ri = is_ri
    if current:
        graphemes.append(current)
    return graphemes
