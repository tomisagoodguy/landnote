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
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from landnote.config import ARTICLES_DIR, EXAM_READER_DATA_DIR
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
)
from landnote.processors.law_timeline import law_refs

# (SUBJECT_FAMILIES 的家族名, 網址 slug, 頁面名稱)；slug 的底線版即 JSON 檔名（land-law → land_law.json）
READERS = [
    ("土地法規與土地行政", "land-law", "土地法規"),
    ("不動產估價", "appraisal", "不動產估價"),
    ("不動產投資", "investment", "不動產投資"),
    ("土地經濟與土地政策", "economics", "土地經濟與土地政策"),
    ("土地利用與都市計畫", "land-use", "土地利用與都市計畫"),
    ("民法", "civil-law", "民法"),
]
READER_ROOT = "exam-reader"
TOPIC_DIR = "topics"  # 跨年度比較頁：exam-reader/<slug>/topics/

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
READER_TOPICS = {
    "land-law": LAND_LAW_TOPICS,
    "appraisal": APPRAISAL_TOPICS,
    "investment": TOPICS["不動產投資分析"],
    "economics": TOPICS["不動產經濟學"],
    "land-use": LAND_USE_TOPICS,
    "civil-law": CIVIL_LAW_TOPICS,
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
    r"[甲乙丙]、\s*(申論|測驗)題.*)$"
)
TITLE = re.compile(r"^《(.+)》$")
TOP_MARK = re.compile(r"^(?:題目)?([一二三四五六七八九十]+)\s*[、：:]")
ANSWER = re.compile(r"^答\s*(?:[：:]\s*|$)")
# 答案用全形括號「（B）1.」，選項用半形「(A)」；題號點號有時省略，所以另以題號遞增防誤判
# 少數年份改用半形「(A) 2 」，此時括號與題號間必有空白，與「(A)3公畝」區隔
CHOICE = re.compile(r"^(?:（\s*([A-DＡ-Ｄ#＃][A-D、,或]*|一律給分|送分)\s*）\s*|\(([A-D#][A-D、,或]*)\)\s+)"
                    r"(\d{1,3})\s*[.．、]?\s*")
