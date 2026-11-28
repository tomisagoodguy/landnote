"""考點心智圖：把歷屆考題掛到「法規編章節」與「主題」上畫成心智圖，並把同一概念在不同科目、年度的考法串成一張圖。

管線位置：site_generator 在 exam_reader.write_pages 之後呼叫 `write_pages()`。讀 `data/exam_bank/<slug>.json`
（逐題讀資料）與 `data/law_articles.json` 的 `chapters`（law_timeline.build 寫入的編章節），
寫 `docs/exam-reader/mindmap/`：

- `<slug>.md`：各科心智圖頁，資料在 `<slug>-law.json`（法規 → 編 → 章 → 條 → 題目）與 `<slug>-topic.json`
  （主題 → 重複考點、常考法條、近年題目）。
- `concepts/<id>.md`：跨科目概念頁（概念 → 科目 → 年度 → 題目），資料在 `concepts/<id>.json`。
  概念有兩種：`CONCEPTS` 的關鍵詞（題目文字命中）與兩科以上都考過的法條，只收兩科以上都出現的。
- `index.md`：總覽與跨科目概念圖（`concepts.json`）。

頁面只放 `.lm-mindmap` 容器，study_tools.js 的 `initMindmaps` 從 CDN 載入 markmap 並讀 JSON 繪製。
節點內容是 HTML；題目節點帶 `data-q`（與熟練度標記 qmark_v1 同鍵），前端依標記上色。
"""

import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from landnote.config import EXAM_READER_DATA_DIR, LAW_ARTICLES_FILE
from landnote.processors.exam_bank import _md_escape
from landnote.processors.exam_reader import (
    HIDE_NAV,
    LAW_DIR,
    LAW_PAGE_MIN,
    READER_ROOT,
    READER_TOPICS,
    RECENT_YEARS,
    TOPIC_DIR,
    LawIndex,
    SimilarIndex,
    _article_key,
    _exam_short,
    _law_of,
    _law_slug,
    _topic_of,
    available,
    data_file,
    qid,
)

MINDMAP_DIR = "mindmap"  # exam-reader/mindmap/
CONCEPT_DIR = "concepts"  # exam-reader/mindmap/concepts/
ARTICLE_QS_MAX = 6  # 條文節點下列出的題目數（新到舊），其餘連到法條比較頁
TOPIC_CLUSTERS_MAX = 8
TOPIC_LAWS_MAX = 6
TOPIC_RECENT_YEARS = 3  # 主題節點下「近年題目」列幾個年度
YEAR_QS_MAX = 8
CONCEPT_FAMILY_QS_MAX = 30  # 概念圖每科最多列幾題，其餘看頁面下方清單
CONCEPT_RELATED_MAX = 8
LAW_CONCEPT_MIN = 4  # 法條概念至少要幾題（兩科以上）才做概念頁，避免一題一頁的零碎頁面
SNIPPET = 30

