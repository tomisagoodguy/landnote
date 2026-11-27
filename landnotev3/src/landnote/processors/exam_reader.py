"""考古題閱讀版：把考卷 PDF 拆成逐題網頁，附詳解、考點法條與相關老師文章。

管線位置（與 exam_bank 同為兩段式）：
- `build()`：讀 `地政考古題/<科目家族>/*.pdf` → 每個家族寫一個 `data/exam_bank/<slug>.json`（需 pymupdf，
  由 `main.py exambank` 在每月考古題更新後執行）。
- `write_pages()`：site_generator 讀 JSON 與已產生的 blog 文章，比對相關文章後寫 `docs/exam-reader/<slug>/`。
  比對在產生網站時做，文章每週更新後推薦也會跟著更新。

家族清單見 `READERS`；科目歸屬沿用考古題頁的 `SiteGenerator.SUBJECT_FAMILIES`。
詳解來自高點‧高上的 PDF；估價師考卷（考選部原卷、無詳解）已在 exam_bank 題庫，這裡不收。
"""

import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from landnote.config import ARTICLES_DIR, EXAM_READER_DATA_DIR, LAW_ARTICLES_FILE
from landnote.processors.exam_bank import (
    APPRAISAL_TOPICS,
    EXAM_DIR,
    REPO_BLOB,
    SUB_MARKS,
    TOPICS,
    _md_escape,
    _pdf_text,
    best_topic,
    normalize_cjk,
    ocr_cache_path,
    split_questions,
)
from landnote.processors.law_timeline import LawTimeline, law_refs

# (SUBJECT_FAMILIES 的家族名, 網址 slug, 頁面名稱)；slug 的底線版即 JSON 檔名（land-law → land_law.json）
READERS = [
    ("土地法規與土地行政", "land-law", "土地法規"),
    ("不動產估價", "appraisal", "不動產估價"),
    ("不動產投資", "investment", "不動產投資"),
    ("土地經濟與土地政策", "economics", "土地經濟與土地政策"),
    ("土地利用與都市計畫", "land-use", "土地利用與都市計畫"),
    ("民法", "civil-law", "民法"),
    ("土地登記", "registration", "土地登記"),
    ("稅法與政府採購", "tax", "稅法與政府採購"),
]
READER_ROOT = "exam-reader"
DRILL_PAGE = "drill"  # 申論題連續刷題頁：exam-reader/<slug>/drill/
DRILL_CHOICE_PAGE = "drill-choice"  # 測驗題連續刷題頁：exam-reader/<slug>/drill-choice/
TOPIC_DIR = "topics"  # 跨年度比較頁：exam-reader/<slug>/topics/
LAW_DIR = "laws"  # 依法條比較頁：exam-reader/<slug>/laws/

# 跨年度比較的主題：(主題, 核心詞 regex, 一般詞 regex)，計分規則同 exam_bank.best_topic。
# 估價、投資、經濟沿用估價師題庫；其餘三科範圍比估價師的對應科目廣，另訂清單。
LAND_LAW_TOPICS = [
    ("地籍測量與土地登記", r"地籍測量|界址|界標|登記|權利書狀|所有權狀|地籍|測量|複丈|囑託登記|預告登記|塗銷",
     r"地政機關"),
    ("地權與土地使用限制", r"外國人|私有土地|面積最高額|優先購買|優先承買|基地出賣|共有土地|第\s*34\s*條之\s*1|"
     r"空地|荒地|公有土地|撥用|地權", r"所有權|共有"),
    ("房屋與基地、耕地租用", r"基地租用|租用基地|耕地|承租人|出租人|三七五|地租|租約|租賃", r"租"),
    ("地價與土地稅", r"地價稅|增值稅|田賦|房屋稅|契稅|規定地價|申報地價|公告地價|公告土地現值|漲價|原地價|累進|"
     r"稅基|稅率|稅", r"地價|課徵"),
    ("土地徵收與收回", r"(?<!區段)徵收|收回|徵收補償|接連地|需用土地人|徵收計畫", r"補償"),
    ("區段徵收與土地重劃", r"區段徵收|抵價地|市地重劃|農地重劃|農村社區土地重劃|重劃", r"整體開發|共同負擔"),
    ("都市更新、都市計畫與土地使用管制", r"都市更新|權利變換|都市計畫|非都市土地|國土計畫|容積|使用分區|使用地|"
     r"危險及老舊", r"開發|使用"),
    ("行政法與行政救濟", r"訴願|行政訴訟|國家賠償|行政處分|行政程序|行政罰|行政執行|行政契約|聽證|公務員|"
     r"信賴保護|比例原則|法律保留", r"行政|機關"),
    ("不動產交易與經紀", r"地政士|經紀|實價登錄|不動產說明書|預售屋|成交案件|公平交易|消費者保護", r"買賣|交易"),
]
LAND_USE_TOPICS = [
    ("土地利用理論與規劃概念", r"區位|地租|集約|最有效使用|成長管理|智慧成長|緊湊|TOD|大眾運輸導向|土地使用規劃|"
     r"規劃理論|混合使用|土地使用模式|新都市主義|田園城市|總量管制", r"理論|規劃"),
    ("國土計畫與區域計畫", r"國土計畫|國土功能分區|區域計畫|非都市土地|開發許可|使用許可|使用地變更|環境敏感|"
     r"丁種建築用地", r"國土|非都市"),
    ("都市計畫與公共設施", r"都市計畫|細部計畫|主要計畫|公共設施|通盤檢討|使用分區|分區管制|土地使用管制|新市鎮|"
     r"新市區", r"都市"),
    ("容積管理", r"容積", r"送出基地|接受基地"),
    ("土地開發：徵收、重劃與整體開發", r"區段徵收|市地重劃|農地重劃|徵收|跨區|整體開發|抵價地|開發權|土地開發",
     r"開發"),
    ("都市更新與都市再生", r"都市更新|危險及老舊|都市再生|老舊|閒置|再發展|更新", r"更新"),
    ("農地與鄉村地區", r"農地|農業|鄉村|農村|農舍|休耕", r"農"),
    ("環境、防災與永續發展", r"環境|防災|氣候|永續|生態|綠|韌性|碳|淹水|濕地|海岸|水資源|災害|地層下陷",
     r"保育|保護"),
    ("住宅與產業用地", r"住宅|產業園區|工業區|科學園區|產業用地|商業區|物流", r"產業"),
]
CIVIL_LAW_TOPICS = TOPICS["民法物權與不動產法規"][:4] + [
    ("占有", r"占有", r"占有人"),
    ("民法總則：行為能力、意思表示與時效", r"行為能力|意思表示|代理|消滅時效|法律行為|無效|撤銷|錯誤|詐欺|脅迫|"
     r"權利能力|法人|條件|期限", r"總則"),
    ("債編：契約與各種之債", r"契約|買賣|瑕疵|給付|債務不履行|侵權|不當得利|無因管理|租賃|保證|承攬|委任|贈與|"
     r"使用借貸|損害賠償|解除|危險負擔|定金|違約金", r"債|價金"),
    ("親屬與繼承", r"繼承|遺產|夫妻|婚姻|遺囑|剩餘財產|配偶|子女|特留分|拋棄繼承|監護", r"親屬"),
]
REGISTRATION_TOPICS = [
    ("登記制度與基本原則", r"登記制度|強制登記|托崙斯|權利登記制|契據登記|靜態登記|動態登記|合意主義|公示主義|"
     r"日據|形式審查|實質審查|對抗第三人", r"制度|原則"),
    # 「申請」幾乎每題都有，只當一般詞，否則程序類會吸走其他主題的題目
    ("登記申請程序與審查", r"代理|登記原因證明|身分證明|收件|審查|駁回|補正|登記規費|登記費|罰鍰|印鑑|簽證|"
     r"地政士|網路申請|跨所|親自到場", r"申請|程序|機關"),
    ("總登記與第一次登記", r"總登記|第一次登記|無主土地|時效取得|公告期間|異議|測量成果|使用執照", r"第一次"),
    ("所有權移轉與繼承登記", r"移轉登記|買賣|贈與|繼承|遺產|拋棄繼承|遺贈|遺囑|共有物分割|第\s*34\s*條之\s*1|"
     r"逾期未辦|未辦繼承|代位", r"移轉|所有權"),
    ("他項權利登記", r"抵押權|地上權|不動產役權|典權|農育權|耕作權|他項權利|最高限額|權利價值", r"設定"),
    ("標示變更、更正與塗銷登記", r"標示變更|分割|合併|更正登記|更正|塗銷|消滅登記|滅失|住址變更|姓名變更|"
     r"地目|複丈", r"變更"),
    ("限制登記與預告登記", r"限制登記|查封|假扣押|假處分|預告登記|破產登記|囑託登記|囑託|禁止處分", r"限制"),
    ("登記效力與損害賠償", r"公信力|絕對效力|登記錯誤|損害賠償|登記儲金|推定力|登記生效|登記對抗|善意第三人",
     r"效力|賠償"),
    ("信託、區分所有與特殊登記", r"信託|區分所有|公寓大廈|共有部分|共用部分|地籍清理|祭祀公業|寺廟|外國人|"
     r"大陸地區|原住民|夫妻|法人|未登記", r"建物|特殊"),
    ("書狀、謄本與地籍資料", r"權利書狀|所有權狀|書狀|謄本|閱覽|個人資料|地籍資料|電子處理|登記簿|地籍圖",
     r"資料"),
]
TAX_TOPICS = [
    ("地價稅", r"地價稅|申報地價|累進起點|自用住宅用地|公共設施保留地|空地稅|田賦", r"地價"),
    ("土地增值稅", r"增值稅|漲價總數額|原地價|移轉現值|重購退稅|不課徵|農業用地|一生一次|一生一屋", r"漲價"),
    ("房地合一與所得稅", r"所得稅|房地合一|財產交易所得|營利事業|綜合所得|扣除額|免稅額|推計課稅|所得",
     r"申報|課稅所得"),
    ("房屋稅與契稅", r"房屋稅|契稅|房屋現值|房屋標準價格|囤房|非自住", r"房屋"),
    ("遺產及贈與稅", r"遺產稅|贈與稅|遺產總額|贈與總額|不計入遺產|視為遺產|視同贈與", r"遺產|贈與"),
    ("營業稅", r"營業稅|進項稅|銷項稅|加值型|非加值型|統一發票", r"營業人"),
    ("稅捐稽徵與救濟", r"稽徵|核課期間|復查|訴願|行政救濟|滯納金|實質課稅|納稅者權利|欠稅|限制出境|"
     r"租稅法律主義|量能課稅|代繳|稅捐保全", r"稅捐|納稅義務人"),
    ("政府採購", r"採購|招標|決標|履約|驗收|廠商|申訴|底價|押標金|保證金|最有利標|統包", r"機關"),
]
READER_TOPICS = {
    "land-law": LAND_LAW_TOPICS,
    "appraisal": APPRAISAL_TOPICS,
    "investment": TOPICS["不動產投資分析"],
    "economics": TOPICS["不動產經濟學"],
    "land-use": LAND_USE_TOPICS,
    "civil-law": CIVIL_LAW_TOPICS,
    "registration": REGISTRATION_TOPICS,
    "tax": TAX_TOPICS,
}
FILE_NAME = re.compile(r"^\[(\d+)\]\[([^\]]+)\]\[(.+)\]\.pdf$")
MIN_TEXT = 50  # 少於此字數視為掃描檔，只提供原卷連結


