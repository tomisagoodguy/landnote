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
from landnote.processors.exam_bank import EXAM_DIR, REPO_BLOB, SUB_MARKS, _md_escape, _pdf_text
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
CN_DIGITS = "一二三四五六七八九十"
# 答案內的條列起點：(一) 1. (1) ① 等，遇到就換行，其餘 PDF 斷行直接接回
LIST_START = re.compile(r"^([（(]?([一二三四五六七八九十]+|\d{1,2}|[a-zA-Z])[）).．、]|[①-⑳⑴-⒇])")


def _clean_lines(text: str) -> Tuple[str, List[str]]:
    """去掉頁首頁尾與重複行（舊版 PDF 以重複輸出模擬粗體），回傳 (考卷科目標題, 內文行)。"""
    text = text.translate(str.maketrans(SUB_MARKS))
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
    for q in questions:
        stem = "".join(q["stem"]).strip()
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


def _question_md(q: dict, refs: List[str], related: List[dict], answer_doc: Optional[dict] = None) -> List[str]:
    meta = [f'<span class="pb-count">第 {q["no"]} 題</span>']
    if q["score"]:
        meta.append(f'<span class="pb-count">{q["score"]} 分</span>')
    meta += [f'<span class="pb-count er-law">{r}</span>' for r in refs[:6]]
    out = ['<div class="qb-item" markdown>', f'<p class="qb-meta">{"".join(meta)}</p>', "",
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
    out += related_md([r for r in related if not answer_doc or r["file"] != answer_doc["file"]], 2)
    out += ["</div>", ""]
    return out


def _paper_page(p: dict, index: ArticleIndex, name: str) -> Tuple[str, Dict[str, List[dict]]]:
    """產生單份考卷頁，並回傳本卷每題的法條（供總覽頁統計）。"""
    from urllib.parse import quote

    essays = [q for q in p["questions"] if q["kind"] == "essay"]
    choices = [q for q in p["questions"] if q["kind"] == "choice"]
    lines = [
        HIDE_NAV,
        f"# {_paper_title(p)}",
        "",
        f'<p class="qb-meta"><a href="{REPO_BLOB + quote(p["pdf"])}" target="_blank" rel="noopener">原卷 PDF</a>'
        f'<a href="../">回{name}題目總覽</a></p>',
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
            lines += _question_md(q, refs, related, answer_doc)
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
            _write_family(docs_dir / READER_ROOT / slug, papers, index, name)
            nav.append((name, f"{READER_ROOT}/{slug}/index.md"))
    return nav


def _write_family(out: Path, papers: List[dict], index: ArticleIndex, name: str) -> None:
    from urllib.parse import quote

    out.mkdir(parents=True, exist_ok=True)
    hot: Dict[str, List[dict]] = defaultdict(list)
    readable = [p for p in papers if p["questions"]]
    for p in readable:
        page, refs = _paper_page(p, index, name)
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
        f"其中 **{n_ans}** 份附補習班詳解（可收合，先寫再看）。每題另附考點法條與自動推薦的老師相關文章。",
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