# 跨科目概念：(名稱, regex)。比對題目與選項文字（不含詳解，詳解常順帶提到其他制度）；
# 只有兩科以上都考過的才產生概念頁，所以清單可以放寬，不會產生單科的空頁。
CONCEPTS: List[Tuple[str, str]] = [
    ("區段徵收", r"區段徵收|抵價地"),
    ("市地重劃", r"市地重劃"),
    ("農地重劃", r"農地重劃"),
    ("農村社區土地重劃", r"農村社區土地重劃"),
    # 「徵收」也用於稅捐（徵收地價稅），只認土地徵收的說法
    (
        "一般徵收與徵收補償",
        r"土地徵收|徵收土地(?!.{0,3}稅)|徵收補償|需用土地人|被徵收|徵收計畫|一併徵收|"
        r"徵收.{0,2}(?:處分|核准|公告)|徵收條例",
    ),
    ("徵收土地收回", r"收回權|申請收回|照原徵收補償價額收回"),
    ("容積移轉與容積獎勵", r"容積移轉|容積獎勵|送出基地|接受基地|容積代金"),
    ("都市更新與權利變換", r"都市更新|權利變換"),
    ("危老重建", r"危險及老舊|危老"),
    ("都市計畫與通盤檢討", r"都市計畫|通盤檢討|細部計畫|主要計畫"),
    ("公共設施保留地", r"公共設施保留地"),
    ("國土計畫與國土功能分區", r"國土計畫|國土功能分區"),
    ("非都市土地使用管制", r"非都市土地|使用地變更|開發許可"),
    ("成長管理與土地使用規劃", r"成長管理|智慧成長|緊湊城市|大眾運輸導向|TOD"),
    ("照價收買與漲價歸公", r"照價收買|漲價歸公"),
    ("平均地權與規定地價", r"平均地權|規定地價"),
    ("公告地價與申報地價", r"公告地價|申報地價"),
    ("公告土地現值", r"公告土地現值|公告現值"),
    ("地價稅", r"地價稅"),
    ("土地增值稅", r"土地增值稅|增值稅"),
    ("自用住宅用地優惠稅率", r"自用住宅用地"),
    ("房地合一稅", r"房地合一"),
    ("房屋稅與囤房稅", r"房屋稅|囤房"),
    ("遺產稅與贈與稅", r"遺產稅|贈與稅"),
    ("空地與荒地", r"空地|荒地"),
    ("外國人取得土地", r"外國人"),
    ("共有土地處分（土地法第34條之1）", r"第\s*34\s*條之\s*1|34-1|共有土地.{0,10}處分|多數決"),
    ("優先購買權與優先承買權", r"優先購買|優先承買"),
    ("耕地租用與三七五減租", r"三七五|耕地租用|耕地.{0,4}租約|減租"),
    ("基地租用與地上權推定", r"基地租用|租用基地|推定.{0,6}地上權"),
    ("時效取得", r"時效取得"),
    ("地上權", r"(?<!區分)地上權"),
    ("區分地上權", r"區分地上權"),
    ("不動產役權", r"不動產役權|地役權"),
    ("抵押權與最高限額抵押權", r"抵押權"),
    ("典權", r"典權"),
    ("農育權", r"農育權"),
    ("區分所有與公寓大廈", r"區分所有|公寓大廈|共用部分|專有部分"),
    ("共有物分割", r"共有物分割|分割共有物|裁判分割"),
    ("預告登記", r"預告登記"),
    ("限制登記與囑託登記", r"限制登記|囑託登記|查封|假扣押|假處分"),
    ("登記公信力與損害賠償", r"公信力|登記錯誤|登記儲金"),
    ("繼承登記與未辦繼承", r"繼承登記|未辦繼承|逾期未辦"),
    ("信託", r"信託"),
    ("實價登錄", r"實價登錄|實價申報|成交案件"),
    ("地政士與不動產經紀", r"地政士|經紀業|經紀人"),
    ("租賃住宅與社會住宅", r"租賃住宅|社會住宅|包租|代管"),
    ("住宅政策與住宅補貼", r"住宅政策|住宅補貼|居住正義|住宅法"),
    # 單寫「地租」多半是地上權、基地租用的租金，只認經濟學的地租理論
    ("地租理論", r"地租理論|差額地租|絕對地租|獨占地租|經濟地租|契約地租|地租.{0,3}(?:學說|形成)|李嘉圖|杜能|屠能"),
    ("外部性與公共財", r"外部性|外部效果|公共財"),
    ("土地使用分區管制", r"使用分區|分區管制"),
    ("比較法", r"比較法"),
    ("收益法與折現現金流量", r"收益法|直接資本化|折現現金流量|DCF"),
    ("成本法", r"成本法|重建成本|重置成本"),
    ("土地開發分析法", r"土地開發分析|開發分析法"),
    ("最有效使用", r"最有效使用"),
    ("淨現值與內部報酬率", r"淨現值|NPV|內部報酬率|IRR"),
    ("不動產證券化", r"證券化|REITs?|REAT"),
    ("租稅法律主義與實質課稅", r"租稅法律主義|實質課稅"),
    ("訴願與行政救濟", r"訴願|行政訴訟|行政救濟"),
    ("比例原則與信賴保護", r"比例原則|信賴保護"),
    ("政府採購", r"採購|招標|決標"),
]


# ---- 資料 ----


class _Family:
    """一科的題目與每題的法條、主題。"""

    def __init__(self, slug: str, name: str, papers: List[dict], laws: LawIndex):
        self.slug, self.name = slug, name
        self.papers = [p for p in papers if p["questions"]]
        for p in self.papers:
            p["slug"] = slug
        self.items: List[Tuple[dict, dict]] = [(p, q) for p in self.papers for q in p["questions"]]
        self.latest = max((p["year"] for p in self.papers), default=0)
        self.refs: Dict[Tuple[str, str], List[str]] = {}
        self.by_ref: Dict[str, List[Tuple[dict, dict]]] = defaultdict(list)
        for p, q in self.items:
            refs = [r for r, _ in laws.refs(q)]
            self.refs[(p["id"], qid(q))] = refs
            for r in refs:
                self.by_ref[r].append((p, q))

    def law_page(self, ref: str) -> Optional[str]:
        """這一科有比較頁的法條 → 檔名（與 exam_reader._law_page_names 同規則）。"""
        return self._law_pages.get(ref)

    def set_law_pages(self, laws: LawIndex) -> None:
        self._law_pages = {r: _law_slug(r, laws.timeline) for r, qs in self.by_ref.items() if len(qs) >= LAW_PAGE_MIN}