def data_file(slug: str, data_dir: Path = EXAM_READER_DATA_DIR) -> Path:
    return data_dir / f"{slug.replace('-', '_')}.json"


def available(data_dir: Path = EXAM_READER_DATA_DIR) -> List[tuple]:
    """已有資料的閱讀版 [(家族名, slug, 頁面名稱)]，順序同 READERS。"""
    return [r for r in READERS if data_file(r[1], data_dir).exists()]

# ---- 解析 ----

# 高點‧高上詳解的頁首頁尾：直排的「高點‧高上」、版權聲明、補習班地址、頁碼
NOISE = re.compile(
    r"^([高點‧・上]|【版權所有.*|.*高分詳解.*|高上高普特考.*|.*www\.get\.com\.tw.*|【(中壢|台中|台南|高雄|另有).*|"
    r"[－\-—]+\s*[－\-—]*|\d{1,2}|第\s*\d+\s*頁.*|（請接背面）|【請接續背面】|背面尚有試題|"
    r"[甲乙丙]、\s*(申論|測驗)題.*|[壹貳參肆]、.*|"
    # 國營事業考卷：「題目二」單獨一行（下一行才是「題目二：」）、頁尾「土地法規 第1頁，共1頁」
    r"題目[一二三四五六七八九十]+|.*第\s*\d+\s*頁\s*[，,]\s*共\s*\d+\s*頁)$"
)
TITLE = re.compile(r"^《(.+)》$")
TOP_MARK = re.compile(r"^(?:題目)?([一二三四五六七八九十]+)\s*[、：:]")
ANSWER = re.compile(r"^答\s*(?:[：:]\s*|$)")
# 答案用全形括號「（B）1.」，選項用半形「(A)」；題號點號有時省略，所以另以題號遞增防誤判
# 少數年份改用半形「(A) 2 」或「(B)1 下列」：括號後有空白，或題號後有空白，與選項「(A)3公畝」區隔。
# 國營事業考卷用「【4】1.」：答案寫成 1–4（選項標記見 GLYPH_OPTION）
CHOICE = re.compile(r"^(?:（\s*(?P<k1>[A-DＡ-Ｄ#＃][A-D、,或]*|一律給分|送分)\s*）\s*"
                    r"|\((?P<k2>[A-D#][A-D、,或]*)\)(?:\s+|(?=\d{1,3}\s))"
                    r"|【(?P<k3>[1-4])】|【(?P<k4>一律給分|送分)[^】]*】)"
                    r"(?P<no>\d{1,3})\s*[.．、]?\s*")
# 少數國營事業考卷有五個選項；括號內偶有空白（「（ C）抵押權」）
OPTION = re.compile(r"[（(]\s?([A-E])\s?[）)]")
BAD_CHOICE_RATIO = 0.3
# 國營事業考卷的選項以圈號字型畫 ①–④，抽出來是控制字元 \x01–\x04（部分年份 \x81–\x84），
# 多在行首，短選項時一行並排兩個（「\x03由基地所有權人決定 \x04以登記之先後定之」）；
# 清理前先換成 (A)–(D)。前面加不可見的 OPTION_MARK，免得「(C) 9 個月」被 CHOICE 當成第 9 題；切選項前移除
GLYPH_OPTION = re.compile(r"(?:^|(?<=\s))[ \t]*([\x01-\x04\x81-\x84])", re.M)
OPTION_MARK = "⁠"
SCORE = re.compile(r"[（(【]\s*(\d+)\s*分\s*[）)】]")
# 考選部原卷申論題的最後一行常黏上測驗題的表頭（「代號：4601①本測驗試題為…」）
HEADER_TAIL = re.compile(r"代號\s*[：:]\s*\d{3,}")
CN_DIGITS = "一二三四五六七八九十"
# 答案內的條列起點：(一) 1. (1) ① 等，遇到就換行，其餘 PDF 斷行直接接回
LIST_START = re.compile(r"^([（(]?([一二三四五六七八九十]+|\d{1,2}|[a-zA-Z])[）).．、]|[①-⑳⑴-⒇])")


def _clean_lines(text: str) -> Tuple[str, List[str]]:
    """去掉頁首頁尾與重複行（舊版 PDF 以重複輸出模擬粗體），回傳 (考卷科目標題, 內文行)。"""
    text = normalize_cjk(text.translate(str.maketrans(SUB_MARKS)))
    # 「（每小題5分，共25分）」統一成「（25分）」，配分才不會漏算
    text = re.sub(r"[（(]\s*每小題[^）)]*?共\s*(\d+)\s*分\s*[）)]", r"（\1分）", text)
    text = re.sub(r"[：:]\s*每小題[^（(\n]*?共\s*(\d+)\s*分", r"（\1分）", text)  # 「解釋名詞：每小題5分，共30分」
    text = GLYPH_OPTION.sub(lambda m: f"{OPTION_MARK}({'ABCD'[(ord(m.group(1)) & 0x0F) - 1]})", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x81]", "", text)
    # 答案「【2】」換頁時常單獨成行，接回下一行的題號，否則整題會被併進前一題；有些年份連括號都斷成「【」「3】」
    text = re.sub(r"【\s*\n\s*([1-4])\s*】", r"【\1】", text)
    text = re.sub(r"^\s*(【[1-4]】)\s*\n\s*", r"\1", text, flags=re.M)
    title, lines, prev = "", [], None
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or ln == prev:
            continue
        prev = ln
        m = TITLE.match(ln)
        if m and not title:
            title = m.group(1)
            continue
        if NOISE.match(ln):
            continue
        lines.append(ln)
    return title, lines


def _join(lines: List[str], structured: bool) -> List[str]:
    """把 PDF 斷行接回段落；structured=True 時遇到條列符號另起一段（用於詳解）。"""
    paras: List[str] = []
    for ln in lines:
        if not paras or (structured and (LIST_START.match(ln) or paras[-1].endswith(("。", "：", ":")))):
            paras.append(ln)
        else:
            paras[-1] += ln
    return paras


def _cn_number(s: str) -> int:
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + CN_DIGITS.index(s[1]) + 1
    if len(s) == 2 and s.endswith("十"):
        return (CN_DIGITS.index(s[0]) + 1) * 10
    if len(s) == 3 and s[1] == "十":  # 二十五
        return (CN_DIGITS.index(s[0]) + 1) * 10 + CN_DIGITS.index(s[2]) + 1
    return CN_DIGITS.index(s[0]) + 1 if len(s) == 1 else 0


def _has_score_ahead(lines: List[str], start: int, window: int = 10) -> bool:
    """試題評析也用「一、二、」條列；往後看到配分（且未先遇到下一個條列）才算題目開頭。"""
    for j in range(start, min(start + window, len(lines))):
        if j > start and (TOP_MARK.match(lines[j]) or ANSWER.match(lines[j])):
            return bool(ANSWER.match(lines[j]))
        if SCORE.search(lines[j]) or re.search(r"分\s*[）)】]", lines[j]):
            return True
    return False


