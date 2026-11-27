"""把逐題讀的考古題匯出成 Obsidian vault：每題一則筆記，與法條、主題、相似題互相連結。

管線位置：讀 `data/exam_bank/<slug>.json`（exam_reader.build 產出）、`data/law_articles.json`，
以及 site_generator 已產生的 blog 文章（比對老師擬答與相關文章），寫到使用者指定的 vault 目錄。
vault 不在 repo 裡：裡面會有使用者自己的筆記，不進版控。

重新匯出時保留使用者的內容：每則筆記 `USER_MARK` 以下的文字、frontmatter 的 `狀態` 欄位原樣保留；
其餘部分（題目、詳解、連結）由資料重產。只覆寫自己產生的檔案，不刪除任何檔案。
"""

import json
import re
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from landnote.config import EXAM_READER_DATA_DIR, SITE_URL
from landnote.processors.exam_bank import REPO_BLOB
from landnote.processors.exam_reader import (
    READER_TOPICS,
    ArticleIndex,
    LawIndex,
    SimilarIndex,
    _amended_after,
    _exam_short,
    _topic_of,
    available,
    data_file,
    qid,
)

VAULT_NAME = "Landnote考古題"  # zip 內的最上層資料夾，也是本機預設輸出目錄名

USER_MARK = "%% ↓ 我的筆記：重新匯出時，這一行以下的內容會保留 %%"
STATUS_KEY = "狀態"
STATUS_DEFAULT = "未讀"
STATUS_CHOICES = "未讀 / 不熟 / 待複習 / 熟練"
INVALID_NAME = re.compile(r'[\\/:*?"<>|#^\[\]]')


def _name(text: str) -> str:
    """筆記檔名：去掉 Obsidian 連結與檔案系統不允許的字元。"""
    return re.sub(r"\s+", " ", INVALID_NAME.sub(" ", text)).strip()


def _esc(text: str) -> str:
    """題目原文放進 Obsidian：避免被當成連結、標籤、註解或區塊參照。"""
    text = re.sub(r"([\[\]*_`|\\#^=%$~])", r"\\\1", text)
    return re.sub(r"^(\d+)([.)])", r"\1\\\2", text)  # 避免「1.」變成清單


def _quote(lines: List[str]) -> List[str]:
    """放進 callout：每行加「> 」。"""
    return [f"> {ln}" if ln else ">" for ln in lines]


def _yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _kind_label(q: dict) -> str:
    return "申論" if q["kind"] == "essay" else "測驗"