def _outline(chapters: Dict[str, List[list]]) -> Dict[str, Dict[str, Tuple[str, ...]]]:
    """法規 → {條號 → (編, 章, 節…) 標題路徑}。"""
    out: Dict[str, Dict[str, Tuple[str, ...]]] = {}
    for law, heads in chapters.items():
        stack: List[Tuple[int, str]] = []
        paths: Dict[str, Tuple[str, ...]] = {}
        for level, title, nos in heads:
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            for no in nos:
                paths[no] = tuple(t for _, t in stack)
        out[law] = paths
    return out


def _article_no(ref: str) -> str:
    """「土地法第34條之1」→「34-1」（law_articles.json 的條號寫法）。"""
    main, sub = _article_key(ref)
    return f"{main}-{sub}" if sub else str(main)


# ---- 節點 ----


def _node(content: str, children: Optional[List[dict]] = None) -> dict:
    out: dict = {"content": content}
    if children:
        out["children"] = children
    return out


def _snippet(text: str, n: int = SNIPPET, markdown: bool = False) -> str:
    """題目摘要；預設跳脫成心智圖節點用的 HTML，markdown=True 時改跳脫 Markdown 語法（頁面清單用）。"""
    s = re.sub(r"\s+", "", text)
    s = re.sub(r"^[（(]\s*[A-D#＃、,或]*\s*[）)]", "", s)  # 測驗題開頭的答案括號
    s = s[:n] + ("…" if len(s) > n else "")
    return _md_escape(s) if markdown else html.escape(s)


def _count(n: int, unit: str = "題") -> str:
    return f'<small class="lm-n">{n} {unit}</small>'


def _q_href(p: dict, q: dict, up: str) -> str:
    return f"{up}{p['slug']}/{p['id']}/#{qid(q)}"


def _q_node(p: dict, q: dict, up: str, with_subject: bool = False) -> dict:
    """題目葉節點；up 為到 exam-reader/ 的相對網址。"""
    kind = "申" if q["kind"] == "essay" else "測"
    where = f"{p['year']} {_exam_short(p['exam'])}" + (f"《{p['subject']}》" if with_subject else "")
    return _node(
        f'<span class="lm-kind">{kind}</span><a href="{_q_href(p, q, up)}" data-q="{p["id"]}-{qid(q)}">'
        f"{html.escape(where)}</a> {_snippet(q['text'])}"
    )


def _newest(qs: List[Tuple[dict, dict]]) -> List[Tuple[dict, dict]]:
    return sorted(qs, key=lambda pq: (-pq[0]["year"], pq[0]["exam"], pq[1]["kind"], pq[1]["no"]))


def _uniq(qs: List[Tuple[dict, dict]]) -> List[Tuple[dict, dict]]:
    seen, out = set(), []
    for p, q in qs:
        key = (p["id"], qid(q))
        if key not in seen:
            seen.add(key)
            out.append((p, q))
    return out


def _recent(qs: List[Tuple[dict, dict]], latest: int) -> int:
    return sum(p["year"] > latest - RECENT_YEARS for p, _ in qs)


# ---- 各科：法規架構圖 ----


def _article_node(fam: _Family, ref: str, laws: LawIndex, up: str, label: str) -> dict:
    qs = _newest(fam.by_ref[ref])
    page = fam.law_page(ref)
    href = f"{up}{fam.slug}/{LAW_DIR}/{page}/" if page else _q_href(*qs[0], up)
    recent = _recent(qs, fam.latest)
    hot = f'<span class="lm-hot" title="近 {RECENT_YEARS} 年 {recent} 題">近{recent}</span>' if recent >= 2 else ""
    gist = re.sub(r"\s+", "", laws.text.get(ref, ""))[:16]
    content = f'<a href="{href}">{html.escape(label)}</a> {_count(len(qs))}{hot}' + (
        f' <span class="lm-gist">{html.escape(gist)}…</span>' if gist else ""
    )
    children = [_q_node(p, q, up) for p, q in qs[:ARTICLE_QS_MAX]]
    if len(qs) > ARTICLE_QS_MAX and page:
        children.append(_node(f'<a href="{href}">看全部 {len(qs)} 題 →</a>'))
    return _node(content, children)