def parse_paper(text: str) -> dict:
    """把一份考卷文字拆成 {commentary, questions:[{no, kind, text, score, answer, options}]}。

    申論題以依序出現的「一、二、」（或「題目一：」）切題，答案從「答：」開始，
    要求題號遞增，避免詳解內的條列「一、」被誤判成新題。選擇題以「（B）1.」開頭。
    考選部原卷（申論＋測驗、測驗無答案）另由 _parse_moex 處理。
    """
    m_moex = MOEX_CHOICE_HEADER.search(text)
    if m_moex and MOEX_OPTIONS[0] in text[m_moex.end():]:
        return _parse_moex(text[:m_moex.start()], text[m_moex.end():])
    _, lines = _clean_lines(text)
    commentary: List[str] = []
    questions: List[dict] = []
    cur: Optional[dict] = None
    mode = "pre"  # pre（試題評析前）/ comment / skip / stem / answer
    expect, expect_choice = 1, 1
    for i, ln in enumerate(lines):
        m_choice = CHOICE.match(ln)
        m_top = TOP_MARK.match(ln)
        if m_choice and int(m_choice.group("no")) == expect_choice:
            expect_choice += 1
            digit = m_choice.group("k3")
            key = "ABCD"[int(digit) - 1] if digit else (
                m_choice.group("k1") or m_choice.group("k2") or m_choice.group("k4"))
            cur = {"no": int(m_choice.group("no")), "kind": "choice",
                   "key": key.translate(str.maketrans("ＡＢＣＤ＃", "ABCD#")),
                   "stem": [ln[m_choice.end():]], "answer": []}
            questions.append(cur)
            mode = "stem"
            continue
        if m_top and _cn_number(m_top.group(1)) == expect and (mode != "comment" or _has_score_ahead(lines, i)):
            cur = {"no": expect, "kind": "essay", "stem": [ln[m_top.end():]], "answer": []}
            questions.append(cur)
            expect += 1
            mode = "stem"
            continue
        if ln.startswith("試題評析"):
            mode = "comment"
            rest = ln[len("試題評析"):].strip()
            if rest:
                commentary.append(rest)
            continue
        if ln.startswith("考點命中"):
            mode = "skip"  # 補習班教材頁碼，對讀者無用
            continue
        # 試題評析有時排在第一題題目之後、「答：」之前
        if cur is not None and cur["kind"] == "essay" and mode != "answer" and ANSWER.match(ln):
            mode = "answer"
            rest = ANSWER.sub("", ln)
            if rest:
                cur["answer"].append(rest)
            continue
        if mode == "comment":
            commentary.append(ln)
        elif cur is not None and mode != "skip":
            (cur["answer"] if mode == "answer" else cur["stem"]).append(ln)

    out = []
    essay_total = 0
    default_score = _header_score(lines)
    for q in questions:
        stem = HEADER_TAIL.split("".join(q["stem"]))[0].replace(OPTION_MARK, "").strip()
        if q["kind"] == "essay":
            score = sum(int(s) for s in SCORE.findall(stem))
            if not score and default_score and essay_total + default_score <= 100:
                score = default_score
            prev = next((o for o in reversed(out) if o["kind"] == "essay"), None)
            # 配分已滿 100 後又出現沒配分的「五、六、」，是前一題詳解裡的條列，併回去
            if not score and essay_total >= 100 and prev:
                prev["answer"] += _join(q["stem"] + q["answer"], structured=True)
                continue
            essay_total += score
        item = {"no": q["no"], "kind": q["kind"], "answer": _join(q["answer"], structured=True)}
        if q["kind"] == "choice":
            item["text"], item["options"] = _split_options(stem)
            item["key"] = q["key"]
            item["score"] = 0
        else:
            item["text"] = stem
            item["score"] = score
        out.append(item)
    # 申論題沒有任何配分代表切題失敗（例如抓到表頭），整份退回只給原卷；
    # 但部分年份的詳解省略配分，每題都接著「答：」時仍是正確切題
    essays = [q for q in out if q["kind"] == "essay"]
    if essays and not any(q["score"] for q in essays) and not all(q["answer"] for q in essays):
        out = [q for q in out if q["kind"] == "choice"]
    # 先刪掉切壞的測驗題（例如選項「（A）1 年」被當成第 1 題），再判斷要不要改用無答案規則
    out = _drop_broken_choices(out)
    # 未附答案的卷子：一般規則拆不出題，或只把卷內「一、選擇題」「二、簡答題」大標題當成申論題時，
    # 改用遞增題號切題；後者要選項大多完整才採用，免得把詳解裡的「1. 2.」條列當成測驗題
    if not any(q["kind"] == "choice" for q in out):
        keyless = _parse_keyless(lines)
        kl_choices = [q for q in keyless if q["kind"] == "choice"]
        complete = sum(len(q["options"]) in (4, 5) for q in kl_choices)
        if not out or (kl_choices and len(keyless) > len(out)
                       and complete >= len(kl_choices) * (1 - BAD_CHOICE_RATIO)):
            out = _drop_broken_choices(keyless)
    return {"commentary": _join(commentary, structured=True), "questions": out}


def _drop_broken_choices(out: List[dict]) -> List[dict]:
    """測驗題多數不是四或五個選項，代表題號或選項沒切對（不支援的排版），寧可只給原卷也不放殘缺題目。"""
    choices = [q for q in out if q["kind"] == "choice"]
    if choices and sum(len(q["options"]) not in (4, 5) for q in choices) > len(choices) * BAD_CHOICE_RATIO:
        return [q for q in out if q["kind"] == "essay"]
    return out


# 考選部原卷（如不動產經紀人）：「甲、申論題」在前、「乙、測驗題部分」在後；
# 測驗題號單獨一行、選項以私用區字元 – 畫 (A)–(D)，試題本身不附答案
MOEX_CHOICE_HEADER = re.compile(r"^\s*[乙丙]、\s*測驗題", re.M)
MOEX_OPTIONS = ""
MOEX_NOISE = re.compile(r"^(代號\s*[：:]|頁次\s*[：:]|※|座號|全一頁|（請接背面）|（背面）)")


def _parse_moex(essay_text: str, choice_text: str) -> dict:
    """考選部原卷：申論段用一般規則（題號是圖片時改以配分切題），測驗段以單獨成行的遞增題號切題。"""
    head = parse_paper(essay_text)
    essays = [q for q in head["questions"] if q["kind"] == "essay"]
    if not essays:
        # 題號是圖片時以配分切題，會把小題「②…（13 分）」切成獨立一題，開頭是第二個以後小題的併回前一題
        texts: List[str] = []
        for t in split_questions(essay_text):
            if texts and re.match(r"^[②-⑩⑵-⑽]", t):
                texts[-1] += "\n" + t
            else:
                texts.append(t)
        essays = [{"no": i, "kind": "essay", "answer": [], "text": t,
                   "score": sum(int(s) for s in SCORE.findall(t))}
                  for i, t in enumerate(texts, 1)]
    text = choice_text.translate(str.maketrans({c: f"({'ABCD'[i]})" for i, c in enumerate(MOEX_OPTIONS)}))
    text = normalize_cjk(text.translate(str.maketrans(SUB_MARKS)))
    qs: List[dict] = []
    expect = 1
    for ln in (ln.strip() for ln in text.splitlines()):
        if not ln or MOEX_NOISE.match(ln):
            continue
        if re.fullmatch(r"\d{1,3}", ln) and int(ln) == expect:
            qs.append({"no": expect, "stem": []})
            expect += 1
        elif qs:
            qs[-1]["stem"].append(ln)
    choices = []
    for q in qs:
        stem, options = _split_options("".join(q["stem"]))
        choices.append({"no": q["no"], "kind": "choice", "answer": [], "text": stem, "options": options,
                        "key": None, "score": 0})
    return {"commentary": head["commentary"], "questions": essays + _drop_broken_choices(choices)}


# 國營事業考卷常只在注意事項寫一次配分（「每大題各占二十五分」「每大題配分20 分」），題目後不再標
HEADER_SCORE = re.compile(r"每大題\s*(?:各占|配分|均為|各)*\s*(\d+|[一二三四五六七八九十]+)\s*分")


def _header_score(lines: List[str]) -> int:
    """卷首注意事項寫的每大題配分；沒寫回傳 0。只認「每大題」，「每題 2 分」多半是測驗題配分。"""
    for ln in lines[:40]:
        m = HEADER_SCORE.search(ln)
        if m:
            n = m.group(1)
            return int(n) if n.isdigit() else _cn_number(n)
    return 0


# 未附答案的試卷（多為國營事業）：題號只寫「1.」，不能與詳解條列區分，所以只在一般規則拆不出題時使用
KEYLESS_Q = re.compile(r"^(\d{1,3})\s*[.．、]\s*(?![\d.])")
KEYLESS_Q_NODOT = re.compile(r"^(\d{1,3})\s*(?=[一-鿿])")
# 選擇題後接「二、申論題：…每題10分」，申論題又從「1.」編號
KEYLESS_ESSAY = re.compile(r"^[一二三四]\s*[、.．]\s*(?:非選擇題|申論題|問答題|簡答題)")


def _parse_keyless(lines: List[str]) -> List[dict]:
    """以遞增題號切測驗題，答案留空。卷首注意事項也編「1. 2.」，再遇到「1.」而前面都沒有選項時整批捨棄重來。"""
    qs: List[dict] = []
    cur: Optional[dict] = None
    expect, kind, essay_score = 1, "choice", 0
    for ln in lines:
        if qs and kind == "choice" and KEYLESS_ESSAY.match(ln):
            kind, expect, cur = "essay", 1, None
            m = re.search(r"每題\s*(\d+)\s*分", ln)
            essay_score = int(m.group(1)) if m else 0
            continue
        prev_done = kind == "choice" and cur is not None and OPTION.search("".join(cur["stem"]))
        # 少數原卷題號後漏了點（「41 下列…」）：前一題已有選項時才認，免得把折行開頭的數字當題號
        m = KEYLESS_Q.match(ln) or (KEYLESS_Q_NODOT.match(ln) if prev_done else None)
        if m and int(m.group(1)) == 1 and qs and not any(OPTION.search("".join(q["stem"])) for q in qs):
            qs, expect = [], 1
        no = int(m.group(1)) if m else 0
        # OCR 偶爾整行漏掉某題的題號行：前一題已有選項時允許跳號，漏掉的那題併入前一題（選項數異常會被標出）
        skipped = prev_done and no == expect + 1
        if m and (no == expect or skipped):
            cur = {"no": no, "kind": kind, "stem": [ln[m.end():]]}
            qs.append(cur)
            expect = no + 1
        elif cur is not None:
            cur["stem"].append(ln)
    out = []
    for q in qs:
        if q["kind"] == "essay":
            stem = "".join(q["stem"]).strip()
            out.append({"no": q["no"], "kind": "essay", "answer": [], "text": stem,
                        "score": sum(int(s) for s in SCORE.findall(stem)) or essay_score})
            continue
        text, options = _split_options("".join(q["stem"]).replace(OPTION_MARK, "").strip())
        out.append({"no": q["no"], "kind": "choice", "answer": [], "text": text, "options": options,
                    "key": None, "score": 0})
    return out


