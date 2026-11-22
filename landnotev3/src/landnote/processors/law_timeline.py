"""法規時效：從全國法規資料庫的修法沿革，判斷文章或考題引用的條文在撰寫後是否修正過。

管線位置（兩段式，與 exam_bank 相同）：
- `build()`：下載全國法規資料庫開放資料（法律、命令各一包 JSON），只留 `LAWS` 內的法規，
  解析沿革成「哪天改了哪些條」，寫 `data/law_timeline.json`（需網路，CI 在產生網站前執行）。
- `LawTimeline`：site_generator、exam_bank 讀 JSON，`stale()` 回傳撰寫日之後被修正的引用條文。

判斷規則：引用到條號（土地法第34條之1）→ 該條在撰寫日後被修正、增訂、刪除或法規修正全文才算；
只寫法名（所得稅法）→ 只有修正全文才算，否則幾乎每篇舊文章都會被標，提醒就失去意義。
"""

import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from landnote.config import LAW_TIMELINE_FILE

MOJ_SOURCES = ["https://law.moj.gov.tw/api/Ch/Law/JSON", "https://law.moj.gov.tw/api/Ch/Order/JSON"]
LAW_SINGLE_URL = "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={flno}"
HISTORY_SINCE = 1990  # 更早的修法對網站上的文章與考題沒有意義

# 追蹤的法規（地政、估價、不動產稅與相關民事法規）；名稱須與全國法規資料庫完全相同
LAWS = [
    "土地法施行法", "土地法", "土地稅法施行細則", "土地稅法", "土地稅減免規則", "平均地權條例施行細則",
    "平均地權條例", "土地登記規則", "地籍測量實施規則", "土地徵收條例施行細則", "土地徵收條例",
    "都市計畫法", "都市更新條例", "都市危險及老舊建築物加速重建條例", "區域計畫法", "國土計畫法",
    "非都市土地使用管制規則", "農業發展條例", "農村社區土地重劃條例", "農地重劃條例", "耕地三七五減租條例",
    "市地重劃實施辦法", "獎勵土地所有權人辦理市地重劃辦法", "區段徵收實施辦法", "國有財產法", "房屋稅條例",
    "契稅條例", "遺產及贈與稅法", "所得稅法", "稅捐稽徵法", "地籍清理條例", "祭祀公業條例",
    "不動產經紀業管理條例", "地政士法", "公寓大廈管理條例", "不動產估價師法", "不動產估價技術規則",
    "地價調查估計規則", "租賃住宅市場發展及管理條例", "住宅法", "建築法", "信託法", "大眾捷運法",
    "行政程序法", "民法", "土地法第34條之1執行要點",
]
_LAW_ALT = "|".join(sorted(map(re.escape, LAWS), key=len, reverse=True))
CN_DIGITS = "一二三四五六七八九十"
CN_NUM = "零〇一二三四五六七八九十百"
_N = rf"[\d{CN_NUM}]+"
# 「土地法第34條之1」「土地法第三十四條之一」「土地法第34-1條」「土地稅法§ 12」「民法 §819-1」
LAW_REF = re.compile(
    rf"({_LAW_ALT})\s*(?:第\s*({_N})\s*(?:[-－]\s*(\d+))?\s*條(?:\s*之\s*({_N}))?|§\s*(\d+)(?:\s*[-－]\s*(\d+))?)?")
REF_PARTS = re.compile(rf"^({_LAW_ALT})(?:第(\d+)條(?:之(\d+))?)?$")


def to_int(s: str) -> int:
    """阿拉伯或中文數字（至百位，如「一百零二」「三十四」）轉整數。"""
    if s.isdigit():
        return int(s)
    total, num = 0, 0
    for ch in s:
        if ch in "零〇":
            continue
        if ch == "百":
            total += (num or 1) * 100
            num = 0
        elif ch == "十":
            total += (num or 1) * 10
            num = 0
        else:
            num = CN_DIGITS.index(ch) + 1
    return total + num


def law_refs(text: str) -> List[str]:
    """抽出法條，統一寫成「土地法第34條之1」；只寫法名未寫條號者回傳法名。依出現順序去重。"""
    seen: Dict[str, None] = {}
    for law, art, dash, sub, sec, sec_sub in LAW_REF.findall(text):
        ref = law
        number, extra = (art, dash or sub) if art else (sec, sec_sub)
        if number:
            ref += f"第{to_int(number)}條" + (f"之{to_int(extra)}" if extra else "")
        seen.setdefault(ref, None)
    return list(seen)


def _split_ref(ref: str) -> Tuple[str, Optional[str]]:
    """「土地法第34條之1」→ ("土地法", "34-1")；只有法名時條號為 None。"""
    m = REF_PARTS.match(ref)
    if not m:
        return ref, None
    if not m.group(2):
        return m.group(1), None
    return m.group(1), m.group(2) + (f"-{m.group(3)}" if m.group(3) else "")


# ---- 解析修法沿革 ----

HISTORY_ENTRY = re.compile(r"^\s*\d+\s*\.", re.M)
ROC_DATE = re.compile(rf"中華民國\s*({_N})\s*年\s*({_N})\s*月\s*({_N})\s*日")
ARTICLE_SPAN = re.compile(r"第\s*([\d\s、，,～~\-]+?)\s*條")