def _law_tree(fam: _Family, laws: LawIndex, outline: Dict[str, Dict[str, Tuple[str, ...]]], up: str) -> dict:
    """科目 → 法規 → 編 → 章 → 節 → 條 → 題目。"""
    by_law: Dict[str, List[str]] = defaultdict(list)
    for ref in fam.by_ref:
        by_law[_law_of(ref)].append(ref)
    law_qs = {law: _uniq([pq for r in refs for pq in fam.by_ref[r]]) for law, refs in by_law.items()}
    children = []
    for law in sorted(by_law, key=lambda law: -len(law_qs[law])):
        paths = outline.get(law, {})
        # 巢狀 dict：標題 → 子樹；"__refs__" 放直屬條文
        tree: dict = {}
        for ref in by_law[law]:
            node = tree
            for title in paths.get(_article_no(ref), ()):
                node = node.setdefault(title, {})
            node.setdefault("__refs__", []).append(ref)

        def build(node: dict, law: str = law) -> Tuple[List[dict], List[Tuple[dict, dict]], Tuple[int, int]]:
            """回傳 (子節點, 涵蓋的題目, 排序鍵＝最小條號)；子節點依條號排，與法規本身的順序一致。"""
            parts = []
            for ref in node.get("__refs__", []):
                parts.append((_article_key(ref), _article_node(fam, ref, laws, up, ref[len(law) :]), fam.by_ref[ref]))
            for title, sub in node.items():
                if title == "__refs__":
                    continue
                kids, qs, key = build(sub, law)
                parts.append((key, _node(f"{html.escape(title)} {_count(len(qs))}", kids), qs))
            parts.sort(key=lambda t: t[0])
            covered = _uniq([pq for _, _, qs in parts for pq in qs])
            return [n for _, n, _ in parts], covered, parts[0][0] if parts else (0, 0)

        kids, _, _ = build(tree)
        children.append(_node(f"<strong>{html.escape(law)}</strong> {_count(len(law_qs[law]))}", kids))
    n = len(_uniq([pq for qs in law_qs.values() for pq in qs]))
    return _node(f"{html.escape(fam.name)}：法規架構 {_count(n)}", children)


# ---- 各科：主題圖 ----


def _topic_tree(fam: _Family, similar: SimilarIndex, laws: LawIndex, up: str) -> Optional[dict]:
    """科目 → 主題 → 重複考點（相似題組）、常考法條、近年題目。主題頁連結與 exam_reader 跨年度比較頁同序。"""
    topics = READER_TOPICS.get(fam.slug, [])
    if not topics:
        return None
    by_topic: Dict[str, List[Tuple[dict, dict]]] = defaultdict(list)
    topic_of: Dict[Tuple[str, str], str] = {}
    for p, q in fam.items:
        t = _topic_of(q, topics)
        by_topic[t].append((p, q))
        topic_of[(p["id"], qid(q))] = t
    names = [t[0] for t in topics if t[0] in by_topic] + [t for t in ("其他",) if t in by_topic]
    clusters: Dict[str, List[List[Tuple[dict, dict]]]] = defaultdict(list)
    for group in similar.clusters():
        p, q = group[0]
        clusters[topic_of[(p["id"], qid(q))]].append(group)
    children = []
    for i, topic in enumerate(names, 1):
        qs = _newest(by_topic[topic])
        kids = []
        groups = clusters.get(topic, [])[:TOPIC_CLUSTERS_MAX]
        if groups:
            g_nodes = []
            for g in groups:
                years = "・".join(str(y) for y in sorted({p["year"] for p, _ in g}))
                g_nodes.append(
                    _node(
                        f'{_snippet(g[0][1]["text"], 22)} <small class="lm-n">{years}</small>',
                        [_q_node(p, q, up) for p, q in g[:ARTICLE_QS_MAX]],
                    )
                )
            kids.append(_node(f"🔁 重複考點 {_count(len(groups), '組')}", g_nodes))
        ref_count: Counter = Counter(r for p, q in qs for r in fam.refs[(p["id"], qid(q))])
        top = [(r, n) for r, n in ref_count.most_common(TOPIC_LAWS_MAX) if n >= 2]
        if top:
            law_nodes = []
            for r, n in top:
                page = fam.law_page(r)
                label = html.escape(r)
                law_nodes.append(
                    _node(
                        (f'<a href="{up}{fam.slug}/{LAW_DIR}/{page}/">{label}</a>' if page else label) + f" {_count(n)}"
                    )
                )
            kids.append(_node(f"📜 常考法條 {_count(len(top), '條')}", law_nodes))
        by_year: Dict[int, List[Tuple[dict, dict]]] = defaultdict(list)
        for p, q in qs:
            by_year[p["year"]].append((p, q))
        y_nodes = [
            _node(f"{y} 年 {_count(len(by_year[y]))}", [_q_node(p, q, up) for p, q in by_year[y][:YEAR_QS_MAX]])
            for y in sorted(by_year, reverse=True)[:TOPIC_RECENT_YEARS]
        ]
        y_nodes.append(_node(f'<a href="{up}{fam.slug}/{TOPIC_DIR}/t{i}/">看歷屆全部 {len(qs)} 題 →</a>'))
        kids.append(_node("📅 近年題目", y_nodes))
        recent = _recent(qs, fam.latest)
        children.append(
            _node(
                f"<strong>{html.escape(topic)}</strong> {_count(len(qs))}"
                + (f'<span class="lm-hot" title="近 {RECENT_YEARS} 年">近{recent}</span>' if recent else ""),
                kids,
            )
        )
    return _node(f"{html.escape(fam.name)}：主題 {_count(len(fam.items))}", children)