def _split_options(stem: str) -> Tuple[str, List[str]]:
    """把測驗題拆成 (題目, 選項)。原卷偶有選項漏了左括號（「…收益課稅B)地價稅」），
    只在前後字母的選項都在、唯獨缺這一個時補回，免得把內文的「B)」誤當選項。"""
    labels = OPTION.findall(stem)
    for prev_c, c, next_c in zip("ABCD", "BCDE", "CDE", strict=False):
        if prev_c in labels and next_c in labels and c not in labels and f"{c})" in stem:
            stem = re.sub(rf"(?<![（(]){c}\)", f"({c})", stem, count=1)
    parts = OPTION.split(stem)
    return parts[0].strip(), [f"({parts[i]}) {parts[i + 1].strip()}" for i in range(1, len(parts) - 1, 2)]


def build(exam_dir: Path = EXAM_DIR, data_dir: Path = EXAM_READER_DATA_DIR) -> List[Path]:
    """掃描 READERS 各家族考卷，每個家族輸出一個閱讀版 JSON；回傳寫出的路徑（無資料的家族略過）。"""
    from landnote.processors.site_generator import SiteGenerator  # 延遲匯入：site_generator 也匯入本模組

    reader_families = {family for family, _, _ in READERS}
    folders: Dict[str, List[Path]] = defaultdict(list)
    for folder in sorted(p for p in exam_dir.iterdir() if p.is_dir()):
        primary = SiteGenerator._subject_family(folder.name)[0]
        folders[primary].append(folder)
        # 跨科考卷（民法與土地法規、土地法與土地相關稅法概要…）也列進名稱符合的其他家族；
        # 主家族沒有逐題讀時不延伸，免得「施工與估價」之類的營建科目被拉進不動產估價
        if primary in reader_families:
            for family, _, pattern in SiteGenerator.SUBJECT_FAMILIES:
                if family in reader_families and family != primary and re.search(pattern, folder.name):
                    folders[family].append(folder)
    written = []
    unparsed: List[str] = []
    for family, slug, _ in READERS:
        out_file = data_file(slug, data_dir)
        known = _known_pdfs(out_file)
        failed: List[str] = []
        papers = _build_family(folders.get(family, []), failed)
        unparsed += [rel for rel in failed if rel not in known]
        if papers:
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(papers, ensure_ascii=False, indent=1), encoding="utf-8")
            written.append(out_file)
    _report_unparsed(list(dict.fromkeys(unparsed)))  # 跨科考卷會出現在多個家族，去重
    return written


def _known_pdfs(out_file: Path) -> set:
    """上一版閱讀版 JSON 已收錄的考卷；只對不在其中的新考卷發拆題失敗警告，舊的已知失敗不重複吵。"""
    if not out_file.exists():
        return set()
    return {p["pdf"] for p in json.loads(out_file.read_text(encoding="utf-8"))}


def _report_unparsed(rels: List[str]) -> None:
    """新考卷有文字卻拆出 0 題（多半是格式變了，規則沒對上）；在 GitHub Actions 中另寫 warning 與執行摘要。"""
    if not rels:
        return
    print(f"有 {len(rels)} 份新考卷抽得到文字卻拆出 0 題（逐題讀只會提供原卷連結）：")
    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    for rel in rels:
        print(f"  {rel}")
        if in_actions:
            print(f"::warning title=考卷拆出 0 題::{rel}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## 新考卷拆出 0 題（{len(rels)} 份）\n\n"
                    "這些 PDF 抽得到文字，但 `exam_reader.parse_paper` 沒拆出任何題目，"
                    "可能是題號、選項或配分格式和以往不同，需要調整拆題規則。\n\n"
                    + "".join(f"- `{rel}`\n" for rel in rels))


def _build_family(folders: List[Path], unparsed: List[str]) -> List[dict]:
    """拆出家族內每份考卷；有文字卻拆出 0 題的考卷路徑附加到 unparsed。"""
    papers = []
    for folder in folders:
        for pdf in sorted(folder.glob("*.pdf")):
            m = FILE_NAME.match(pdf.name)
            if not m or "估價師" in m.group(2):  # 估價師原卷無詳解，已在主題題庫
                continue
            rel = f"{folder.name}/{pdf.name}"
            try:
                text = _pdf_text(pdf)
            except Exception:  # 少數 PDF 損毀打不開，仍保留原卷連結
                text = ""
            has_text = len(text.strip()) >= MIN_TEXT  # 沒文字的掃描檔由 ocr_scanned.py --check 提醒
            parsed = parse_paper(text) if has_text else {"commentary": [], "questions": []}
            if has_text and not parsed["questions"]:
                unparsed.append(rel)
            papers.append({
                "id": f"{m.group(1)}-{hashlib.md5(rel.encode('utf-8')).hexdigest()[:6]}",
                "year": int(m.group(1)),
                "exam": m.group(2),
                "subject": m.group(3),
                "pdf": rel,
                "has_answer": any(q["answer"] or q.get("key") for q in parsed["questions"]),
                "ocr": bool(parsed["questions"]) and ocr_cache_path(pdf).exists(),
                **parsed,
            })
    return papers


# 考點法條：抽取規則與法規清單統一在 law_timeline（法規時效標示也用同一份）


# ---- 相關文章比對（中文字二元組 TF-IDF） ----

ANSWER_MARK = re.compile(r"【(?:解答|擬答|參考答案)】")
ADMONITION = re.compile(r"^!!!.*\n(?:(?: {4}.*)?\n)*", re.M)  # 文章開頭的法規時效提醒
ANSWER_MIN_SIM = 0.5  # 實測同一題 0.85；不同題但同主題約 0.4 以下


def _bigrams(text: str) -> set:
    s = re.sub(r"[^一-鿿A-Za-z0-9]", "", text)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _tokens(text: str) -> List[str]:
    grams = []
    for run in re.findall(r"[一-鿿]+", text):
        grams += [run[i:i + 2] for i in range(len(run) - 1)]
    return grams


class ArticleIndex:
    """以 blog 文章建 TF-IDF 索引；法條完全相同時額外加分。"""

    LAW_BONUS = 0.08
    MIN_SCORE = 0.12

    def __init__(self, posts_dir: Union[Path, List[Path]], articles_dir: Path = ARTICLES_DIR):
        teacher = {}
        for f in articles_dir.glob("*.md"):  # 原始檔名「編號_標題,某某老師.md」
            m = re.match(r"^(\d+)_.*,(.+?)\.md$", f.name)
            if m:
                teacher[m.group(1)] = m.group(2)
        self.docs: List[dict] = []
        df: Counter = Counter()
        raw_tf = []
        dirs = [posts_dir] if isinstance(posts_dir, Path) else posts_dir
        for f in [f for p in dirs for f in sorted(p.glob("*.md"))]:
            text = f.read_text(encoding="utf-8")
            fm = re.match(r"---\n(.*?)\n---\n", text, re.S)
            head = fm.group(1) if fm else ""
            body = text[fm.end():] if fm else text
            body = body.split("## 文章圖片")[0]
            m_title = re.search(r"^title:\s*(.+)$", head, re.M)
            m_slug = re.search(r"^slug:\s*['\"]?([^'\"\n]+)", head, re.M)
            title = m_title.group(1).strip().strip("'\"") if m_title else f.stem
            slug = m_slug.group(1) if m_slug else ""
            author = teacher.get(slug, "Jasper 不動產" if slug.startswith("jasper-") else "")
            tf = Counter(_tokens(title) * 3 + _tokens(body))
            df.update(tf.keys())
            raw_tf.append(tf)
            # path：相對 docs/ 的原始檔路徑（blog/posts/… 或 jasper/posts/…），供頁面連結
            doc = {"file": f.name, "path": f"{f.parent.parent.name}/posts/{f.name}",
                   "title": title, "author": author,
                   "laws": {r for r in law_refs(body) if "第" in r}}
            m_ans = ANSWER_MARK.search(body)
            if m_ans:  # 老師解題文：「題目原文…【解答】…」
                question = ADMONITION.sub("", body[:m_ans.start()])
                doc["answer_grams"] = _bigrams(question)
                doc["answer_md"] = body[m_ans.end():].split("\n---\n")[0].strip()
            self.docs.append(doc)
        n = len(self.docs)
        self.idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
        self.postings: Dict[str, List[Tuple[int, float]]] = defaultdict(list)
        for i, tf in enumerate(raw_tf):
            vec = {t: (1 + math.log(c)) * self.idf[t] for t, c in tf.items()}
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            for t, v in vec.items():
                self.postings[t].append((i, v / norm))

    def related(self, text: str, laws: List[str], k: int = 3) -> List[dict]:
        tf = Counter(_tokens(text))
        vec = {t: (1 + math.log(c)) * self.idf[t] for t, c in tf.items() if t in self.idf}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        scores: Dict[int, float] = defaultdict(float)
        for t, v in vec.items():
            for i, w in self.postings[t]:
                scores[i] += v / norm * w
        specific = {r for r in laws if "第" in r}
        for i, d in enumerate(self.docs):
            hit = len(specific & d["laws"])
            if hit and i in scores:
                scores[i] += self.LAW_BONUS * hit
        best = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
        return [{**self.docs[i], "score": round(s, 3)} for i, s in best if s >= self.MIN_SCORE]

    def teacher_answer(self, text: str) -> Optional[dict]:
        """找出題目原文與考題幾乎相同的老師解題文（字二元組 Jaccard ≥ ANSWER_MIN_SIM）。"""
        q = _bigrams(SCORE.sub("", text))
        best, best_sim = None, ANSWER_MIN_SIM
        for d in self.docs:
            a = d.get("answer_grams")
            if a and q:
                sim = len(q & a) / len(q | a)
                if sim >= best_sim:
                    best, best_sim = d, sim
        return best