OPTION = re.compile(r"[（(]([A-D])[）)]")
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
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x81]", "", text)
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
    """
    _, lines = _clean_lines(text)
    commentary: List[str] = []
    questions: List[dict] = []
    cur: Optional[dict] = None
    mode = "pre"  # pre（試題評析前）/ comment / skip / stem / answer
    expect, expect_choice = 1, 1
    for i, ln in enumerate(lines):
        m_choice = CHOICE.match(ln)
        m_top = TOP_MARK.match(ln)
        if m_choice and int(m_choice.group(3)) == expect_choice:
            expect_choice += 1
            key = m_choice.group(1) or m_choice.group(2)
            cur = {"no": int(m_choice.group(3)), "kind": "choice",
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
    for q in questions:
        stem = HEADER_TAIL.split("".join(q["stem"]))[0].strip()
        if q["kind"] == "essay":
            score = sum(int(s) for s in SCORE.findall(stem))
            prev = next((o for o in reversed(out) if o["kind"] == "essay"), None)
            # 配分已滿 100 後又出現沒配分的「五、六、」，是前一題詳解裡的條列，併回去
            if not score and essay_total >= 100 and prev:
                prev["answer"] += _join(q["stem"] + q["answer"], structured=True)
                continue
            essay_total += score
        item = {"no": q["no"], "kind": q["kind"], "answer": _join(q["answer"], structured=True)}
        if q["kind"] == "choice":
            parts = OPTION.split(stem)
            item["text"] = parts[0].strip()
            item["options"] = [f"({parts[i]}) {parts[i + 1].strip()}" for i in range(1, len(parts) - 1, 2)]
            item["key"] = q["key"]
            item["score"] = 0
        else:
            item["text"] = stem
            item["score"] = sum(int(s) for s in SCORE.findall(stem))
        out.append(item)
    # 申論題沒有任何配分代表切題失敗（例如抓到表頭），整份退回只給原卷
    essays = [q for q in out if q["kind"] == "essay"]
    if essays and not any(q["score"] for q in essays):
        out = [q for q in out if q["kind"] == "choice"]
    return {"commentary": _join(commentary, structured=True), "questions": out}


def build(exam_dir: Path = EXAM_DIR, data_dir: Path = EXAM_READER_DATA_DIR) -> List[Path]:
    """掃描 READERS 各家族考卷，每個家族輸出一個閱讀版 JSON；回傳寫出的路徑（無資料的家族略過）。"""
    from landnote.processors.site_generator import SiteGenerator  # 延遲匯入：site_generator 也匯入本模組

    folders: Dict[str, List[Path]] = defaultdict(list)
    for folder in sorted(p for p in exam_dir.iterdir() if p.is_dir()):
        folders[SiteGenerator._subject_family(folder.name)[0]].append(folder)
    written = []
    for family, slug, _ in READERS:
        papers = _build_family(folders.get(family, []))
        if papers:
            out_file = data_file(slug, data_dir)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(papers, ensure_ascii=False, indent=1), encoding="utf-8")
            written.append(out_file)
    return written


def _build_family(folders: List[Path]) -> List[dict]:
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
            parsed = parse_paper(text) if len(text.strip()) >= MIN_TEXT else {"commentary": [], "questions": []}
            papers.append({
                "id": f"{m.group(1)}-{hashlib.md5(rel.encode('utf-8')).hexdigest()[:6]}",
                "year": int(m.group(1)),
                "exam": m.group(2),
                "subject": m.group(3),
                "pdf": rel,
                "has_answer": any(q["answer"] or q.get("key") for q in parsed["questions"]),
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
    if q["kind"] == "choice":
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


def _question_md(q: dict, refs: List[str], related: List[dict], answer_doc: Optional[dict] = None,
                 similar: Optional[List[Tuple[dict, dict]]] = None) -> List[str]:
    meta = [f'<span class="pb-count">第 {q["no"]} 題</span>']
    if q["score"]:
        meta.append(f'<span class="pb-count">{q["score"]} 分</span>')
    meta += [f'<span class="pb-count er-law">{r}</span>' for r in refs[:6]]
    out = [f'<div class="qb-item" id="{qid(q)}" markdown>', f'<p class="qb-meta">{"".join(meta)}</p>', "",
           _md_escape(q["text"]), ""]
    if q.get("options"):
        out += [_md_escape(o) + "<br>" for o in q["options"]] + [""]
    if q["kind"] == "choice":
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


def _paper_page(p: dict, index: ArticleIndex, name: str,
                similar: "SimilarIndex") -> Tuple[str, Dict[str, List[dict]]]:
    """產生單份考卷頁，並回傳本卷每題的法條（供總覽頁統計）。"""
    from urllib.parse import quote

    essays = [q for q in p["questions"] if q["kind"] == "essay"]
    choices = [q for q in p["questions"] if q["kind"] == "choice"]
    lines = [
        HIDE_NAV,
        f"# {_paper_title(p)}",
        "",
        f'<p class="qb-meta"><a href="{REPO_BLOB + quote(p["pdf"])}" target="_blank" rel="noopener">原卷 PDF</a>'
        f'<a href="../{TOPIC_DIR}/">跨年度比較</a><a href="../">回{name}題目總覽</a></p>',
        "",
        '!!! note "題目文字由 PDF 自動擷取"',
        "    表格與特殊符號可能跑版，請對照原卷 PDF。考點標籤由題目與詳解中引用的法條自動抽出；"
        "延伸閱讀依文字相似度自動推薦，不一定與題目完全對應。",
        "",
    ]
    if p["commentary"]:
        lines += ['??? info "試題評析"', ""] + _indent([_md_escape(c) + "\n" for c in p["commentary"]]) + [""]
    refs_by_q: Dict[str, List[dict]] = {}
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
            lines += _question_md(q, refs, related, answer_doc, similar.of(p, q))
            for r in refs:
                if "第" in r:
                    refs_by_q.setdefault(r, []).append({"paper": p, "no": q["no"], "kind": q["kind"]})
    return "\n".join(lines), refs_by_q


def write_pages(docs_dir: Path, posts_dir: Union[Path, List[Path]],
                data_dir: Path = EXAM_READER_DATA_DIR) -> List[tuple]:
    """產生 docs/exam-reader/<slug>/，回傳 mkdocs nav 用的 [(標題, 路徑)]；沒有任何資料時回空。"""
    readers = available(data_dir)
    if not readers:
        return []
    index = ArticleIndex(posts_dir)
    nav = []
    for _, slug, name in readers:
        papers = json.loads(data_file(slug, data_dir).read_text(encoding="utf-8"))
        if papers:
            _write_family(docs_dir / READER_ROOT / slug, papers, index, name, slug)
            nav.append((name, f"{READER_ROOT}/{slug}/index.md"))
    return nav


def _write_family(out: Path, papers: List[dict], index: ArticleIndex, name: str, slug: str) -> None:
    from urllib.parse import quote

    out.mkdir(parents=True, exist_ok=True)
    hot: Dict[str, List[dict]] = defaultdict(list)
    readable = [p for p in papers if p["questions"]]
    similar = SimilarIndex(readable)
    _write_topic_pages(out / TOPIC_DIR, readable, similar, name, READER_TOPICS.get(slug, []))
    for p in readable:
        page, refs = _paper_page(p, index, name, similar)
        (out / f"{p['id']}.md").write_text(page, encoding="utf-8")
        for r, qs in refs.items():
            hot[r] += qs

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
    if hot:
        lines += [
            "## 最常考的法條",
            "",
            "題目或詳解引用該條文的題數；點年度直接跳到那份考卷。",
            "",
            "| 法條 | 題數 | 出題年度 |",
            "|---|---:|---|",
        ]
    for ref, qs in sorted(hot.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:30]:
        by_paper: Dict[str, dict] = {}
        for q in qs:
            by_paper.setdefault(q["paper"]["id"], q["paper"])
        links = "、".join(f"[{p['year']}{_exam_short(p['exam'])}]({p['id']}.md)" for p in
                         sorted(by_paper.values(), key=lambda p: -p["year"])[:10])
        lines.append(f"| {ref} | {len(qs)} | {links} |")
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
            if q["kind"] == "essay":
                kind = f"申論 {q['score']} 分" if q["score"] else "申論"
            else:
                kind = "測驗"
            lines += [
                '<div class="qb-item" markdown>',
                f'<p class="qb-meta"><span class="pb-count">{_exam_short(p["exam"])}</span>'
                f'<span class="pb-count">{kind}</span>'
                f'<a href="../../{p["id"]}/#{qid(q)}">{"看詳解" if q["answer"] else "看原題"} →</a></p>',
                "",
                f"《{_md_escape(p['subject'])}》第 {q['no']} 題：{_md_escape(q['text'])}",
                "",
            ]
            if q.get("options"):
                lines += [_md_escape(o) + "<br>" for o in q["options"]] + [""]
            if q["kind"] == "choice":
                lines += ['??? success "答案"', f"    **{q['key']}**", ""]
            lines += ["</div>", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
