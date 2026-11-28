"""大法官解釋（釋字）與憲法法庭判決（憲判字）的字號擷取，供逐題讀把題目、文章、法條串到同一號解釋。

只做文字擷取，頁面由 exam_reader.write_pages 產生（同 law_timeline.law_refs 與法條頁的分工）。
字號統一成「釋字第400號」「112年憲判字第20號」，各種寫法（司法院釋字第400號、大法官會議解釋第400號、
釋字400、釋字第四○○號、釋字第400、440號）都歸到同一號。
"""

import re
from typing import Dict, Iterator, List, Optional, Tuple

INTERP_LAST = 813  # 釋字到第 813 號為止，111 年起改為憲法法庭判決（憲判字）
_NUM = r"[\d〇○零一二三四五六七八九十百]+"
INTERP_RE = re.compile(
    rf"釋字\s*(?:第\s*)?(?P<a>{_NUM})\s*號?"
    rf"|大法官(?:會議)?解釋\s*第\s*(?P<b>{_NUM})\s*號"
    rf"|司法院(?:大法官)?(?:會議)?\s*第\s*(?P<c>{_NUM})\s*號解釋"
    r"|(?P<y>1[1-9]\d)\s*年度?\s*憲判字\s*第\s*(?P<j>\d+)\s*號"
)
# 「釋字第400、440號」「釋字第400號及第440號」的後續號次
_MORE_RE = re.compile(rf"\s*[、及與和]\s*(?:釋字)?\s*(?:第\s*)?(?P<n>{_NUM})\s*號?")
_CN_DIGIT = {c: i for i, c in enumerate("零一二三四五六七八九")} | {"〇": 0, "○": 0}

JUDGMENT_LIST_URL = "https://cons.judicial.gov.tw/judcurrentNew1.aspx?fid=38"


def _num(s: str) -> Optional[int]:
    """「400」「四○○」「五五二」「四百零九」→ 整數；無法解析回 None。"""
    if s.isdigit():
        return int(s)
    if "百" in s or "十" in s:
        total = cur = 0
        for ch in s:
            if ch in _CN_DIGIT:
                cur = _CN_DIGIT[ch]
            elif ch == "十":
                total, cur = total + (cur or 1) * 10, 0
            elif ch == "百":
                total, cur = total + cur * 100, 0
        return total + cur
    digits = [_CN_DIGIT.get(ch) for ch in s]
    return int("".join(map(str, digits))) if digits and None not in digits else None


def _interp_key(n: Optional[int]) -> Optional[str]:
    return f"釋字第{n}號" if n and 1 <= n <= INTERP_LAST else None


def iter_interps(text: str) -> Iterator[Tuple[int, int, str]]:
    """逐一回傳 (起點, 終點, 字號)；並列的後續號次各自一個區段（文章改連結時每個號碼各連各的）。"""
    for m in INTERP_RE.finditer(text):
        if m.group("y"):
            yield m.start(), m.end(), f"{m.group('y')}年憲判字第{int(m.group('j'))}號"
            continue
        key = _interp_key(_num(m.group("a") or m.group("b") or m.group("c")))
        if not key:
            continue
        yield m.start(), m.end(), key
        if not m.group("a"):
            continue
        pos = m.end()
        while True:
            more = _MORE_RE.match(text, pos)
            if not more:
                break
            k = _interp_key(_num(more.group("n")))
            if not k:
                break
            yield more.start("n"), more.end(), k
            pos = more.end()


def interp_refs(text: str) -> List[str]:
    """文字中提到的解釋字號，依出現順序去重。"""
    return list(dict.fromkeys(key for _, _, key in iter_interps(text)))


_MD_NOISE = re.compile(r"\*\*|__|^#+\s*|^>\s*|^[-*]\s+", re.M)
_MD_LINK_TEXT = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_HTML_LINK_TEXT = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S | re.I)
_LINK_ONLY_LINE = re.compile(
    r"^[ \t]*(?:<p>)?[ \t]*(?:[-*•][ \t]*)?(?:!?\[[^\]\n]*\]\([^)\n]*\)|<a\b[^>\n]*>.*?</a>)[ \t]*(?:</p>)?[ \t]*$",
    re.M | re.I,
)
EXCERPT_SIDE = 80  # 摘句往前後各最多幾個字


def _plain(text: str) -> str:
    """摘句前先把連結換成連結文字、去掉 HTML 標籤與網址，免得句子切在標籤中間。
    整行只有一個連結的是「相關文章」清單，指的是別篇文章，整行去掉（本文沒談到該號解釋就不列）。"""
    text = _LINK_ONLY_LINE.sub("", text)
    text = _HTML_LINK_TEXT.sub(r"\1", _MD_LINK_TEXT.sub(r"\1", text))
    return re.sub(r"<[^>]+>|https?://\S+", "", text)


def interp_mentions(text: str) -> Dict[str, str]:
    """每號解釋第一次出現的那一句（文章頁「老師怎麼說」用），句子過長時只取字號前後 EXCERPT_SIDE 字。"""
    text = _plain(text)
    out: Dict[str, str] = {}
    headings: Dict[str, str] = {}  # 只出現在標題的，退而用標題
    for start, end, key in iter_interps(text):
        if key in out:
            continue
        ls = text.rfind("\n", 0, start) + 1
        le = text.find("\n", end)
        line = text[ls : le if le != -1 else len(text)].strip()
        if line.startswith(("#", "title:", "- 標題")):
            headings.setdefault(key, re.sub(r"^(?:#+|title:|- 標題：?)\s*(?:[-*•]\s*)?", "", line).strip("'\""))
            continue
        lo = max(max(text.rfind(c, 0, start) for c in "。！？\n") + 1, start - EXCERPT_SIDE)
        hi_cands = [i for i in (text.find(c, end) for c in "。！？\n") if i != -1]
        hi = min(min(hi_cands) + 1 if hi_cands else len(text), end + EXCERPT_SIDE)
        s = re.sub(r"\s+", " ", _MD_NOISE.sub("", text[lo:hi])).strip()
        if lo > 0 and text[lo - 1] not in "。！？\n":
            s = "…" + s
        if hi < len(text) and text[hi - 1] not in "。！？\n":
            s += "…"
        out[key] = s
    for key, s in headings.items():
        out.setdefault(key, s)
    return out


def interp_slug(key: str) -> str:
    """頁面檔名：釋字第400號 → j400；112年憲判字第20號 → c112-20。"""
    m = re.match(r"^釋字第(\d+)號$", key)
    if m:
        return f"j{m.group(1)}"
    m = re.match(r"^(\d+)年憲判字第(\d+)號$", key)
    return f"c{m.group(1)}-{m.group(2)}" if m else key


def interp_sort_key(key: str) -> Tuple[int, int, int]:
    """憲判字（新）在後、各自依號次。"""
    m = re.match(r"^釋字第(\d+)號$", key)
    if m:
        return (0, 0, int(m.group(1)))
    m = re.match(r"^(\d+)年憲判字第(\d+)號$", key)
    return (1, int(m.group(1)), int(m.group(2))) if m else (2, 0, 0)


def interp_url(key: str) -> str:
    """官方全文：釋字有固定網址；憲判字的網址用內部流水號，無法由字號推得，連到判決列表。"""
    m = re.match(r"^釋字第(\d+)號$", key)
    if m:
        return f"https://cons.judicial.gov.tw/jcc/zh-tw/jep03/show?expno={m.group(1)}"
    return JUDGMENT_LIST_URL
