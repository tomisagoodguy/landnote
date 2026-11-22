"""估價師考古題主題題庫：從考古題 PDF 抽出逐題文字、依主題分類，存成 JSON。

管線位置：讀 `地政考古題/<科目>/*估價師*.pdf` → 寫 `data/exam_bank/appraiser.json`，
site_generator 只讀 JSON 產生網頁（CI 的網站流程不需安裝 PDF 套件）。
新考古題由 update_exams.yml 下載後重跑本模組（`main.py exambank`）。
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

from landnote.config import DATA_DIR, EXAM_BANK_FILE

EXAM_DIR = DATA_DIR.parent / "地政考古題"

# 試卷開頭到「注意事項」最後一行都是表頭；標題字常被拆成單字一行，所以整段切掉而不逐行比對
HEADER_END = re.compile(r"不予計分|電子計算器|本國文字作答|座號|考試時間|^科\s*目|^目\s*[：:]")
HEADER_SCAN_LINES = 30
# 換頁時重複出現的頁首頁尾
NOISE_LINE = re.compile(r"^(代號\s*[：:]|頁次\s*[：:]|全一頁|座號|（請接背面）|（背面）|背面尚有試題)")
# 考選部 PDF 以私用區字元畫圈號：U+E129 起為 ①②③…，U+E0C6 起為 ⑴⑵⑶…
SUB_MARKS = {**{chr(0xE129 + i): c for i, c in enumerate("①②③④⑤⑥⑦⑧")},
             **{chr(0xE0C6 + i): c for i, c in enumerate("⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽")}}
SUB_START = "".join(SUB_MARKS.values())
TOP_MARK = re.compile(r"^([一二三四五六七八九十]+)、")
SCORE = re.compile(r"[（(]\s*(\d+)\s*分\s*[）)]")
FILE_NAME = re.compile(r"^\[(\d+)\]\[[^\]]*估價師\]\[(.+)\]\.pdf$")

# 各科主題：(主題名稱, 核心詞 regex, 一般詞 regex)。分數 = 核心詞命中數×3 + 一般詞命中數，
# 一題歸入分數最高的主題，同分取先列者；列表順序也是網頁上的主題順序。
APPRAISAL_TOPICS = [
    ("比較法", r"比較法|比較標的|比較實例|比較價格|區域因素|個別因素|近鄰地區|類似地區|價格日期調整",
     r"調整|案例|交易"),
    ("收益法", r"收益法|收益價格|直接資本化|折現現金流量|收益資本化率|折現率|期末價值|有效總收入|總費用",
     r"收益|淨收益|租金收入"),
    ("成本法與折舊", r"成本法|成本價格|重建成本|重置成本|折舊|耐用年數|樓層別效用比|地價分配率|拆分",
     r"建物|營造"),
    ("土地開發分析法", r"土地開發分析|預期開發|開發分析|最有效使用", r"開發|興建|合建"),
    ("租金、權利與特殊標的估價", r"租金|租賃權|地上權|區分地上權|容積|既成巷道|畸零地|公共設施保留地|歷史建築|"
     r"農作改良物|高氯離子|海砂屋|投資性不動產|素地|附建物|地下", r"權利|租"),
    ("都市更新、權利變換與市地重劃", r"都市更新|權利變換|更新單元|市地重劃|重劃", r"更新"),
    ("地價查估制度與大量估價", r"路線價|深度指數|公告地價|公告土地現值|基準地|地價區段|大量估價|計量模型|實價登錄|"
     r"徵收", r"地價|查估"),
    ("估價原則、價格種類與執業規範", r"價格種類|估價原則|相關原則|價值、價格|非市場價值|估價師法|估價師事務所|"
     r"業務範圍|審慎穩健|估價報告書|立場聲明|職業道德|課稅目的", r"原則"),
]
# 實務科題目常以方法名開頭（「收益法（40 分）…」），直接歸入該方法
APPRAISAL_LEAD = {"比較法": "比較法", "收益法": "收益法", "成本法": "成本法與折舊",
                  "土地開發分析法": "土地開發分析法", "價格決定": "估價原則、價格種類與執業規範"}
TOPICS: Dict[str, List[tuple]] = {
    "不動產估價理論": APPRAISAL_TOPICS,
    "不動產估價實務": APPRAISAL_TOPICS,
    "不動產投資分析": [
        ("投資決策：NPV、IRR 與現金流量", r"淨現值|NPV|內部報酬率|IRR|MIRR|回收期|互斥|WACC|資金成本|財務可行性",
         r"現金流量|現值|終值|年金|折現|開發成本"),
        ("收益型不動產與資本化率", r"資本化率|Cap Rate|NOI|營運淨收入|前門法|後門法|有效總收|Effective Gross|空置|閒置|"
         r"財務報表|租金收入", r"租金|收益|出租|房租"),
        ("抵押貸款與融資", r"抵押貸款|房貸|本利均等|攤還|逆向|以房養老|次貸|次級房|ARM|浮動利率|包裹式|提前清償|"
         r"貸款常數|債務保障", r"融資|償還"),
        ("財務槓桿與報酬率", r"槓桿|ROE|ROR|損益平衡|權益報酬", r"自有資金|報酬率"),
        ("不動產證券化、REITs 與 BOT", r"證券化|投資信託|REIT|私募|BOT|不良資產", r"基金"),
        ("風險與投資組合", r"CAPM|資本資產|風險值|標準差|變異數|實質選擇權|real option|跨國", r"風險|機率|情境"),
        ("市場分析與總體經濟", r"市場分析|通貨膨脹|貨幣供給|資本適足|ESG|綠色金融|氣候|預售屋|租買|Tenure|胃納|"
         r"非住宅財產|優先採行租賃|租屋中", r"市場|景氣|購屋|租屋|特性"),
    ],
    "不動產經濟學": [
        ("地租、地價與區位理論", r"地租|李嘉圖|Ricardo|屠能|競價|區位|單核心|集約度|布坎南|生產要素",
         r"地價|租金|都市土地|樓層"),
        ("外部性、公共財與市場失靈", r"外部性|公共財|集體財|Coase|柯思|寇斯|Pigou|庇古|尋租|市場失靈|產權|集體行動|"
         r"共享性|天坑|鄰避|廢污|污染", r"居民|社區"),
        ("租稅與轉嫁", r"轉嫁|稅|資本化效果|回饋|影響費", r"課徵"),
        ("住宅政策與住宅市場", r"社會住宅|租金補貼|房租管制|住宅補貼|負擔能力|自用住宅|出租住宅|租買",
         r"住宅|租屋|購屋"),
        ("農地、環境與能源", r"農業多功能|農地|綠能|種電|農電|梯田|碳排|水稻|氣候變遷", r"農業|環境"),
        ("土地開發與使用管制", r"使用管制|規劃管制|再開發|都市更新|市地重劃|使用變更|徵收|擴大都市計畫|大眾運輸|設廠",
         r"開發|都市計畫"),
        ("市場供需、資訊與總體經濟", r"利率|通貨膨脹|景氣循環|泡沫|信用管制|交易成本|資訊|訊息|經濟核|實價登錄",
         r"供給|需求|價格|市場"),
    ],
    "土地利用法規": [
        ("國土計畫法", r"國土計畫|國土功能分區|使用許可|應經申請同意", r"國土"),
        ("區域計畫與非都市土地管制", r"區域計畫|非都市土地|開發許可|分區變更|環境敏感|海域|使用地變更|農業用地變更",
         r"非都市|使用地|農地"),
        ("都市計畫與公共設施保留地", r"細部計畫|主要計畫|公共設施保留地|公共設施用地|新市區|都市計畫事業|"
         r"產業專用區|通盤檢討|計畫變更", r"都市計畫"),
        ("容積移轉與容積獎勵", r"容積移轉|容積", r"送出|接受基地"),
        ("都市更新與危老重建", r"都市更新|權利變換|危險及老舊|更新地區|更新事業", r"更新"),
        ("土地徵收", r"(?<!區段)徵收|撤銷徵收|徵收補償", r"補償|需用土地人"),
        ("區段徵收與市地重劃", r"區段徵收|抵價地|市地重劃|重劃", r"整體開發"),
    ],
    "民法物權與不動產法規": [
        ("所有權與共有", r"共有|應有部分|分割|分管|優先承購|及於土地之上下|面積最高額", r"處分|所有權"),
        ("抵押權", r"抵押權|抵押物|最高限額", r"抵押"),
        ("地上權、典權與用益物權", r"地上權|典權|農育權|不動產役權|永佃|時效取得|越界|基地出賣|租地建屋",
         r"出租|承租|占有"),
        ("土地登記", r"公信力|推定力|登記生效|登記對抗|登記錯誤|更正", r"登記"),
        ("土地稅：地價稅與土地增值稅", r"增值稅|地價稅|漲價總數額|原地價|累進稅率", r"稅"),
        ("地價制度與不動產估價師法", r"估價師法|估價師事務所|估價助理員|職業道德|地價區段|區段地價|公告地價|"
         r"申報地價|公告土地現值|規定地價|地價調查|宗地單位地價|估價技術規則|徵收補償市價",
         r"估價|地價"),
        ("土地政策與開發法規", r"市地重劃|重劃|區段徵收|都市更新|權利變換|公有土地|撥用|公共設施保留地|"
         r"預售屋|面積最高額|信託|容積移轉", r"徵收|開發"),
    ],
}
# 關鍵詞判斷不了的題目，人工指定：(科目, 年度, 題號) → 主題
OVERRIDES = {
    ("不動產估價理論", 101, 4): "估價原則、價格種類與執業規範",
    ("不動產投資分析", 103, 3): "抵押貸款與融資",
    ("民法物權與不動產法規", 106, 1): "地上權、典權與用益物權",
    ("民法物權與不動產法規", 114, 1): "土地政策與開發法規",
}
CASE_TOPIC = "綜合估價案例（估價報告書）"
CASE_MIN_SCORE = 70  # 實務科 70 分以上的大題是整份估價報告書的綜合案例


def _pdf_text(path: Path) -> str:
    try:
        import pymupdf
    except ImportError:  # 舊版只提供 fitz 名稱
        import fitz as pymupdf
    with pymupdf.open(path) as doc:
        return "".join(page.get_text() for page in doc)


def _join_lines(lines: List[str]) -> str:
    """PDF 斷行還原：中文直接相接；表格儲存格等短行以空白分隔，句末標點後換段。"""
    out = ""
    prev = ""
    for line in lines:
        if out and line[0] in SUB_START and not out.endswith("\n"):
            out += "\n"
        if not out or out.endswith("\n"):
            out += line
        elif len(line) <= 14 and len(prev) <= 14:
            out += " " + line
        else:
            out += line
        if re.search(r"(分\s*[）)]|[。？?：:])$", line):
            out += "\n"
        prev = line
    return re.sub(r"\n{2,}", "\n", out).strip()


# 舊版 PDF 常用 CJK 相容字與康熙部首（如「不動產」的不、「都更」的更），外觀相同但搜尋與比對都會失敗
CJK_COMPAT = re.compile("[⼀-⿟豈-﫿\U0002f800-\U0002fa1f]")


def normalize_cjk(text: str) -> str:
    """把 CJK 相容字與康熙部首換成一般漢字。"""
    return CJK_COMPAT.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)


def split_questions(text: str) -> List[str]:
    """把一份試卷切成逐題文字。優先以「一、二、」切；沒有題號（PDF 用圖形編號）時以配分結尾切。"""
    # 「（每小題5 分，共25 分）」統一成「（25 分）」，配分加總才不會漏
    text = re.sub(r"[（(]\s*每小題[^）)]*?共\s*(\d+)\s*分\s*[）)]", r"（\1 分）", text)
    text = normalize_cjk(text.translate(str.maketrans(SUB_MARKS)))
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    head = [i for i, ln in enumerate(lines[:HEADER_SCAN_LINES]) if HEADER_END.search(ln)]
    if head:
        lines = lines[head[-1] + 1:]
    lines = [ln for ln in lines if not NOISE_LINE.match(ln)]

    marks = [i for i, ln in enumerate(lines) if TOP_MARK.match(ln)]
    if any(ln.startswith("壹、") for ln in lines):
        # 整份估價報告書案例（壹、撰寫說明 貳、委託條件…），其中「一、」是條件而非題號
        chunks = [lines]
    elif len(marks) >= 2:
        bounds = marks + [len(lines)]
        chunks = [lines[a:b] for a, b in zip(bounds, bounds[1:], strict=False)]
    else:
        chunks, cur = [], []
        for ln in lines:
            cur.append(ln)
            if SCORE.search(ln) and re.search(r"分\s*[）)]\s*$", ln):
                chunks.append(cur)
                cur = []
        if cur and chunks:
            chunks[-1].extend(cur)
    questions = []
    for chunk in chunks:
        q = _join_lines(chunk)
        q = TOP_MARK.sub("", q, count=1).strip()
        if SCORE.search(q):
            questions.append(q)
    return questions


def classify(subject: str, text: str, score: int = 0) -> str:
    """依關鍵詞加權分數歸類；實務科的整份案例題另歸綜合案例。"""
    if subject == "不動產估價實務" and score >= CASE_MIN_SCORE:
        return CASE_TOPIC
    if TOPICS.get(subject) is APPRAISAL_TOPICS:
        lead = re.match(r"(比較法|收益法|成本法|土地開發分析法|價格決定)\s*[（(]", text)
        if lead:
            return APPRAISAL_LEAD[lead.group(1)]
    return best_topic(TOPICS.get(subject, []), text)


def best_topic(topics: List[tuple], text: str) -> str:
    """在 (主題, 核心詞, 一般詞) 清單中取分數最高者；都沒命中回「其他」。"""
    best, best_score = "其他", 0
    for topic, strong, weak in topics:
        points = 3 * len(re.findall(strong, text)) + len(re.findall(weak, text))
        if points > best_score:
            best, best_score = topic, points
    return best


def topic_order(subject: str) -> List[str]:
    """網頁上的主題排列順序。"""
    names = [t[0] for t in TOPICS.get(subject, [])]
    if subject == "不動產估價實務":
        names.insert(0, CASE_TOPIC)
    return names + ["其他"]


# 網頁順序與網址（英文 slug 讓網址穩定、好分享）
SUBJECT_PAGES = [
    ("不動產估價理論", "theory", "估價理論"),
    ("不動產估價實務", "practice", "估價實務"),
    ("不動產投資分析", "investment", "投資分析"),
    ("不動產經濟學", "economics", "不動產經濟學"),
    ("土地利用法規", "land-use-law", "土地利用法規"),
    ("民法物權與不動產法規", "civil-law", "民法物權與不動產法規"),
]
BANK_DIR = "exam-bank"
REPO_BLOB = "https://github.com/tomisagoodguy/landnote/blob/main/landnotev3/地政考古題/"
HIDE_NAV = "---\nhide:\n  - navigation\n---\n"


def _md_escape(line: str) -> str:
    """題目原文放進 Markdown：跳脫會被當成語法的字元。"""
    line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    line = re.sub(r"([*_`|\[\]\\])", r"\\\1", line)
    return re.sub(r"^(\d+)([.)])", r"\1\\\2", line)  # 避免「1.」變成清單


# 估價師試題總評、考題命中等文章（標題如「105年不動產估價師試題總評(一)」），依年度掛到該年題目
COMMENTARY_TITLE = re.compile(r"(\d{2,3})\s*年.*估價師.*(總評|命中|解析|詳解)")
RELATED_K = 3  # 每題推薦文章數


def _commentary_by_year(docs: List[dict]) -> Dict[int, List[dict]]:
    """從文章索引找出估價師試題總評，回傳 {民國年: [文章…]}，同年依標題排序。"""
    out: Dict[int, List[dict]] = {}
    for d in docs:
        m = COMMENTARY_TITLE.search(d["title"])
        if m:
            out.setdefault(int(m.group(1)), []).append(d)
    return {y: sorted(ds, key=lambda d: d["title"]) for y, ds in out.items()}


def _post_link(d: dict) -> str:
    """題庫頁（exam-bank/<科目>.md）連到 blog 文章原始檔，由 MkDocs 換成實際網址。"""
    who = f"｜{d['author']}" if d.get("author") else ""
    return f"[{_md_escape(d['title'])}](<../{d['path']}>){who}"


def _subject_page(subject: str, title: str, items: List[dict], index=None,
                  commentary: Optional[Dict[int, List[dict]]] = None,
                  practice: Optional[List[tuple]] = None) -> str:
    """產生單科主題題庫頁；有文章索引時，每題附相關文章與該年度試題總評。"""
    from datetime import date
    from urllib.parse import quote

    from landnote.processors.exam_reader import related_md, teacher_answer_md
    from landnote.processors.law_timeline import LawTimeline, law_refs

    commentary = commentary or {}
    timeline = LawTimeline()

    years = sorted({i["year"] for i in items})
    by_topic: Dict[str, List[dict]] = {}
    for i in items:
        by_topic.setdefault(i["topic"], []).append(i)
    topics = [t for t in topic_order(subject) if t in by_topic]

    lines = [
        HIDE_NAV,
        f"# {title}：主題題庫",
        "",
        f"專技高考不動產估價師「{subject}」民國 {years[0]}–{years[-1]} 年共 **{len(items)}** 題，依主題分類、"
        "同主題由新到舊排列。建議先挑一個主題限時寫，寫不出來的觀念就是今天的任務。",
        "",
        *(["想多練附詳解的題目？高普考、地方特考同類科目逐題讀："
           + "、".join(f"[{name}](../exam-reader/{slug}/index.md)" for name, slug in practice), ""]
          if practice else []),
        '!!! note "題目文字由 PDF 自動擷取"',
        "    表格、圖形在擷取時會變成一行數字，計算題請點「原卷 PDF」對照原始版面。"
        + ("「延伸閱讀」依文字相似度自動推薦，不一定與題目完全對應，點標題可直接展開全文；"
           "補習班老師寫過的擬答會附在題目下方。" if index else ""),
        "",
        "| 主題 | 題數 | 配分合計 | 最近出題 | 出題年度 |",
        "|---|---:|---:|---:|---|",
    ]
    # 預設 slugify 會濾掉中文，標題改用固定 id（topic-1…）
    for n, t in enumerate(topics, 1):
        qs = by_topic[t]
        ys = sorted({q["year"] for q in qs}, reverse=True)
        lines.append(f"| [{t}](#topic-{n}) | {len(qs)} | {sum(q['score'] for q in qs)} | {ys[0]} | "
                     f"{'、'.join(map(str, ys))} |")
    for n, t in enumerate(topics, 1):
        lines += ["", f"## {t} {{#topic-{n}}}", ""]
        for q in sorted(by_topic[t], key=lambda q: (-q["year"], q["no"])):
            pdf = REPO_BLOB + quote(q["pdf"])
            lines += [
                '<div class="qb-item" markdown>',
                f'<p class="qb-meta"><span class="pb-count">{q["year"]} 年</span>'
                f'<span class="pb-count">第 {q["no"]} 題</span><span class="pb-count">{q["score"]} 分</span>'
                f'<a href="{pdf}" target="_blank" rel="noopener">原卷 PDF</a></p>',
                "",
            ]
            lines += [_md_escape(ln) + "\n" for ln in q["text"].splitlines() if ln.strip()]
            if timeline:
                # 以出題年度年底為基準：之後的修法才提醒（同年稍晚的修法會漏標，但不會誤標）
                lines += timeline.notice(q["text"], date(q["year"] + 1911, 12, 31),
                                         f"本題出題（民國 {q['year']} 年）後，題目引用的")
            reviews = commentary.get(q["year"], [])
            if reviews:
                lines += [f"**{q['year']} 年試題總評**：" + "、".join(_post_link(d) for d in reviews), ""]
            if index:
                answer_doc = index.teacher_answer(q["text"])
                if answer_doc:
                    lines += teacher_answer_md(answer_doc, 1)
                shown = {d["file"] for d in reviews} | ({answer_doc["file"]} if answer_doc else set())
                related = [d for d in index.related(q["text"], law_refs(q["text"]), RELATED_K)
                           if d["file"] not in shown]
                lines += related_md(related, 1, "延伸閱讀")
            lines += ["</div>", ""]
    return "\n".join(lines)


def write_pages(docs_dir: Path, bank_file: Path = EXAM_BANK_FILE,
                posts_dir: Optional[List[Path]] = None,
                practice: Optional[Dict[str, List[tuple]]] = None) -> List[tuple]:
    """產生題庫網頁到 docs/exam-bank/，回傳 mkdocs nav 用的 [(標題, 路徑)]；無題庫時回空。

    posts_dir 預設為 [docs/blog/posts]（site_generator 已先寫好文章），用來比對每題的相關文章；
    資料夾不存在或沒有文章時，題庫照常產生、只是不附延伸閱讀。
    """
    from landnote.processors.exam_reader import ArticleIndex

    if not bank_file.exists():
        return []
    items = json.loads(bank_file.read_text(encoding="utf-8"))
    out = docs_dir / BANK_DIR
    out.mkdir(parents=True, exist_ok=True)

    posts_dir = posts_dir or [docs_dir / "blog" / "posts"]
    index = ArticleIndex(posts_dir) if any(f for p in posts_dir for f in p.glob("*.md")) else None
    commentary = _commentary_by_year(index.docs) if index else {}

    nav = [("題庫總覽", f"{BANK_DIR}/index.md")]
    cards = []
    for idx, (subject, slug, title) in enumerate(SUBJECT_PAGES):
        qs = [i for i in items if i["subject"] == subject]
        if not qs:
            continue
        page = _subject_page(subject, title, qs, index, commentary, (practice or {}).get(subject))
        (out / f"{slug}.md").write_text(page, encoding="utf-8")
        nav.append((title, f"{BANK_DIR}/{slug}.md"))
        counts: Dict[str, int] = {}
        for q in qs:
            counts[q["topic"]] = counts.get(q["topic"], 0) + 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
        cards += [
            f'    <a href="{slug}/" class="feature-card c{idx % 4}">',
            f'        <div class="feature-card__head"><span class="pb-count">{len(qs)} 題</span></div>',
            f"        <h3>{title}</h3>",
            f"        <p>最常考：{'、'.join(f'{t}（{n}）' for t, n in top)}</p>",
            "    </a>",
        ]
    years = sorted({i["year"] for i in items})
    index = [
        "---\nhide:\n  - navigation\n  - toc\n---\n",
        "# 估價師主題題庫",
        "",
        f"把專技高考不動產估價師民國 {years[0]}–{years[-1]} 年六科專業科目、共 **{len(items)}** 題申論與計算題，"
        "依主題重新分類（國文不列入）。每科頁面最上方有各主題的題數與出題年度，"
        "一眼看出哪些主題年年考、哪些很久沒出。",
        "",
        "**建議用法（逆向讀書法）**：先挑一個主題、限時寫最近三年的題目 → 標出卡關的觀念 → "
        "只針對卡關處回頭讀書 → 再寫更早的題目驗收。",
        "",
        '<div class="feature-grid">',
        *cards,
        "</div>",
    ]
    (out / "index.md").write_text("\n".join(index), encoding="utf-8")
    return nav


def build(exam_dir: Path = EXAM_DIR, out_file: Path = EXAM_BANK_FILE) -> Optional[Path]:
    """掃描估價師考古題 PDF，輸出題庫 JSON；回傳輸出路徑（無資料時回 None）。"""
    items = []
    for pdf in sorted(exam_dir.glob("*/*估價師*.pdf")):
        m = FILE_NAME.match(pdf.name)
        if not m or m.group(2).startswith("國文"):
            continue  # 國文為作文，不做主題分類
        year, subject = int(m.group(1)), m.group(2)
        for no, q in enumerate(split_questions(_pdf_text(pdf)), 1):
            score = sum(int(s) for s in SCORE.findall(q))
            items.append({
                "year": year,
                "subject": subject,
                "no": no,
                "score": score,
                "topic": OVERRIDES.get((subject, year, no)) or classify(subject, q, score),
                "text": q,
                "pdf": f"{pdf.parent.name}/{pdf.name}",
            })
    if not items:
        return None
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_file