def teacher_answer_md(doc: dict, depth: int) -> List[str]:
    """老師擬答的可收合區塊；depth 為頁面相對 docs/ 的目錄深度（圖片路徑要往上幾層）。"""
    up = "../" * depth
    body = doc["answer_md"].replace("](images/", f"]({up}{doc['path'].rsplit('/', 1)[0]}/images/")
    who = f"｜{doc['author']}" if doc["author"] else ""
    head = f'??? success "老師擬答{who}（先自己寫再打開）"'
    return [head, ""] + _indent(body.splitlines()) + [
        "", f"    出處：[{_md_escape(doc['title'])}](<{up}{doc['path']}>)", ""]


# ---- 網頁 ----

HIDE_NAV = "---\nhide:\n  - navigation\n---\n"


EXAM_SHORT = [("高考三級", "高考"), ("普考", "普考"), ("地方政府特考三等", "地特三等"),
              ("地方政府特考四等", "地特四等"), ("地方政府特考五等", "地特五等"),
              ("專技普考-地政士", "地政士"), ("專技普考-不動產經紀人", "經紀人")]


def _exam_short(exam: str) -> str:
    return next((short for key, short in EXAM_SHORT if exam.startswith(key)), "國營事業")


def _paper_title(p: dict) -> str:
    return f"{p['year']} 年 {p['exam']}《{p['subject']}》"


def _indent(lines: List[str]) -> List[str]:
    return [("    " + ln) if ln else "" for ln in lines]


def related_md(docs: List[dict], depth: int, heading: str = "延伸閱讀：老師相關文章") -> List[str]:
    """相關文章清單；每篇是可收合區塊，展開時由前端（study_tools.js）就地載入全文。"""
    import html

    if not docs:
        return []
    up = "../" * depth
    out = [f'<p class="er-related-title">{heading}</p>', ""]
    for r in docs:
        who = f"｜{r['author']}" if r["author"] else ""
        out += ['<details class="qb-read" markdown>', f"<summary>{html.escape(r['title'] + who)}</summary>", "",
                f'[在新頁面開啟](<{up}{r["path"]}>){{.qb-read-link}}', "", "</details>", ""]
    return out


def qid(q: dict) -> str:
    """題目在考卷頁上的錨點：申論 e1、測驗 c12（同一卷兩種題號會重複）。"""
    return f"{q['kind'][0]}{q['no']}"


def _q_label(p: dict, q: dict) -> str:
    return f"{p['year']} {_exam_short(p['exam'])}《{p['subject']}》第 {q['no']} 題"


def _brief_md(p: dict, q: dict, up: str) -> List[str]:
    """題目精簡版（標題連結＋題目＋選項＋測驗答案），用於相似題與跨年度比較；up 為到家族目錄的相對路徑。"""
    out = [f"**[{_q_label(p, q)}](<{up}{p['id']}.md#{qid(q)}>)**", "", _md_escape(q["text"]), ""]
    if q.get("options"):
        out += [_md_escape(o) + "<br>" for o in q["options"]] + [""]
    if q["kind"] == "choice" and q["key"]:
        out += [f"答案：**{q['key']}**", ""]
    return out


def _similar_md(similar: List[Tuple[dict, dict]]) -> List[str]:
    if not similar:
        return []
    labels = list(dict.fromkeys(f"{p['year']} {_exam_short(p['exam'])}" for p, _ in similar))
    shown = "、".join(labels[:3]) + (f" 等 {len(labels)} 份" if len(labels) > 3 else "")  # 手機上標題不超過兩行
    out = [f'??? abstract "歷屆相似題（{len(similar)}）：{shown}"', ""]
    for p, q in similar:
        out += _indent(_brief_md(p, q, ""))
    return out


def _law_tags(hits: List[Tuple[str, str]], pages: Dict[str, str], up: str, limit: int = 6) -> List[str]:
    """法條標籤；有比較頁的連過去。up 為從目前頁面到家族目錄的網址前綴（如 "../"）。"""
    tags = []
    for ref, source in hits[:limit]:
        cls = "pb-count er-law" + (" er-law--match" if source == LawIndex.MATCH else "")
        tip = f'title="{LawIndex.SOURCE_TIP[source]}"'
        if ref in pages:
            tags.append(f'<a class="{cls}" {tip} href="{up}{LAW_DIR}/{pages[ref]}/">{ref}</a>')
        else:
            tags.append(f'<span class="{cls}" {tip}>{ref}</span>')
    return tags


def _question_md(q: dict, hits: List[Tuple[str, str]], law_pages: Dict[str, str], related: List[dict],
                 answer_doc: Optional[dict] = None,
                 similar: Optional[List[Tuple[dict, dict]]] = None) -> List[str]:
    meta = [f'<span class="pb-count">第 {q["no"]} 題</span>']
    if q["score"]:
        meta.append(f'<span class="pb-count">{q["score"]} 分</span>')
    meta += _law_tags(hits, law_pages, "../")
    out = [f'<div class="qb-item" id="{qid(q)}" markdown>', f'<p class="qb-meta">{"".join(meta)}</p>', "",
           _md_escape(q["text"]), ""]
    if q.get("options"):
        out += [_md_escape(o) + "<br>" for o in q["options"]] + [""]
    if q["kind"] == "choice" and q["key"]:
        out += ['??? success "答案"', f"    **{q['key']}**", ""]
    elif q["answer"]:
        out += ['??? success "參考解答（補習班詳解，先自己寫再打開）"', ""]
        out += _indent([_md_escape(a) + "\n" for a in q["answer"]])
    if answer_doc:
        out += teacher_answer_md(answer_doc, 2)
    out += _similar_md(similar or [])
    out += related_md([r for r in related if not answer_doc or r["file"] != answer_doc["file"]], 2)
    out += ["</div>", ""]
    return out


def _paper_page(p: dict, index: ArticleIndex, name: str, similar: "SimilarIndex",
                hits: Dict[Tuple[str, str], List[Tuple[str, str]]], law_pages: Dict[str, str],
                drills: Optional[Dict[str, int]] = None) -> str:
    """產生單份考卷頁。hits 為每題的法條 [(法條, 來源)]，law_pages 為有比較頁的法條 → 檔名，
    drills 為本家族有產生的連續刷題頁（題型 → 題數），本卷有該題型才放連結。"""
    from urllib.parse import quote

    essays = [q for q in p["questions"] if q["kind"] == "essay"]
    choices = [q for q in p["questions"] if q["kind"] == "choice"]
    drill_links = "".join(f'<a href="../{DRILL_KINDS[k][0]}/">{DRILL_KINDS[k][1]}連續刷題</a>'
                          for k, group in (("essay", essays), ("choice", choices)) if group and k in (drills or {}))
    lines = [
        HIDE_NAV,
        f"# {_paper_title(p)}",
        "",
        f'<p class="qb-meta"><a href="{REPO_BLOB + quote(p["pdf"])}" target="_blank" rel="noopener">原卷 PDF</a>'
        f'<a href="../{TOPIC_DIR}/">跨年度比較</a>'
        + drill_links
        + (f'<a href="../{LAW_DIR}/">依法條比較</a>' if law_pages else "")
        + f'<a href="../">回{name}題目總覽</a></p>',
        "",
        '!!! note "題目文字由 PDF 自動擷取"',
        "    表格與特殊符號可能跑版，請對照原卷 PDF。法條標籤是題目或詳解引用的條文，"
        "虛線框者是依條文內容自動比對（可能不準）；點標籤可看歷屆考這一條的題目。"
        "延伸閱讀依文字相似度自動推薦，不一定與題目完全對應。",
        "",
    ]
    if p.get("ocr"):
        lines += ['!!! warning "本卷為掃描檔，題目由 OCR 辨識"',
                  "    可能有錯字或漏字，作答前請對照原卷 PDF。", ""]
    if choices and not any(q["key"] for q in choices):
        lines += ['!!! info "本卷未附答案"',
                  "    原卷只有題目，主辦單位另行公告的答案未收錄；可先作答再查官方公告。", ""]
    if p["commentary"]:
        lines += ['??? info "試題評析"', ""] + _indent([_md_escape(c) + "\n" for c in p["commentary"]]) + [""]
    for title, group in (("申論題", essays), ("測驗題", choices)):
        if not group:
            continue
        if essays and choices:
            lines += [f"## {title}", ""]
        for q in group:
            refs = law_refs(q["text"] + "".join(q["answer"]))
            k = 3 if q["kind"] == "essay" else 2
            related = index.related(q["text"] * 2 + "".join(q["answer"]) + "".join(q.get("options", [])), refs, k)
            answer_doc = index.teacher_answer(q["text"]) if q["kind"] == "essay" else None
            lines += _question_md(q, hits[(p["id"], qid(q))], law_pages, related, answer_doc, similar.of(p, q))
    return "\n".join(lines)


DRILL_KINDS = {  # 題型 → (頁面檔名, 標題, 說明)
    "essay": (DRILL_PAGE, "申論題", "可一路往下寫；解答預設收合，先自己寫再打開。"),
    "choice": (DRILL_CHOICE_PAGE, "測驗題", "可一路往下作答；答案預設收合，選好再打開對答案。"),
}