# ---- 跨科目概念 ----


class _Concept:
    def __init__(self, cid: str, name: str, kind: str, ref: str = ""):
        self.cid, self.name, self.kind, self.ref = cid, name, kind, ref
        self.qs: Dict[str, List[Tuple[dict, dict]]] = defaultdict(list)  # 科目 slug → 題目

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.qs.values())

    def years(self) -> List[int]:
        return sorted({p["year"] for qs in self.qs.values() for p, _ in qs})


def _concepts(fams: List[_Family], laws: LawIndex) -> List[_Concept]:
    """關鍵詞概念與跨科法條概念；只留兩科以上都考過的。"""
    out: List[_Concept] = []
    patterns = [(i, name, re.compile(rx)) for i, (name, rx) in enumerate(CONCEPTS, 1)]
    kw = {i: _Concept(f"k{i}", name, "keyword") for i, name, _ in patterns}
    for fam in fams:
        for p, q in fam.items:
            stem = q["text"] + " " + " ".join(q.get("options", []))
            for i, _, rx in patterns:
                if rx.search(stem):
                    kw[i].qs[fam.slug].append((p, q))
    out += [c for c in kw.values() if len(c.qs) >= 2]
    refs: Dict[str, _Concept] = {}
    for fam in fams:
        for ref, qs in fam.by_ref.items():
            if ref not in refs:
                refs[ref] = _Concept("law-" + _law_slug(ref, laws.timeline), ref, "law", ref)
            refs[ref].qs[fam.slug] += qs
    out += [c for c in refs.values() if len(c.qs) >= 2 and c.total >= LAW_CONCEPT_MIN]
    for c in out:
        for slug in c.qs:
            c.qs[slug] = _newest(_uniq(c.qs[slug]))
    return sorted(out, key=lambda c: (-len(c.qs), -c.total, c.name))


def _related(
    c: _Concept, concepts: List[_Concept], fams: Dict[str, _Family]
) -> Tuple[List[Tuple[_Concept, int]], List[Tuple[str, int]]]:
    """(相關概念, 相關法條)：同一題也命中的其他概念、這些題目引用的法條，依共同題數排序。"""
    mine = {(p["id"], qid(q)) for qs in c.qs.values() for p, q in qs}
    shared = []
    for o in concepts:
        if o is c:
            continue
        n = sum((p["id"], qid(q)) in mine for qs in o.qs.values() for p, q in qs)
        if n >= 2:
            shared.append((o, n))
    shared.sort(key=lambda t: (-t[1], t[0].name))
    refs: Counter = Counter()
    for slug, qs in c.qs.items():
        for p, q in qs:
            refs.update(r for r in fams[slug].refs[(p["id"], qid(q))] if r != c.ref)
    return shared[:CONCEPT_RELATED_MAX], [(r, n) for r, n in refs.most_common(CONCEPT_RELATED_MAX) if n >= 2]


def _law_href(ref: str, fams: Dict[str, _Family], up: str) -> Optional[str]:
    """法條比較頁網址：取這一條題數最多、有比較頁的科目。"""
    best = max((f for f in fams.values() if f.law_page(ref)), key=lambda f: len(f.by_ref[ref]), default=None)
    return f"{up}{best.slug}/{LAW_DIR}/{best.law_page(ref)}/" if best else None