def _expand(span: str) -> List[str]:
    """「6、22～28、40-1、70-1～70-7」→ ["6", "22", …, "28", "40-1", "70-1", …, "70-7"]。"""
    out = []
    for part in re.split(r"[、，,]", re.sub(r"\s+", "", span)):
        if not part:
            continue
        bounds = re.split(r"[～~]", part, maxsplit=1)
        if len(bounds) == 1:
            out.append(part)
            continue
        lo, hi = bounds
        a, b = lo.split("-"), hi.split("-")
        if len(a) == len(b) == 1 and a[0].isdigit() and b[0].isdigit():
            out += [str(n) for n in range(int(a[0]), int(b[0]) + 1)]
        elif len(a) == len(b) == 2 and a[0] == b[0] and a[1].isdigit() and b[1].isdigit():
            out += [f"{a[0]}-{n}" for n in range(int(a[1]), int(b[1]) + 1)]
        else:
            out += [lo, hi]
    return out


def parse_histories(text: str) -> List[dict]:
    """把沿革文字拆成 [{"date": "YYYY-MM-DD", "all": bool, "articles": [...]}]，只留 HISTORY_SINCE 之後。"""
    text = text.replace("\r\n", "\n")
    starts = [m.start() for m in HISTORY_ENTRY.finditer(text)] or [0]
    out = []
    for a, b in zip(starts, starts[1:] + [len(text)], strict=True):
        entry = re.sub(r"\s*\n\s*", "", text[a:b])
        m = ROC_DATE.search(entry)
        if not m:
            continue
        year = to_int(m.group(1)) + 1911
        if year < HISTORY_SINCE:
            continue
        # 「公告…改由…管轄」是機關改名，不是修法，從第一個「公告」之後截掉
        body = entry[m.end():].split("公告", 1)[0]
        if not re.search(r"公布|發布", body):
            continue
        articles = sorted({x for s in ARTICLE_SPAN.findall(body) for x in _expand(s)})
        out.append({
            "date": f"{year:04d}-{to_int(m.group(2)):02d}-{to_int(m.group(3)):02d}",
            "all": bool(re.search(r"全文", body)),
            "articles": articles,
        })
    return out


def build(out_file: Path = LAW_TIMELINE_FILE) -> Path:
    """下載全國法規資料庫開放資料，寫出追蹤法規的修法時間軸。"""
    import requests

    laws: Dict[str, dict] = {}
    updated = ""
    for url in MOJ_SOURCES:
        resp = requests.get(url, timeout=180)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".json"))
            data = json.loads(z.read(name).decode("utf-8-sig"))
        updated = max(updated, str(data.get("UpdateDate", "")))
        for law in data["Laws"]:
            if law["LawName"] not in LAWS or law["LawAbandonNote"]:
                continue
            pcode = re.search(r"pcode=(\w+)", law["LawURL"])
            laws[law["LawName"]] = {
                "url": law["LawURL"],
                "pcode": pcode.group(1) if pcode else "",
                "amendments": parse_histories(law["LawHistories"]),
            }
    if not laws:
        raise RuntimeError("全國法規資料庫回傳的資料中找不到任何追蹤法規")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({"source_updated": updated, "laws": laws}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return out_file


# ---- 查詢 ----

class LawTimeline:
    """讀 law_timeline.json；檔案不存在時 `stale()` 一律回空，網站照常產生。"""

    def __init__(self, data_file: Path = LAW_TIMELINE_FILE):
        self.laws: Dict[str, dict] = {}
        if data_file.exists():
            self.laws = json.loads(data_file.read_text(encoding="utf-8"))["laws"]

    def __bool__(self) -> bool:
        return bool(self.laws)

    def stale(self, refs: List[str], as_of: date) -> List[dict]:
        """回傳 as_of 之後被修正的引用：[{"ref", "date"（最近一次相關修正）, "url"}]，依引用順序。"""
        cutoff = as_of.isoformat()
        out = []
        for ref in refs:
            law, article = _split_ref(ref)
            info = self.laws.get(law)
            if not info:
                continue
            hits = [a["date"] for a in info["amendments"] if a["date"] > cutoff
                    and (a["all"] or (article is not None and article in a["articles"]))]
            if not hits:
                continue
            url = info["url"]
            if article and info.get("pcode"):
                url = LAW_SINGLE_URL.format(pcode=info["pcode"], flno=article)
            out.append({"ref": ref, "date": max(hits), "url": url})
        return out

    def notice(self, text: str, as_of: date, lead: str, limit: int = 6) -> List[str]:
        """產生 Markdown 提醒（admonition）行；沒有需要提醒的條文時回空。

        lead 是提醒開頭，例如「本文發布（2016-09-08）後，文中引用的」「本題出題（民國 105 年）後，題目引用的」。
        """
        items = self.stale(law_refs(text), as_of)
        if not items:
            return []
        shown = "、".join(f"[{i['ref']}]({i['url']})（{i['date']} 修正）" for i in items[:limit])
        more = f"等 {len(items)} 項" if len(items) > limit else ""
        return [
            '!!! warning "法規可能已修正"',
            f"    {lead} {shown}{more}有修正，內容可能與現行規定不同，請以全國法規資料庫的現行條文為準。",
            "",
        ]