class Vault:
    """產生整個 vault；`write()` 回傳各類筆記數量。"""

    def __init__(self, out: Path, posts_dirs: List[Path], data_dir: Path = EXAM_READER_DATA_DIR):
        self.out = out
        self.posts_dirs = posts_dirs
        self.readers = available(data_dir)
        self.data_dir = data_dir
        self.laws = LawIndex()
        self.index = ArticleIndex(posts_dirs)
        self.urls = self._post_urls()
        # (paper id, qid) → 題目筆記名稱；跨科考卷出現在多個家族時只寫一次
        self.q_names: Dict[Tuple[str, str], str] = {}
        self.paper_names: Dict[str, str] = {}
        self.written_papers: set = set()
        self.counts: Dict[str, int] = defaultdict(int)

    # ---- 共用 ----

    def _post_urls(self) -> Dict[str, str]:
        """文章原始檔路徑（相對 docs/）→ 網站網址；網址格式同 mkdocs.yml 的 post_url_format '{date}/{slug}'。"""
        urls = {}
        for posts in self.posts_dirs:
            blog = posts.parent.name
            for f in posts.glob("*.md"):
                head = f.read_text(encoding="utf-8")[:600]
                m_date = re.search(r"^date:\s*(\d{4})-(\d{2})-(\d{2})", head, re.M)
                m_slug = re.search(r"^slug:\s*['\"]?([^'\"\n]+)", head, re.M)
                if m_date and m_slug:
                    y, mo, d = m_date.groups()
                    urls[f"{blog}/posts/{f.name}"] = f"{SITE_URL}{blog}/{y}/{mo}/{d}/{m_slug.group(1).strip()}/"
        return urls

    def _write(self, rel: str, body: List[str], props: Dict[str, object]) -> None:
        """寫一則筆記；保留既有檔案的「狀態」欄位與 USER_MARK 以下的內容。"""
        path = self.out / rel
        user = ""
        status = props.get(STATUS_KEY)
        if path.exists():
            old = path.read_text(encoding="utf-8")
            if USER_MARK in old:
                user = old.split(USER_MARK, 1)[1].lstrip("\n")
            m = re.search(rf"^{STATUS_KEY}:\s*(.+)$", old, re.M)
            if m and status is not None:
                status = m.group(1).strip()
        if status is not None:
            props[STATUS_KEY] = status
        fm = ["---"]
        for key, value in props.items():
            if isinstance(value, list):
                fm.append(f"{key}:" if value else f"{key}: []")
                fm += [f"  - {_yaml_str(str(v))}" for v in value]
            elif isinstance(value, int):
                fm.append(f"{key}: {value}")
            else:
                fm.append(f"{key}: {_yaml_str(str(value)) if key != STATUS_KEY else value}")
        fm.append("---")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(fm + [""] + body + ["", USER_MARK, ""]) + user
        path.write_text(text, encoding="utf-8")

    # ---- 命名 ----

    def _assign_names(self, families: List[Tuple[str, str, List[dict]]]) -> None:
        """先替所有考卷與題目決定唯一的筆記名稱，寫內容時才能互相連結。"""
        used: Dict[str, int] = defaultdict(int)
        for _, _, papers in families:
            for p in papers:
                if p["id"] in self.paper_names:
                    continue
                base = _name(f"{p['year']} {_exam_short(p['exam'])} {p['subject']}")
                used[base] += 1
                self.paper_names[p["id"]] = base if used[base] == 1 else f"{base} ({p['id']})"
        for _, _, papers in families:
            for p in papers:
                for q in p["questions"]:
                    key = (p["id"], qid(q))
                    if key not in self.q_names:
                        self.q_names[key] = f"{self.paper_names[p['id']]} {_kind_label(q)}{q['no']}"

    def _law_name(self, ref: str) -> str:
        return _name(ref)

    def _topic_name(self, name: str, topic: str) -> str:
        return _name(f"{name}－{topic}")

    # ---- 產生 ----

    def write(self) -> Dict[str, int]:
        families = []
        for _, slug, name in self.readers:
            papers = json.loads(data_file(slug, self.data_dir).read_text(encoding="utf-8"))
            families.append((slug, name, [p for p in papers if p["questions"]]))
        self._assign_names(families)

        by_law: Dict[str, List[Tuple[dict, dict, str]]] = defaultdict(list)
        written_q: set = set()
        family_summary = []
        for slug, name, papers in families:
            similar = SimilarIndex(papers)
            topics = READER_TOPICS.get(slug, [])
            by_topic: Dict[str, List[Tuple[dict, dict]]] = defaultdict(list)
            for p in papers:
                for q in p["questions"]:
                    key = (p["id"], qid(q))
                    hits = self.laws.refs(q)
                    topic = _topic_of(q, topics) if topics else ""
                    if topic:
                        by_topic[topic].append((p, q))
                    if key in written_q:
                        continue
                    written_q.add(key)
                    for ref, source in hits:
                        by_law[ref].append((p, q, source))
                    self._question_note(name, p, q, hits, topic, similar.of(p, q))
                self._paper_note(name, p)
            for topic, qs in by_topic.items():
                self._topic_note(name, topic, qs)
            self._family_note(name, papers, by_topic)
            family_summary.append((name, papers, by_topic))
        for ref, qs in by_law.items():
            self._law_note(ref, qs)
        self._home_note(family_summary, by_law)
        return dict(self.counts)

    def _question_note(
        self, name: str, p: dict, q: dict, hits: List[Tuple[str, str]], topic: str, similar: List[Tuple[dict, dict]]
    ) -> None:
        note = self.q_names[(p["id"], qid(q))]
        props: Dict[str, object] = {
            "科目": name,
            "年度": p["year"],
            "考試": p["exam"],
            "考卷科目": p["subject"],
            "題型": _kind_label(q),
            "題號": q["no"],
        }
        if q["score"]:
            props["配分"] = q["score"]
        if q["kind"] == "choice" and q.get("key"):
            props["答案"] = q["key"]
        props["考卷"] = f"[[{self.paper_names[p['id']]}]]"
        if topic:
            props["主題"] = f"[[{self._topic_name(name, topic)}]]"
        props["法條"] = [f"[[{self._law_name(ref)}]]" for ref, _ in hits]
        props["tags"] = [f"考古題/{_name(name).replace(' ', '')}", _kind_label(q)]
        props[STATUS_KEY] = STATUS_DEFAULT

        body = [f"# {p['year']} 年 {p['exam']}《{p['subject']}》第 {q['no']} 題", ""]
        body += _quote(
            [
                "[!question] 題目" + (f"（{q['score']} 分）" if q["score"] else ""),
                *[ln for par in q["text"].split("\n") for ln in (_esc(par),)],
            ]
        )
        if q.get("options"):
            body += _quote([""] + [_esc(o) + "  " for o in q["options"]])
        body.append("")
        if q["kind"] == "choice" and q.get("key"):
            body += ["> [!success]- 答案", f"> **{q['key']}**", ""]
        elif q.get("answer"):
            body += _quote(
                ["[!success]- 參考解答（補習班詳解，先自己寫再打開）"]
                + [ln for a in q["answer"] for ln in (_esc(a), "")][:-1]
            ) + [""]
        doc = self.index.teacher_answer(q["text"])
        if doc:
            who = f"｜{doc['author']}" if doc["author"] else ""
            img_base = f"{SITE_URL}{doc['path'].rsplit('/', 1)[0]}/images/"
            answer = doc["answer_md"].replace("](images/", f"]({img_base}")
            body += _quote(
                [f"[!tip]- 老師擬答{who}（先自己寫再打開）"]
                + answer.splitlines()
                + ["", f"出處：[{doc['title']}]({self.urls.get(doc['path'], SITE_URL)})"]
            ) + [""]
        if hits:
            body += ["## 考點法條", ""]
            for ref, source in hits:
                tip = "（依條文內容自動比對，可能不準）" if source == LawIndex.MATCH else f"（{source}引用）"
                body.append(f"- [[{self._law_name(ref)}]]{tip}")
            body.append("")
        if similar:
            body += ["## 歷屆相似題", ""]
            body += [
                f"- [[{self.q_names[(sp['id'], qid(sq))]}]]"
                for sp, sq in similar
                if (sp["id"], qid(sq)) in self.q_names
            ]
            body.append("")
        related = [
            r
            for r in self.index.related(q["text"] + "".join(q.get("options", [])), [ref for ref, _ in hits])
            if not doc or r["file"] != doc["file"]
        ]
        if related:
            body += ["## 延伸閱讀：老師相關文章", ""]
            for r in related:
                who = f"｜{r['author']}" if r["author"] else ""
                body.append(f"- [{_esc(r['title'])}{who}]({self.urls.get(r['path'], SITE_URL)})")
            body.append("")
        body.append(f"原卷 PDF：[GitHub]({REPO_BLOB}{quote(p['pdf'])})")
        self._write(f"題目/{_name(name)}/{note}.md", body, props)
        self.counts["題目"] += 1

    def _paper_note(self, name: str, p: dict) -> None:
        note = self.paper_names[p["id"]]
        if p["id"] in self.written_papers:  # 跨科考卷只寫在第一個家族
            return
        self.written_papers.add(p["id"])
        rel = f"考卷/{_name(name)}/{note}.md"
        props: Dict[str, object] = {
            "科目": name,
            "年度": p["year"],
            "考試": p["exam"],
            "考卷科目": p["subject"],
            "tags": ["考卷"],
        }
        body = [
            f"# {p['year']} 年 {p['exam']}《{p['subject']}》",
            "",
            f"原卷 PDF：[GitHub]({REPO_BLOB}{quote(p['pdf'])})" + ("；附補習班詳解" if p["has_answer"] else ""),
            "",
        ]
        for q in p["questions"]:
            body += [
                f"- [[{self.q_names[(p['id'], qid(q))]}|第 {q['no']} 題（{_kind_label(q)}）]]"
                + f"：{_esc(q['text'].splitlines()[0][:40])}…"
            ]
        body += ["", "> [!tip] 想整份連續讀，把上面的連結改成 `![[...]]` 嵌入，或用 Obsidian 的「開啟所有連結」。"]
        self._write(rel, body, props)
        self.counts["考卷"] += 1

    def _law_note(self, ref: str, qs: List[Tuple[dict, dict, str]]) -> None:
        law = re.sub(r"第\d+條.*$", "", ref)
        amended = self.laws.timeline.amended(ref)
        url = self.laws.timeline.url(ref)
        props: Dict[str, object] = {"法規": law, "題數": len(qs), "tags": ["法條"]}
        if amended:
            props["最近修正"] = amended[0]
        props[STATUS_KEY] = STATUS_DEFAULT
        body = [f"# {ref}", ""]
        text = self.laws.text.get(ref)
        if text:
            body += _quote(
                ["[!quote] 現行條文"]
                + [ln for par in text.split("\n") if par.strip() for ln in (_esc(par.strip()), "")][:-1]
            )
            if url:
                body += [">", f"> [全國法規資料庫]({url})"]
            body.append("")
        else:
            body += ["> [!warning] 現行法規查無此條", "> 可能已刪除或條號變動，題目請以出題當時的法規理解。", ""]
        if amended:
            body += [
                f"條文修正（含法規修正全文）：{'、'.join(amended[:8])}"
                + (f" 等 {len(amended)} 次" if len(amended) > 8 else ""),
                "",
            ]
        body += [f"## 歷屆考題（{len(qs)} 題）", ""]
        for p, q, source in sorted(qs, key=lambda t: (-t[0]["year"], t[0]["exam"], t[1]["no"])):
            flags = []
            if source == LawIndex.MATCH:
                flags.append("自動比對")
            after = _amended_after(amended, p["year"])
            if after:
                flags.append(f"⚠ 出題後修正 {after}")
            body.append(f"- [[{self.q_names[(p['id'], qid(q))]}]]" + (f"（{'、'.join(flags)}）" if flags else ""))
        self._write(f"法條/{_name(law)}/{self._law_name(ref)}.md", body, props)
        self.counts["法條"] += 1

    def _topic_note(self, name: str, topic: str, qs: List[Tuple[dict, dict]]) -> None:
        years = sorted({p["year"] for p, _ in qs})
        props: Dict[str, object] = {"科目": name, "題數": len(qs), "tags": ["主題"]}
        body = [f"# {name}：{topic}", "", f"民國 {years[0]}–{years[-1]} 年共 {len(qs)} 題，新年度在前。", ""]
        by_year: Dict[int, List[Tuple[dict, dict]]] = defaultdict(list)
        for p, q in qs:
            by_year[p["year"]].append((p, q))
        for y in sorted(by_year, reverse=True):
            body += [f"## {y} 年", ""]
            body += [
                f"- [[{self.q_names[(p['id'], qid(q))]}]]：{_esc(q['text'].splitlines()[0][:50])}…"
                for p, q in sorted(by_year[y], key=lambda t: (t[0]["exam"], t[1]["no"]))
            ]
            body.append("")
        self._write(f"主題/{_name(name)}/{self._topic_name(name, topic)}.md", body, props)
        self.counts["主題"] += 1

    def _family_note(self, name: str, papers: List[dict], by_topic: Dict[str, list]) -> None:
        n_q = sum(len(p["questions"]) for p in papers)
        body = [f"# {name}", "", f"{len(papers)} 份考卷、{n_q} 題。", ""]
        if by_topic:
            body += ["## 主題", ""]
            body += [
                f"- [[{self._topic_name(name, t)}]]（{len(qs)} 題）"
                for t, qs in sorted(by_topic.items(), key=lambda kv: -len(kv[1]))
            ]
            body.append("")
        body += ["## 歷屆考卷", ""]
        body += [f"- [[{self.paper_names[p['id']]}]]" for p in sorted(papers, key=lambda p: (-p["year"], p["exam"]))]
        self._write(f"科目/{_name(name)}.md", body, {"tags": ["科目"]})

    def _home_note(self, families: list, by_law: Dict[str, list]) -> None:
        n_q = self.counts["題目"]
        body = [
            "# Landnote 考古題庫",
            "",
            f"共 {n_q} 題、{self.counts['法條']} 條法條、{self.counts['主題']} 個主題，資料來自"
            f" [Landnote 數位圖書館]({SITE_URL})。",
            "",
            "## 怎麼用",
            "",
            f"1. 每題筆記的 `{STATUS_KEY}` 欄位改成 {STATUS_CHOICES}，下方查詢會自動整理出待複習清單。",
            "2. 心得、易錯點寫在每則筆記最下面的「我的筆記」標記線以下，用 `obsidian` 指令重新匯出時會保留。"
            "從網站下載的 zip 版沒有這個保護：解壓新版覆蓋會清掉題目筆記裡的狀態與筆記，"
            "長篇心得建議另開資料夾寫，再用 [[連結]] 指向題目。",
            "3. 從題目點進 **法條** 筆記，可看同一條歷屆怎麼考；法條筆記的反向連結會列出所有引用它的題目與你的筆記。",
            "4. 解答都收合著，先自己寫再打開。",
            "",
            "## 科目",
            "",
        ]
        body += [
            f"- [[{_name(name)}]]：{len(papers)} 份考卷、{sum(len(p['questions']) for p in papers)} 題"
            for name, papers, _ in families
        ]
        top = sorted(by_law, key=lambda r: (-len(by_law[r]), r))[:30]
        body += ["", "## 最常考的 30 條法條", ""]
        body += [f"- [[{self._law_name(r)}]]（{len(by_law[r])} 題）" for r in top]
        body += [
            "",
            "## 複習清單（需安裝 Dataview 外掛）",
            "",
            "```dataview",
            f'TABLE 科目, 年度, 題型, 法條 FROM "題目" WHERE {STATUS_KEY} = "不熟" OR {STATUS_KEY} = "待複習"',
            "SORT 科目, 年度 DESC",
            "```",
            "",
            "```dataview",
            f'TABLE length(rows) AS 題數 FROM "題目" WHERE {STATUS_KEY} != "未讀" GROUP BY {STATUS_KEY}',
            "```",
        ]
        self._write("首頁.md", body, {"tags": ["首頁"]})


def export(out: Path, posts_dirs: List[Path], data_dir: Path = EXAM_READER_DATA_DIR) -> Optional[Dict[str, int]]:
    """匯出 vault；沒有逐題讀資料時回 None。"""
    vault = Vault(out, posts_dirs, data_dir)
    if not vault.readers:
        return None
    return vault.write()


def export_zip(
    zip_path: Path, posts_dirs: List[Path], data_dir: Path = EXAM_READER_DATA_DIR
) -> Optional[Dict[str, int]]:
    """匯出到暫存目錄再壓成 zip（最上層資料夾為 VAULT_NAME），供網站下載；沒有資料時回 None。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / VAULT_NAME
        counts = export(root, posts_dirs, data_dir)
        if counts is None:
            return None
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:  # 非 ASCII 檔名自動標 UTF-8
            for f in sorted(root.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(tmp).as_posix())
        return counts