def _concept_tree(
    c: _Concept, fams: Dict[str, _Family], related: List[Tuple[_Concept, int]], refs: List[Tuple[str, int]], up: str
) -> dict:
    """概念 → 科目 → 年度 → 題目，另掛相關概念與相關法條。up 為到 exam-reader/ 的相對網址。"""
    children = []
    for slug in sorted(c.qs, key=lambda s: -len(c.qs[s])):
        qs = c.qs[slug]
        by_year: Dict[int, List[Tuple[dict, dict]]] = defaultdict(list)
        for p, q in qs[:CONCEPT_FAMILY_QS_MAX]:
            by_year[p["year"]].append((p, q))
        y_nodes = [
            _node(f"{y} 年 {_count(len(by_year[y]))}", [_q_node(p, q, up, True) for p, q in by_year[y]])
            for y in sorted(by_year, reverse=True)
        ]
        if len(qs) > CONCEPT_FAMILY_QS_MAX:
            y_nodes.append(_node(f"…另 {len(qs) - CONCEPT_FAMILY_QS_MAX} 題見頁面下方清單"))
        years = sorted({p["year"] for p, _ in qs})
        span = f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0])
        children.append(
            _node(
                f'<strong>{html.escape(fams[slug].name)}</strong> {_count(len(qs))} <small class="lm-n">{span}</small>',
                y_nodes,
            )
        )
    if related:
        children.append(
            _node(
                f"🔗 相關概念 {_count(len(related), '個')}",
                [
                    _node(
                        f'<a href="{up}{MINDMAP_DIR}/{CONCEPT_DIR}/{o.cid}/">{html.escape(o.name)}</a>'
                        f' <small class="lm-n">同題 {n}</small>'
                    )
                    for o, n in related
                ],
            )
        )
    if refs:
        nodes = []
        for r, n in refs:
            href = _law_href(r, fams, up)
            label = html.escape(r)
            nodes.append(_node((f'<a href="{href}">{label}</a>' if href else label) + f" {_count(n)}"))
        children.append(_node(f"📜 相關法條 {_count(len(refs), '條')}", nodes))
    return _node(f"<strong>{html.escape(c.name)}</strong> {_count(c.total)}", children)


# ---- 頁面 ----


def _box(src: str, level: int, label: str) -> str:
    """心智圖容器；study_tools.js 讀 data-src（相對頁面網址）繪製，data-level 為預設顯示幾層（含根節點）。"""
    return (
        f'<div class="lm-mindmap" data-src="{src}" data-level="{level}" role="figure" '
        f'aria-label="{html.escape(label)}"><p class="lm-loading">心智圖載入中…（需要 JavaScript）</p></div>'
    )