def _write_drill_page(out: Path, kind: str, papers: List[dict], index: ArticleIndex, name: str,
                      hits: Dict[Tuple[str, str], List[Tuple[str, str]]], law_pages: Dict[str, str]) -> int:
    """某題型所有附解答的題目跨年度排成一頁，由新到舊連續刷；回傳題數，0 則不產生。

    申論題的解答是補習班詳解或老師擬答，測驗題是答案選項；沒有解答的題目不收（刷題要能對答案）。
    """
    page, label, how = DRILL_KINDS[kind]
    by_year: Dict[int, List[List[str]]] = defaultdict(list)
    for p in sorted(papers, key=lambda p: (-p["year"], p["exam"], p["subject"])):
        for q in p["questions"]:
            if q["kind"] != kind:
                continue
            answer_doc = index.teacher_answer(q["text"]) if kind == "essay" else None
            if not (q["key"] if kind == "choice" else q["answer"] or answer_doc):
                continue
            head = [f'<p class="er-drill-src"><a href="../{p["id"]}/#{qid(q)}">{_q_label(p, q)}</a></p>', ""]
            body = _question_md(q, hits[(p["id"], qid(q))], law_pages, [], answer_doc)
            body[0] = body[0].replace(f'id="{qid(q)}"', f'id="{p["id"]}-{qid(q)}"')  # 同頁多份考卷，錨點加卷別
            by_year[p["year"]].append(head + body)
    n = sum(len(v) for v in by_year.values())
    if not n:
        return 0
    lines = [
        HIDE_NAV,
        f"# {name}：{label}連續刷題",
        "",
        f'<p class="qb-meta"><a href="../">回{name}題目總覽</a><a href="../{TOPIC_DIR}/">跨年度比較</a></p>',
        "",
        f"共 **{n}** 題附解答的{label}，由新到舊排成一頁，{how}"
        "頁面目錄可跳到指定年度，題目標題連回原考卷。",
        "",
    ]
    for year in sorted(by_year, reverse=True):
        lines += [f"## {year} 年（{len(by_year[year])} 題）", ""]
        for block in by_year[year]:
            lines += block
    (out / f"{page}.md").write_text("\n".join(lines), encoding="utf-8")
    return n


def write_pages(docs_dir: Path, posts_dir: Union[Path, List[Path]],
                data_dir: Path = EXAM_READER_DATA_DIR) -> List[tuple]:
    """產生 docs/exam-reader/<slug>/，回傳 mkdocs nav 用的 [(標題, 路徑)]；沒有任何資料時回空。"""
    readers = available(data_dir)
    if not readers:
        return []
    index = ArticleIndex(posts_dir)
    laws = LawIndex()
    nav = []
    written = []
    for _, slug, name in readers:
        papers = json.loads(data_file(slug, data_dir).read_text(encoding="utf-8"))
        if papers:
            _write_family(docs_dir / READER_ROOT / slug, papers, index, laws, name, slug)
            nav.append((name, f"{READER_ROOT}/{slug}/index.md"))
            written.append((slug, name, papers))
    if written:
        _write_overview(docs_dir / READER_ROOT, written)
        nav.insert(0, ("各科總覽", f"{READER_ROOT}/index.md"))
    return nav


def _has_key(q: dict) -> bool:
    """題目是否有解答：申論看詳解內容，測驗看答案字母。"""
    return bool(q.get("key") if q["kind"] == "choice" else q.get("answer"))


def _write_overview(out: Path, families: List[Tuple[str, str, List[dict]]]) -> None:
    """exam-reader/index.md：各科考卷數、題數與詳解涵蓋率一覽。"""
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    t_p = t_a = t_q = t_k = 0
    for slug, name, papers in families:
        qs = [q for p in papers for q in p["questions"]]
        n_a = sum(p["has_answer"] for p in papers)
        n_k = sum(_has_key(q) for q in qs)
        years = sorted({p["year"] for p in papers})
        pct = f"{n_k * 100 // len(qs)}%" if qs else "—"
        rows.append(f"| [{name}]({slug}/index.md) | {years[0]}–{years[-1]} | {len(papers)} | {n_a} | "
                    f"{len(qs)} | {n_k}（{pct}） |")
        t_p, t_a, t_q, t_k = t_p + len(papers), t_a + n_a, t_q + len(qs), t_k + n_k
    lines = [
        "---\nhide:\n  - navigation\n  - toc\n---\n",
        "# 逐題讀：各科總覽",
        "",
        f"地政相關考古題共 **{len(families)}** 科、**{t_p}** 份考卷、**{t_q}** 題拆成網頁逐題閱讀，"
        f"其中 **{t_a}** 份附補習班詳解，**{t_k}** 題（{t_k * 100 // max(t_q, 1)}%）有解答可看。",
        "",
        "!!! note \"不是每份考卷都有詳解\"",
        "    詳解來自補習班公開的解題 PDF，部分年度或考試沒有出詳解，這些考卷只有題目；"
        "測驗題若答案頁無法自動對應，也會只顯示題目。各科頁面的「歷屆考卷」表格有 ✓ 的才附詳解。",
        "",
        "| 科目 | 年度 | 考卷 | 附詳解考卷 | 題數 | 有解答的題目 |",
        "|---|---|---:|---:|---:|---:|",
        *rows,
    ]
    (out / "index.md").write_text("\n".join(lines), encoding="utf-8")


def _write_family(out: Path, papers: List[dict], index: ArticleIndex, laws: "LawIndex", name: str,
                  slug: str) -> None:
    from urllib.parse import quote

    out.mkdir(parents=True, exist_ok=True)
    readable = [p for p in papers if p["questions"]]
    similar = SimilarIndex(readable)
    _write_topic_pages(out / TOPIC_DIR, readable, similar, name, READER_TOPICS.get(slug, []))
    hits = {(p["id"], qid(q)): laws.refs(q) for p, q in similar.items}
    by_ref: Dict[str, List[Tuple[dict, dict, str]]] = defaultdict(list)
    for p, q in similar.items:
        for ref, source in hits[(p["id"], qid(q))]:
            by_ref[ref].append((p, q, source))
    law_pages = _write_law_pages(out / LAW_DIR, by_ref, laws, name)
    drills = {kind: n for kind in DRILL_KINDS
              if (n := _write_drill_page(out, kind, readable, index, name, hits, law_pages))}
    for p in readable:
        page = _paper_page(p, index, name, similar, hits, law_pages, drills)
        (out / f"{p['id']}.md").write_text(page, encoding="utf-8")

    n_q = sum(len(p["questions"]) for p in readable)
    n_ans = sum(p["has_answer"] for p in papers)
    years = sorted({p["year"] for p in papers})
    subjects = Counter(p["subject"] for p in papers)
    lines = [
        "---\nhide:\n  - navigation\n  - toc\n---\n",
        f"# {name}：逐題閱讀",
        "",
        f"把{name}家族（{'、'.join(s for s, _ in subjects.most_common(4))}{'…' if len(subjects) > 4 else ''}）"
        f"民國 {years[0]}–{years[-1]} 年 **{len(papers)}** 份考古題拆成網頁，共 **{n_q}** 題，"
        f"其中 **{n_ans}** 份附補習班詳解（可收合，先寫再看）。每題另附考點法條、歷屆相似題與自動推薦的老師相關文章。",
        "",
        f"**[跨年度比較]({TOPIC_DIR}/index.md)**：依主題看各年度出了哪些題目，以及換句話說又考一次的重複考點。",
        "",
    ]
    for kind, n in drills.items():
        page, label, _ = DRILL_KINDS[kind]
        lines += [f"**[{label}連續刷題]({page}.md)**：{n} 題附解答的{label}跨年度排成一頁，"
                  "不用一份考卷看完再回來選下一份。", ""]
    if law_pages:
        lines += [
            f"**[依法條比較]({LAW_DIR}/index.md)**：同一條文歷屆怎麼考，附現行條文與修正日期，"
            "標出出題後條文已修正的舊題。",
            "",
            "## 最常考的法條",
            "",
            f"考過兩題以上的條文共 {len(law_pages)} 條，以下列出前 20 條；點條文看歷屆題目。",
            "",
            "| 法條 | 題數 | 出題年度 |",
            "|---|---:|---|",
        ]
        top = sorted(law_pages, key=lambda r: (-len(by_ref[r]), r))[:20]
        for ref in top:
            years = sorted({p["year"] for p, _, _ in by_ref[ref]})
            span = f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0])
            lines.append(f"| [{ref}]({LAW_DIR}/{law_pages[ref]}.md) | {len(by_ref[ref])} | {span} |")
    lines += ["", "## 歷屆考卷", "", "| 年度 | 考試 | 科目 | 題目 | 詳解 |", "|---:|---|---|---|---|"]
    for p in sorted(papers, key=lambda p: (-p["year"], p["exam"])):
        e = sum(q["kind"] == "essay" for q in p["questions"])
        c = sum(q["kind"] == "choice" for q in p["questions"])
        desc = "、".join(s for s in (f"申論 {e} 題" if e else "", f"測驗 {c} 題" if c else "") if s)
        if p["questions"]:
            title = f"[{p['subject']}]({p['id']}.md)"
        else:
            desc = "無法自動拆題（掃描檔或特殊排版），請看原卷"
            title = f'[{p["subject"]}]({REPO_BLOB + quote(p["pdf"])}){{target="_blank"}}'
        lines.append(f"| {p['year']} | {p['exam']} | {title} | {desc} | {'✓' if p['has_answer'] else ''} |")
    (out / "index.md").write_text("\n".join(lines), encoding="utf-8")


# ---- 跨年度比較 ----

