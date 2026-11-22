"""考古題閱讀版：把考卷 PDF 拆成逐題網頁，附詳解、考點法條與相關老師文章。

管線位置（與 exam_bank 同為兩段式）：
- `build()`：讀 `地政考古題/<土地法規家族>/*.pdf` → 寫 `data/exam_bank/land_law.json`（需 pymupdf，
  由 `main.py exambank` 在每月考古題更新後執行）。
- `write_pages()`：site_generator 讀 JSON 與已產生的 blog 文章，比對相關文章後寫 `docs/exam-reader/`。
  比對在產生網站時做，文章每週更新後推薦也會跟著更新。

目前只做土地法規家族（PoC）；其他科目沿用同一套解析，只需調整 `FAMILY_DIR`。
"""

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from landnote.config import ARTICLES_DIR, LAND_LAW_READER_FILE
from landnote.processors.exam_bank import EXAM_DIR, REPO_BLOB, SUB_MARKS, _md_escape, _pdf_text
from landnote.processors.law_timeline import law_refs

FAMILY_DIR = re.compile(r"土地法|土地行政")  # 民法與土地法規等歸民法家族，與考古題頁一致
FAMILY_EXCLUDE = re.compile(r"民法")
FILE_NAME = re.compile(r"^\[(\d+)\]\[([^\]]+)\]\[(.+)\]\.pdf$")
READER_DIR = "exam-reader/land-law"
MIN_TEXT = 50  # 少於此字數視為掃描檔，只提供原卷連結

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


def build(exam_dir: Path = EXAM_DIR, out_file: Path = LAND_LAW_READER_FILE) -> Optional[Path]:
    """掃描土地法規家族考卷，輸出閱讀版 JSON；回傳輸出路徑（無資料時回 None）。"""
    papers = []
    for folder in sorted(p for p in exam_dir.iterdir() if p.is_dir()):
        if not FAMILY_DIR.search(folder.name) or FAMILY_EXCLUDE.search(folder.name):
            continue
        for pdf in sorted(folder.glob("*.pdf")):
            m = FILE_NAME.match(pdf.name)
            if not m:
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
    if not papers:
        return None
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(papers, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_file


# 考點法條：抽取規則與法規清單統一在 law_timeline（法規時效標示也用同一份）


# ---- 相關文章比對（中文字二元組 TF-IDF） ----

def _tokens(text: str) -> List[str]:
    grams = []
    for run in re.findall(r"[一-鿿]+", text):
        grams += [run[i:i + 2] for i in range(len(run) - 1)]
    return grams


class ArticleIndex:
    """以 blog 文章建 TF-IDF 索引；法條完全相同時額外加分。"""

    LAW_BONUS = 0.08
    MIN_SCORE = 0.12

    def __init__(self, posts_dir: Path, articles_dir: Path = ARTICLES_DIR):
        teacher = {}
        for f in articles_dir.glob("*.md"):  # 原始檔名「編號_標題,某某老師.md」
            m = re.match(r"^(\d+)_.*,(.+?)\.md$", f.name)
            if m:
                teacher[m.group(1)] = m.group(2)
        self.docs: List[dict] = []
        df: Counter = Counter()
        raw_tf = []
        for f in sorted(posts_dir.glob("*.md")):
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
            self.docs.append({"file": f.name, "title": title, "author": author,
                              "laws": {r for r in law_refs(body) if "第" in r}})
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


def _question_md(q: dict, refs: List[str], related: List[dict]) -> List[str]:
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
    if related:
        out += ['<p class="er-related-title">延伸閱讀：老師相關文章</p>', ""]
        for r in related:
            who = f"｜{r['author']}" if r["author"] else ""
            out.append(f"- [{_md_escape(r['title'])}](<../../blog/posts/{r['file']}>){who}")
        out.append("")
    out += ["</div>", ""]
    return out


def _paper_page(p: dict, index: ArticleIndex) -> Tuple[str, Dict[str, List[dict]]]:
    """產生單份考卷頁，並回傳本卷每題的法條（供總覽頁統計）。"""
    from urllib.parse import quote

    essays = [q for q in p["questions"] if q["kind"] == "essay"]
    choices = [q for q in p["questions"] if q["kind"] == "choice"]
    lines = [
        HIDE_NAV,
        f"# {_paper_title(p)}",
        "",
        f'<p class="qb-meta"><a href="{REPO_BLOB + quote(p["pdf"])}" target="_blank" rel="noopener">原卷 PDF</a>'
        f'<a href="../">回土地法規題目總覽</a></p>',
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
            lines += _question_md(q, refs, related)
            for r in refs:
                if "第" in r:
                    refs_by_q.setdefault(r, []).append({"paper": p, "no": q["no"], "kind": q["kind"]})
    return "\n".join(lines), refs_by_q


def write_pages(docs_dir: Path, posts_dir: Path, data_file: Path = LAND_LAW_READER_FILE) -> List[tuple]:
    """產生 docs/exam-reader/land-law/，回傳 mkdocs nav 用的 [(標題, 路徑)]；無資料時回空。"""
    if not data_file.exists():
        return []
    papers = json.loads(data_file.read_text(encoding="utf-8"))
    out = docs_dir / READER_DIR
    out.mkdir(parents=True, exist_ok=True)
    index = ArticleIndex(posts_dir)

    hot: Dict[str, List[dict]] = defaultdict(list)
    readable = [p for p in papers if p["questions"]]
    for p in readable:
        page, refs = _paper_page(p, index)
        (out / f"{p['id']}.md").write_text(page, encoding="utf-8")
        for r, qs in refs.items():
            hot[r] += qs

    from urllib.parse import quote
    n_q = sum(len(p["questions"]) for p in readable)
    years = sorted({p["year"] for p in papers})
    lines = [
        "---\nhide:\n  - navigation\n  - toc\n---\n",
        "# 土地法規：逐題閱讀",
        "",
        f"把土地法規家族（土地法規、土地法規概要、土地法大意、土地行政…）民國 {years[0]}–{years[-1]} 年 "
        f"**{len(papers)}** 份考古題拆成網頁，共 **{n_q}** 題。每題附補習班詳解（可收合，先寫再看）、"
        "考點法條，以及自動推薦的老師相關文章。",
        "",
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
            name = f"[{p['subject']}]({p['id']}.md)"
        else:
            desc = "無法自動拆題（掃描檔或特殊排版），請看原卷"
            name = f'[{p["subject"]}]({REPO_BLOB + quote(p["pdf"])}){{target="_blank"}}'
        lines.append(f"| {p['year']} | {p['exam']} | {name} | {desc} | {'✓' if p['has_answer'] else ''} |")
    (out / "index.md").write_text("\n".join(lines), encoding="utf-8")
    return [("土地法規逐題讀", f"{READER_DIR}/index.md")]