def _dump(path: Path, tree: dict) -> None:
    path.write_text(json.dumps(tree, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


HOWTO = (
    '!!! tip "怎麼用"\n'
    "    點圓點展開或收合分支，滾輪或雙指縮放、拖曳移動；點文字連到法條比較頁或原題。"
    "題目前的顏色是你的熟練度標記（紅＝不熟、黃＝待複習、綠＝熟練），在題目卡按標記後回來就會更新。\n"
)


def _family_page(out: Path, fam: _Family, has_law: bool, has_topic: bool, concepts: List[_Concept]) -> None:
    lines = [
        HIDE_NAV,
        f"# {fam.name}：考點心智圖",
        "",
        f'<p class="qb-meta"><a href="../">回心智圖總覽</a><a href="../../{fam.slug}/">回{fam.name}題目總覽</a></p>',
        "",
        HOWTO,
    ]
    if has_law:
        lines += [
            "## 法規架構",
            "",
            "依法規本身的**編、章、節**排列，只列考過的條文；每條標出歷屆題數與近 "
            f"{RECENT_YEARS} 年題數（「近N」），展開可看題目。沒有引用到條文的題目（多為理論或政策題）在下方主題圖。",
            "",
            _box(f"../{fam.slug}-law.json", 2, f"{fam.name}法規架構心智圖"),
            "",
        ]
    if has_topic:
        lines += [
            "## 主題",
            "",
            "依題目關鍵詞歸類的主題，每個主題下有**重複考點**（不同年度換個問法再考的題組）、"
            "**常考法條**與**近年題目**。",
            "",
            _box(f"../{fam.slug}-topic.json", 3, f"{fam.name}主題心智圖"),
            "",
        ]
    mine = [c for c in concepts if fam.slug in c.qs][:20]
    if mine:
        lines += [
            "## 這一科也出現在其他科目的概念",
            "",
            "同一個概念在其他科目怎麼考，點進去看跨科目的心智圖：",
            "",
            " ".join(
                f'<a class="pb-count" href="../{CONCEPT_DIR}/{c.cid}/">{html.escape(c.name)}'
                f"<small> {len(c.qs)} 科</small></a>"
                for c in mine
            ),
            "",
        ]
    (out / f"{fam.slug}.md").write_text("\n".join(lines), encoding="utf-8")


def _concept_page(out: Path, c: _Concept, fams: Dict[str, _Family], related: List[Tuple[_Concept, int]]) -> None:
    years = c.years()
    span = f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0])
    what = "這一條" if c.kind == "law" else "這個概念"
    lines = [
        HIDE_NAV,
        f"# {c.name}：跨科目考法",
        "",
        f'<p class="qb-meta"><span class="pb-count">{len(c.qs)} 科</span><span class="pb-count">{c.total} 題</span>'
        f'<span class="pb-count">{span} 年</span><a href="../../">回心智圖總覽</a></p>',
        "",
        f"{what}在 {len(c.qs)} 個科目都考過。同一件事在不同科目的問法、重點常不一樣，"
        "放在一起看可以一次讀通：先看各科出題的角度，再看相關概念與法條把知識串起來。",
        "",
        _box(f"../{c.cid}.json", 2, f"{c.name}跨科目心智圖"),
        "",
    ]
    if c.kind == "law":
        href = _law_href(c.ref, fams, "../../../")
        if href:
            lines += [f"[看條文與歷屆題目：{c.name}]({href}){{.md-button}}", ""]
    if related:
        lines += ["**相關概念**：" + "・".join(f"[{o.name}](../{o.cid}/)" for o, _ in related), ""]
    lines += ["## 各科題目", ""]
    for slug in sorted(c.qs, key=lambda s: -len(c.qs[s])):
        lines += [f"### {fams[slug].name}（{len(c.qs[slug])} 題）", ""]
        for p, q in c.qs[slug]:
            kind = "申論" if q["kind"] == "essay" else "測驗"
            lines.append(
                f"- [{p['year']} {_exam_short(p['exam'])}《{p['subject']}》{kind}第 {q['no']} 題]"
                f"(../../../{slug}/{p['id']}/#{qid(q)}) {_snippet(q['text'], 40, markdown=True)}"
            )
        lines.append("")
    (out / f"{c.cid}.md").write_text("\n".join(lines), encoding="utf-8")


def _index_page(out: Path, fams: List[_Family], pages: List[_Family], concepts: List[_Concept]) -> None:
    kw = [c for c in concepts if c.kind == "keyword"]
    law = [c for c in concepts if c.kind == "law"]
    lines = [
        "---\nhide:\n  - navigation\n  - toc\n---\n",
        "# 考點心智圖",
        "",
        "把歷屆考題掛在**法規的編章節**與**主題**上，一張圖看出一科的骨架、哪裡常考、哪些題目換個問法又考一次；"
        "**跨科目概念**則把同一個概念在不同科目、不同年度的考法串在一起。",
        "",
        HOWTO,
        "## 各科心智圖",
        "",
        "| 科目 | 題數 | 對到法條的題目 | 跨科概念 |",
        "|---|---:|---:|---:|",
    ]
    for fam in pages:
        n_law = len(_uniq([pq for qs in fam.by_ref.values() for pq in qs]))
        n_c = sum(fam.slug in c.qs for c in concepts)
        lines.append(f"| [{fam.name}]({fam.slug}.md) | {len(fam.items)} | {n_law} | {n_c} |")
    lines += [
        "",
        "## 跨科目概念",
        "",
        f"{len(kw)} 個概念、{len(law)} 條法條在兩個以上科目都考過。"
        "圖中每個概念展開是各科題數，點名稱看該概念的跨科目心智圖。",
        "",
        _box("concepts.json", 3, "跨科目概念心智圖"),
        "",
        "| 概念 | 科目數 | 題數 | 年度 | 各科題數 |",
        "|---|---:|---:|---|---|",
    ]
    names = {f.slug: f.name for f in fams}
    for c in kw + law:
        years = c.years()
        per = "・".join(f"{names[s]} {len(c.qs[s])}" for s in sorted(c.qs, key=lambda s: -len(c.qs[s])))
        lines.append(
            f"| [{c.name}]({CONCEPT_DIR}/{c.cid}.md) | {len(c.qs)} | {c.total} | {years[0]}–{years[-1]} | {per} |"
        )
    (out / "index.md").write_text("\n".join(lines), encoding="utf-8")