class SimilarIndex:
    """同家族題目兩兩比對（字二元組 TF-IDF 餘弦），找出不同考卷中問同一件事的題目。"""

    MIN_SIM = 0.4  # 實測 0.4 以上幾乎都是同一考點換句話說；0.35 以下開始混入只是同章節的題目
    MAX_SHOWN = 8

    def __init__(self, papers: List[dict]):
        self.items = [(p, q) for p in papers for q in p["questions"]]
        self.pos = {(p["id"], qid(q)): i for i, (p, q) in enumerate(self.items)}
        tfs = [Counter(_sim_tokens(q)) for _, q in self.items]
        df: Counter = Counter()
        for tf in tfs:
            df.update(tf.keys())
        n = len(tfs)
        vecs: List[Dict[str, float]] = []
        postings: Dict[str, List[Tuple[int, float]]] = defaultdict(list)
        for i, tf in enumerate(tfs):
            vec = {t: (1 + math.log(c)) * (math.log((n + 1) / (df[t] + 1)) + 1) for t, c in tf.items()}
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            vecs.append({t: v / norm for t, v in vec.items()})
            for t, v in vecs[i].items():
                postings[t].append((i, v))
        self.neighbors: Dict[int, List[Tuple[float, int]]] = defaultdict(list)
        for i, vec in enumerate(vecs):
            scores: Dict[int, float] = defaultdict(float)
            for t, v in vec.items():
                for j, w in postings[t]:
                    if j > i:
                        scores[j] += v * w
            for j, sc in scores.items():
                (pi, qi), (pj, qj) = self.items[i], self.items[j]
                if sc >= self.MIN_SIM and pi["id"] != pj["id"] and qi["kind"] == qj["kind"]:
                    self.neighbors[i].append((sc, j))
                    self.neighbors[j].append((sc, i))

    def of(self, p: dict, q: dict) -> List[Tuple[dict, dict]]:
        """某題的相似題，新年度在前。"""
        i = self.pos[(p["id"], qid(q))]
        best = sorted(self.neighbors.get(i, []), reverse=True)[:self.MAX_SHOWN]
        return sorted((self.items[j] for _, j in best), key=lambda pq: (-pq[0]["year"], pq[0]["exam"]))

    def clusters(self) -> List[List[Tuple[dict, dict]]]:
        """重複出題題組：從最新的題目開始，把它與尚未分組的相似題收成一組；只留橫跨兩個以上年度的組。"""
        order = sorted(range(len(self.items)), key=lambda i: -self.items[i][0]["year"])
        used, groups = set(), []
        for i in order:
            if i in used or not self.neighbors.get(i):
                continue
            members = [i] + [j for _, j in sorted(self.neighbors[i], reverse=True) if j not in used]
            used.update(members)
            group = sorted((self.items[j] for j in members), key=lambda pq: (-pq[0]["year"], pq[0]["exam"]))
            if len({p["year"] for p, _ in group}) >= 2:
                groups.append(group)
        return sorted(groups, key=lambda g: (-len({p["year"] for p, _ in g}), -g[0][0]["year"]))


def _sim_tokens(q: dict) -> List[str]:
    text = SCORE.sub("", q["text"] + "".join(q.get("options", [])))
    s = re.sub(r"[^一-鿿A-Za-z0-9]", "", text)
    return [s[i:i + 2] for i in range(len(s) - 1)]


def _topic_of(q: dict, topics: List[tuple]) -> str:
    return best_topic(topics, q["text"] + " " + " ".join(q.get("options", [])))


def _kind_counts(qs: List[Tuple[dict, dict]]) -> str:
    e = sum(q["kind"] == "essay" for _, q in qs)
    c = len(qs) - e
    return "、".join(s for s in (f"申論 {e}" if e else "", f"測驗 {c}" if c else "") if s)


def _write_topic_pages(out: Path, papers: List[dict], similar: SimilarIndex, name: str,
                       topics: List[tuple]) -> None:
    """exam-reader/<slug>/topics/：總覽（主題出題趨勢＋重複出題題組）與每個主題一頁（依年度排列）。"""
    out.mkdir(parents=True, exist_ok=True)
    by_topic: Dict[str, List[Tuple[dict, dict]]] = defaultdict(list)
    for p, q in similar.items:
        by_topic[_topic_of(q, topics) if topics else "全部題目"].append((p, q))
    names = [t[0] for t in topics if t[0] in by_topic] + [t for t in ("其他", "全部題目") if t in by_topic]
    latest = max(p["year"] for p in papers)
    recent = latest - 4

    lines = [
        HIDE_NAV,
        f"# {name}：跨年度比較",
        "",
        f'<p class="qb-meta"><a href="../">回{name}題目總覽</a></p>',
        "",
        "同一個考點常隔幾年換個問法再考一次。這裡把歷屆題目依**主題**歸類、依**年度**排好，"
        "方便看出題趨勢與題目演變；**重複出題**則列出不同年度文字高度相似的題組，可直接展開對照。",
        "",
        '!!! note "主題與相似題由程式自動判斷"',
        "    主題依題目關鍵詞歸類、相似題依文字相似度比對，偶有歸錯；每題都連回原考卷，可看完整詳解。",
        "",
        "## 主題出題趨勢",
        "",
        f"| 主題 | 題數 | 近 5 年（{recent}–{latest}） | 最近出題 |",
        "|---|---:|---:|---:|",
    ]
    for i, topic in enumerate(names, 1):
        qs = by_topic[topic]
        n_recent = sum(p["year"] >= recent for p, _ in qs)
        lines.append(f"| [{topic}](t{i}.md) | {len(qs)}（{_kind_counts(qs)}） | {n_recent} | "
                     f"{max(p['year'] for p, _ in qs)} |")
        _write_topic_page(out / f"t{i}.md", topic, qs, name)

    groups = similar.clusters()
    lines += ["", f"## 重複出題（{len(groups)} 組）", ""]
    if groups:
        lines += ["不同年度文字高度相似的題目，出現年度越多排越前面。", ""]
    else:
        lines += ["本科多為申論題，各年題目文字差異大，沒有找到明顯重複的題組；請改用上方主題頁比較。", ""]
    for g in groups:
        years = "、".join(dict.fromkeys(str(p["year"]) for p, _ in g))
        head = g[0][1]["text"][:36].replace('"', "'")
        lines += [f'??? note "{len(g)} 題・{years} 年：{_md_escape(head)}…"', ""]
        for p, q in g:
            lines += _indent(_brief_md(p, q, "../"))
    (out / "index.md").write_text("\n".join(lines), encoding="utf-8")


def _write_topic_page(path: Path, topic: str, qs: List[Tuple[dict, dict]], name: str) -> None:
    by_year: Dict[int, List[Tuple[dict, dict]]] = defaultdict(list)
    for p, q in qs:
        by_year[p["year"]].append((p, q))
    years = sorted(by_year, reverse=True)
    lines = [
        "---\nhide:\n  - navigation\n---\n",
        f"# {topic}",
        "",
        f'<p class="qb-meta"><span class="pb-count">{name}</span><span class="pb-count">{len(qs)} 題</span>'
        f'<span class="pb-count">{years[-1]}–{years[0]} 年</span><a href="../">回跨年度比較</a></p>',
        "",
        "出題年度：" + "・".join(f"[{y}](#y{y})（{len(by_year[y])}）" for y in years),
        "",
    ]
    for y in years:
        lines += [f"## {y} 年 {{#y{y}}}", ""]
        for p, q in sorted(by_year[y], key=lambda pq: (pq[1]["kind"] != "essay", pq[0]["exam"], pq[1]["no"])):
            lines += _card_md(p, q)
    path.write_text("\n".join(lines), encoding="utf-8")


def _card_md(p: dict, q: dict, badges: Optional[List[str]] = None) -> List[str]:
    """比較頁（topics/、laws/ 下一層）的題目卡：考試別、題型、額外標籤、題目、選項、可收合答案。"""
    if q["kind"] == "essay":
        kind = f"申論 {q['score']} 分" if q["score"] else "申論"
    else:
        kind = "測驗"
    out = [
        '<div class="qb-item" markdown>',
        f'<p class="qb-meta"><span class="pb-count">{_exam_short(p["exam"])}</span>'
        f'<span class="pb-count">{kind}</span>{"".join(badges or [])}'
        f'<a href="../../{p["id"]}/#{qid(q)}">{"看詳解" if q["answer"] else "看原題"} →</a></p>',
        "",
        f"《{_md_escape(p['subject'])}》第 {q['no']} 題：{_md_escape(q['text'])}",
        "",
    ]
    if q.get("options"):
        out += [_md_escape(o) + "<br>" for o in q["options"]] + [""]
    if q["kind"] == "choice" and q["key"]:
        out += ['??? success "答案"', f"    **{q['key']}**", ""]
    return out + ["</div>", ""]


# ---- 依法條比較 ----

class LawIndex:
    """把考題對到條文：題目明寫的條號 > 詳解引用的條號 > 依條文內容比對（字二元組 TF-IDF）。

    條文來自 data/law_articles.json（law_timeline.build 寫入）；檔案不存在時只用明寫的條號。
    """

    QUESTION, ANSWER, MATCH = "題目", "詳解", "比對"
    SOURCE_TIP = {QUESTION: "題目引用的條文", ANSWER: "詳解引用的條文", MATCH: "依條文內容自動比對，可能不準"}
    MIN_SCORE = 0.3  # 實測 0.3 以上多為正確條文；0.25 以下常對到用語相近的他法條文
    SECOND_SCORE = 0.45  # 第二高分也很高時一併列出（例如測驗題選項分別考不同條）
    # 比對時去掉題目套語，免得「下列何者正確」主導分數
    BOILERPLATE = re.compile(r"下列|何者|敘述|正確|錯誤|請|說明|試|何謂|為何|規定|依|之")

    def __init__(self, articles_file: Path = LAW_ARTICLES_FILE, timeline: Optional[LawTimeline] = None):
        self.timeline = timeline or LawTimeline()
        self.text: Dict[str, str] = {}
        self.law_of: List[str] = []
        self.refs_list: List[str] = []
        self.postings: Dict[str, List[Tuple[int, float]]] = defaultdict(list)
        self.idf: Dict[str, float] = {}
        if not articles_file.exists():
            return
        laws = json.loads(articles_file.read_text(encoding="utf-8"))["laws"]
        tfs = []
        for law, articles in laws.items():
            for no, content in articles.items():
                ref = _ref_name(law, no)
                self.text[ref] = content
                self.refs_list.append(ref)
                self.law_of.append(law)
                tfs.append(Counter(_grams(content)))
        df: Counter = Counter()
        for tf in tfs:
            df.update(tf.keys())
        n = len(tfs)
        self.idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
        for i, tf in enumerate(tfs):
            vec = {t: (1 + math.log(c)) * self.idf[t] for t, c in tf.items()}
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            for t, v in vec.items():
                self.postings[t].append((i, v / norm))

    def refs(self, q: dict) -> List[Tuple[str, str]]:
        """題目的法條 [(法條, 來源)]，依可信度排序、去重。"""
        stem = q["text"] + " " + " ".join(q.get("options", []))
        out: Dict[str, str] = {}
        for r in law_refs(stem):
            if "第" in r:
                out.setdefault(r, self.QUESTION)
        for r in law_refs("".join(q["answer"])):
            if "第" in r:
                out.setdefault(r, self.ANSWER)
        for r in self.match(stem):
            out.setdefault(r, self.MATCH)
        return list(out.items())

    def match(self, text: str) -> List[str]:
        if not self.postings:
            return []
        # 題目點名的法規（「依土地徵收條例規定」）只在該法規內找
        names = {r for r in law_refs(text) if "第" not in r}
        tf = Counter(_grams(self.BOILERPLATE.sub("", text)))
        vec = {t: (1 + math.log(c)) * self.idf[t] for t, c in tf.items() if t in self.idf}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        scores: Dict[int, float] = defaultdict(float)
        for t, v in vec.items():
            for i, w in self.postings[t]:
                if not names or self.law_of[i] in names:
                    scores[i] += v / norm * w
        best = sorted(scores.items(), key=lambda kv: -kv[1])[:2]
        out = [self.refs_list[i] for i, sc in best[:1] if sc >= self.MIN_SCORE]
        out += [self.refs_list[i] for i, sc in best[1:] if out and sc >= self.SECOND_SCORE]
        return out


def _grams(text: str) -> List[str]:
    s = re.sub(r"[^一-鿿A-Za-z0-9]", "", text)
    return [s[i:i + 2] for i in range(len(s) - 1)]


def _ref_name(law: str, no: str) -> str:
    """("土地法", "34-1") → 「土地法第34條之1」，與 law_refs 的寫法一致。"""
    main, _, sub = no.partition("-")
    return f"{law}第{main}條" + (f"之{sub}" if sub else "")


def _law_slug(ref: str, timeline: LawTimeline) -> str:
    """比較頁檔名：全國法規資料庫代碼＋條號（D0060001-34-1），網址穩定；查不到代碼時用雜湊。"""
    m = re.match(r"^(.+?)第(\d+)條(?:之(\d+))?$", ref)
    info = timeline.laws.get(m.group(1), {}) if m else {}
    if m and info.get("pcode"):
        return f"{info['pcode']}-{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")
    return "law-" + hashlib.md5(ref.encode("utf-8")).hexdigest()[:8]


LAW_PAGE_MIN = 2  # 至少兩題才有比較的意義


def _write_law_pages(out: Path, by_ref: Dict[str, List[Tuple[dict, dict, str]]], laws: LawIndex,
                     name: str) -> Dict[str, str]:
    """exam-reader/<slug>/laws/：總覽（依法規分區）與每條一頁；回傳有頁面的法條 → 檔名。"""
    pages = {ref: _law_slug(ref, laws.timeline) for ref, qs in by_ref.items() if len(qs) >= LAW_PAGE_MIN}
    if not pages:
        return {}
    out.mkdir(parents=True, exist_ok=True)
    grouped: Dict[str, List[str]] = defaultdict(list)
    for ref in pages:
        grouped[re.sub(r"第\d+條.*$", "", ref)].append(ref)
    order = sorted(grouped, key=lambda law: -sum(len(by_ref[r]) for r in grouped[law]))
    n_q = len({(p["id"], qid(q)) for ref in pages for p, q, _ in by_ref[ref]})
    lines = [
        HIDE_NAV,
        f"# {name}：依法條比較",
        "",
        f'<p class="qb-meta"><a href="../{TOPIC_DIR}/">依主題比較</a><a href="../">回{name}題目總覽</a></p>',
        "",
        f"把 **{n_q}** 題對到 **{len(pages)}** 條考過兩題以上的條文。點條文可看**現行條文、修正日期**，"
        "以及歷屆考這一條的題目（依年度排列，出題後條文已修正的會標出來）。",
        "",
        '!!! note "法條怎麼對上的"',
        "    題目或補習班詳解明寫條號的直接採用；沒寫條號的，依題目文字與全國法規資料庫現行條文的相似度自動比對，"
        "比對結果在題目頁以虛線框標示，偶有對錯。",
        "",
        "**法規**：" + "・".join(f"[{law}](#law-{i})（{len(grouped[law])}）" for i, law in enumerate(order, 1)),
        "",
    ]
    for i, law in enumerate(order, 1):
        lines += [f"## {law} {{#law-{i}}}", "", "| 條文 | 題數 | 出題年度 | 內容 |", "|---|---:|---|---|"]
        for ref in sorted(grouped[law], key=lambda r: (-len(by_ref[r]), _article_key(r))):
            years = sorted({p["year"] for p, _, _ in by_ref[ref]})
            span = f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0])
            snippet = _md_escape(laws.text.get(ref, "").replace("\n", " ")[:24])
            lines.append(f"| [{ref[len(law):]}]({pages[ref]}.md) | {len(by_ref[ref])} | {span} | "
                         f"{snippet}{'…' if snippet else '（現行法規查無此條）'} |")
        lines.append("")
        for ref in grouped[law]:
            _write_law_page(out / f"{pages[ref]}.md", ref, by_ref[ref], laws, name)
    (out / "index.md").write_text("\n".join(lines), encoding="utf-8")
    return pages


def _article_key(ref: str) -> Tuple[int, int]:
    m = re.search(r"第(\d+)條(?:之(\d+))?$", ref)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def _write_law_page(path: Path, ref: str, qs: List[Tuple[dict, dict, str]], laws: LawIndex, name: str) -> None:
    amended = laws.timeline.amended(ref)
    url = laws.timeline.url(ref)
    by_year: Dict[int, List[Tuple[dict, dict, str]]] = defaultdict(list)
    for item in qs:
        by_year[item[0]["year"]].append(item)
    years = sorted(by_year, reverse=True)
    n_stale = sum(1 for p, _, _ in qs if _amended_after(amended, p["year"]))
    lines = [
        "---\nhide:\n  - navigation\n---\n",
        f"# {ref}",
        "",
        f'<p class="qb-meta"><span class="pb-count">{name}</span><span class="pb-count">{len(qs)} 題</span>'
        f'<span class="pb-count">{years[-1]}–{years[0]} 年</span><a href="../">回依法條比較</a></p>',
        "",
    ]
    text = laws.text.get(ref)
    if text:
        # 條文每項一段；整段放進 admonition 縮排，換行才不會跳出區塊
        lines += ['!!! quote "現行條文"', ""] + _indent(
            [ln for par in text.split("\n") if par.strip() for ln in (_md_escape(par.strip()), "")])
        if url:
            lines += [f"    [全國法規資料庫]({url}){{target=\"_blank\"}}", ""]
    else:
        lines += ['!!! warning "現行法規查無此條"',
                  "    這一條可能已刪除或條號變動，題目內容請以出題當時的法規理解。", ""]
    if amended:
        shown = "、".join(amended[:8]) + (f" 等 {len(amended)} 次" if len(amended) > 8 else "")
        lines += [f"**條文修正**（含法規修正全文）：{shown}。"]
        if n_stale:
            lines += ["", f"其中 **{n_stale}** 題出題後條文又修正過，標有「出題後修正」，舊詳解可能已不適用。"]
        lines += [""]
    lines += ["出題年度：" + "・".join(f"[{y}](#y{y})（{len(by_year[y])}）" for y in years), ""]
    for y in years:
        lines += [f"## {y} 年 {{#y{y}}}", ""]
        for p, q, source in sorted(by_year[y], key=lambda t: (t[1]["kind"] != "essay", t[0]["exam"], t[1]["no"])):
            badges = [f'<span class="pb-count er-law{" er-law--match" if source == LawIndex.MATCH else ""}" '
                      f'title="{LawIndex.SOURCE_TIP[source]}">{source}</span>']
            after = _amended_after(amended, p["year"])
            if after:
                badges.append(f'<span class="pb-count er-warn" title="出題後條文修正日期">出題後修正 {after}</span>')
            lines += _card_md(p, q, badges)
    path.write_text("\n".join(lines), encoding="utf-8")


def _amended_after(amended: List[str], roc_year: int) -> Optional[str]:
    """出題年度之後最近一次修正的日期；同年度的修正無法判斷先後，不算。"""
    cutoff = f"{roc_year + 1911}-12-31"
    later = [d for d in amended if d > cutoff]
    return later[0] if later else None