def _overview_tree(kw: List[_Concept], law: List[_Concept], names: Dict[str, str]) -> dict:
    def item(c: _Concept) -> dict:
        per = [
            _node(f"{html.escape(names[s])} {_count(len(c.qs[s]))}") for s in sorted(c.qs, key=lambda s: -len(c.qs[s]))
        ]
        return _node(
            f'<a href="{CONCEPT_DIR}/{c.cid}/">{html.escape(c.name)}</a> {_count(c.total)}'
            f' <small class="lm-n">{len(c.qs)} 科</small>',
            per,
        )

    by_n: Dict[int, List[_Concept]] = defaultdict(list)
    for c in kw:
        by_n[len(c.qs)].append(c)
    children = [
        _node(f"<strong>{n} 科都考</strong> {_count(len(by_n[n]), '個')}", [item(c) for c in by_n[n]])
        for n in sorted(by_n, reverse=True)
    ]
    if law:
        law_node = _node(f"<strong>跨科法條</strong> {_count(len(law), '條')}", [item(c) for c in law])
        law_node["payload"] = {"fold": 1}  # 兩百多條，預設收合，點開才展開
        children.append(law_node)
    return _node("跨科目概念", children)


def write_pages(
    docs_dir: Path,
    data_dir: Path = EXAM_READER_DATA_DIR,
    laws: Optional[LawIndex] = None,
    articles_file: Path = LAW_ARTICLES_FILE,
) -> List[Tuple[str, str]]:
    """產生 docs/exam-reader/mindmap/，回傳 nav 用的 [(標題, 路徑)]；沒有考古題資料時回空。"""
    readers = available(data_dir)
    if not readers:
        return []
    laws = laws or LawIndex()
    chapters = {}
    if articles_file.exists():
        chapters = json.loads(articles_file.read_text(encoding="utf-8")).get("chapters", {})
    outline = _outline(chapters)
    fams: List[_Family] = []
    for _, slug, name in readers:
        fam = _Family(slug, name, json.loads(data_file(slug, data_dir).read_text(encoding="utf-8")), laws)
        if fam.items:
            fam.set_law_pages(laws)
            fams.append(fam)
    if not fams:
        return []
    by_slug = {f.slug: f for f in fams}
    out = docs_dir / READER_ROOT / MINDMAP_DIR
    (out / CONCEPT_DIR).mkdir(parents=True, exist_ok=True)
    concepts = _concepts(fams, laws)
    pages = []
    for fam in fams:
        up = "../../"  # exam-reader/mindmap/<slug>/ → exam-reader/
        has_law = bool(fam.by_ref)
        if has_law:
            _dump(out / f"{fam.slug}-law.json", _law_tree(fam, laws, outline, up))
        topic = _topic_tree(fam, SimilarIndex(fam.papers), laws, up)
        if topic:
            _dump(out / f"{fam.slug}-topic.json", topic)
        if has_law or topic:
            _family_page(out, fam, has_law, bool(topic), concepts)
            pages.append(fam)
    for c in concepts:
        related, refs = _related(c, concepts, by_slug)
        _dump(out / CONCEPT_DIR / f"{c.cid}.json", _concept_tree(c, by_slug, related, refs, "../../../"))
        _concept_page(out / CONCEPT_DIR, c, by_slug, related)
    names = {f.slug: f.name for f in fams}
    _dump(
        out / "concepts.json",
        _overview_tree([c for c in concepts if c.kind == "keyword"], [c for c in concepts if c.kind == "law"], names),
    )
    _index_page(out, fams, pages, concepts)
    _link_family_indexes(docs_dir / READER_ROOT, pages)
    print(f"  考點心智圖：{len(pages)} 科、{len(concepts)} 個跨科目概念")
    return [("考點心智圖", f"{READER_ROOT}/{MINDMAP_DIR}/index.md")]


MINDMAP_LINK_ANCHOR = "**[跨年度比較]"  # 各科題目總覽頁（exam_reader 產生）在這一行前插入心智圖入口


def _link_family_indexes(root: Path, pages: List[_Family]) -> None:
    """在各科題目總覽頁加上心智圖入口；找不到插入點就不加（總覽頁改版時不會壞頁）。"""
    for fam in pages:
        path = root / fam.slug / "index.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if MINDMAP_LINK_ANCHOR not in text:
            continue
        link = (
            f"**[考點心智圖](../{MINDMAP_DIR}/{fam.slug}.md)**：依法規編章節與主題畫成心智圖，"
            "一眼看出哪裡常考、哪些題目換個問法又考一次。\n\n"
        )
        path.write_text(text.replace(MINDMAP_LINK_ANCHOR, link + MINDMAP_LINK_ANCHOR, 1), encoding="utf-8")
