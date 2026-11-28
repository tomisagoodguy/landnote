"""我的法條筆記：data/my_notes/notes.json（手工整理的地政士、經紀人重點）→ notes/ 各法規頁，並掛到逐題讀的法條頁。

筆記分兩種：
- article：條號＋重要度＋口訣（memo），並存整理當時抄的條文（text）。每次產生網站都跟現行條文比對，
  不同就標「條文已修正」並以現行條文為主、原整理條文收合。
- topic：主題重點（body 是 Markdown），refs 是內文引用的法條，exams 是註記的歷屆考題出處。
  內容無法自動比對，引用條文在整理後（NOTES_AS_OF）修正過的會標出來。

必須在 exam_reader.write_pages 之後執行：法條頁的 MARK 由這裡換成「我的筆記」。
"""

import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from landnote.config import LAW_ARTICLES_FILE, LOGS_DIR, MY_NOTES_DIR
from landnote.processors.law_timeline import LawTimeline, _split_ref
from landnote.utils.logger import Logger

logger = Logger.setup_logger("my_notes", LOGS_DIR)

NOTES_ROOT = "notes"
NOTES_FILE = MY_NOTES_DIR / "notes.json"
MARK = "<!-- my-notes -->"  # exam_reader._write_law_page 留的位置
NOTES_AS_OF = "2021-01-01"  # 原檔引用的考題到 109 年，之後的修正視為整理後才改
HIDE_NAV = "---\nhide:\n  - navigation\n---\n"


def _norm(s: str) -> str:
    return re.sub(r"[^一-鿿A-Za-z0-9]", "", s)


def _html_safe(s: str) -> str:
    """筆記內文保留 Markdown，只跳脫會被當成 HTML 的角括號（表格換行的 <br> 除外）。"""
    return re.sub(r"<(?!br>)", "&lt;", s.replace("&", "&amp;"))


def _ref_name(law: str, no: str) -> str:
    main, _, sub = no.partition("-")
    return f"{law}第{main}條" + (f"之{sub}" if sub else "")


def _slug(law: str, timeline: LawTimeline) -> str:
    pcode = timeline.laws.get(law, {}).get("pcode")
    return pcode or "law-" + hashlib.md5(law.encode("utf-8")).hexdigest()[:8]


def article_status(old: List[str], current: Optional[str]) -> str:
    """same／changed／missing：原整理條文跟現行條文比，允許只抄其中幾項。"""
    if current is None:
        return "missing"
    # 逐段嚴格比對（只忽略標點空白）：「百分之二之罰鍰」改成「百分之二以下之罰鍰」這種一兩字的修正正是考點
    c = _norm(current)
    return "same" if all(_norm(ln) in c for ln in old) else "changed"


def _law_pages(docs_dir: Path) -> Dict[str, List[Tuple[str, Path]]]:
    """逐題讀各科的法條頁：法條 → [(科目名, 檔案)]，從頁面標題與第一個 pb-count 讀回來。"""
    out: Dict[str, List[Tuple[str, Path]]] = defaultdict(list)
    for path in sorted((docs_dir / "exam-reader").glob("*/laws/*.md")):
        if path.name == "index.md":
            continue
        text = path.read_text(encoding="utf-8")
        title = re.search(r"^# (.+)$", text, re.M)
        fam = re.search(r'<span class="pb-count">([^<]+)</span>', text)
        if title and fam:
            out[title.group(1).strip()].append((fam.group(1), path))
    return out


def _load() -> List[dict]:
    if not NOTES_FILE.exists():
        return []
    return json.loads(NOTES_FILE.read_text(encoding="utf-8"))["notes"]


def write_pages(docs_dir: Path) -> List[Tuple[str, str]]:
    """寫 notes/ 並把筆記掛到法條頁；回傳 nav [(標題, 路徑)]，沒有筆記檔時回空。"""
    notes = _load()
    if not notes:
        for path in (docs_dir / "exam-reader").glob("*/laws/*.md"):
            text = path.read_text(encoding="utf-8")
            if MARK in text:
                path.write_text(text.replace(MARK, ""), encoding="utf-8")
        return []
    timeline = LawTimeline()
    current: Dict[str, str] = {}
    if LAW_ARTICLES_FILE.exists():
        for law, arts in json.loads(LAW_ARTICLES_FILE.read_text(encoding="utf-8"))["laws"].items():
            for no, text in arts.items():
                current[_ref_name(law, no)] = text
    law_pages = _law_pages(docs_dir)

    out = docs_dir / NOTES_ROOT
    out.mkdir(parents=True, exist_ok=True)
    if (MY_NOTES_DIR / "images").exists():
        shutil.copytree(MY_NOTES_DIR / "images", out / "images", dirs_exist_ok=True)

    by_law: Dict[str, List[dict]] = defaultdict(list)
    for n in notes:
        by_law[n["law"]].append(n)
    slugs = {law: _slug(law, timeline) for law in by_law}
    by_ref: Dict[str, List[Tuple[str, str, dict]]] = defaultdict(list)  # 法條 → [(法規頁, 錨點, 筆記)]
    stats = {}
    for law, items in by_law.items():
        for i, n in enumerate(items, 1):
            n["_anchor"] = f"n{i}"
            n["_refs"] = [_ref_name(law, n["no"])] if n["kind"] == "article" else n.get("refs", [])
            if n["kind"] == "article":
                n["_status"] = article_status(n.get("text", []), current.get(n["_refs"][0]))
            for ref in n["_refs"]:
                by_ref[ref].append((slugs[law], n["_anchor"], n))
        stats[law] = _write_law(out / f"{slugs[law]}.md", law, items, current, timeline, law_pages)
    _write_index(out / "index.md", by_law, slugs, stats)
    n_linked = _inject(docs_dir, law_pages, by_ref)
    logger.info(f"我的法條筆記：{len(notes)} 則、{len(by_law)} 部法規，掛到 {n_linked} 個法條頁")
    return [("總覽", f"{NOTES_ROOT}/index.md")] + [(law, f"{NOTES_ROOT}/{slugs[law]}.md") for law in by_law]


def _ref_chip(
    ref: str,
    law: str,
    current: Dict[str, str],
    timeline: LawTimeline,
    law_pages: Dict[str, List[Tuple[str, Path]]],
    docs_dir_rel: str,
) -> str:
    """引用法條的標籤：有逐題讀法條頁就連過去（看歷屆題目），否則連全國法規資料庫。"""
    label = ref[len(law) :] if ref.startswith(law + "第") else ref
    later = [d for d in timeline.amended(ref) if d > NOTES_AS_OF]
    cls = "pb-count er-law" + (" er-warn" if later else "")
    tip = (
        f"整理後修正：{later[0]}"
        if later
        else ("現行法規查無此條" if ref not in current and _split_ref(ref)[0] in timeline.laws else "")
    )
    pages = law_pages.get(ref)
    if pages:
        fam, path = pages[0]
        href = f"{docs_dir_rel}exam-reader/{path.parent.parent.name}/laws/{path.stem}.md"
        tip = "；".join(t for t in (tip, f"{fam}考過，點開看歷屆題目") if t)
    else:
        href = timeline.url(ref)
    attr = f' title="{tip}"' if tip else ""
    if not href:
        return f'<span class="{cls}"{attr}>{label}</span>'
    target = "" if pages else ' target="_blank"'
    return f'<a class="{cls}" href="{href}"{target}{attr}>{label}{"（整理後修正）" if later else ""}</a>'


def _indent(lines: List[str]) -> List[str]:
    return [("    " + ln) if ln else "" for ln in lines]


def _write_law(
    path: Path,
    law: str,
    items: List[dict],
    current: Dict[str, str],
    timeline: LawTimeline,
    law_pages: Dict[str, List[Tuple[str, Path]]],
) -> Dict[str, int]:
    arts = [n for n in items if n["kind"] == "article"]
    topics = [n for n in items if n["kind"] == "topic"]
    changed = [n for n in arts if n["_status"] != "same"]
    tracked = law in timeline.laws
    lines = [
        HIDE_NAV,
        f"# {law}：我的法條筆記",
        "",
        '<p class="qb-meta"><a href="../">回筆記總覽</a>'
        + (f'<a href="{timeline.laws[law]["url"]}" target="_blank">全國法規資料庫</a>' if tracked else "")
        + "</p>",
        "",
    ]
    if not tracked:
        lines += [
            '!!! info "未追蹤這部法規"',
            "    網站沒有下載這部法規的現行條文，筆記無法自動比對修法，請自行對照全國法規資料庫。",
            "",
        ]
    summary = [f"**{len(arts)}** 則條文重點", f"**{len(topics)}** 則主題整理"]
    if changed:
        summary.append(f"其中 **{len(changed)}** 條跟現行條文不同（標「條文已修正」）")
    lines += ["、".join(summary) + "。", ""]
    if arts:
        lines += ["## 條文重點", ""]
        for n in sorted(arts, key=lambda n: tuple(int(x) for x in n["no"].split("-"))):
            lines += _article_md(n, law, current, timeline, law_pages)
    if topics:
        lines += ["## 主題整理", ""]
        for n in topics:
            lines += _topic_md(n, law, current, timeline, law_pages)
    path.write_text("\n".join(lines), encoding="utf-8")
    return {"articles": len(arts), "topics": len(topics), "changed": len(changed)}


def _badges(n: dict) -> List[str]:
    out = []
    if n.get("level"):
        hot = " er-hot" if "極度" in n["level"] else ""
        out.append(f'<span class="pb-count{hot}">{n["level"]}</span>')
    out += [f'<span class="pb-count" title="原筆記註記的考題出處">{e}</span>' for e in n.get("exams", [])]
    return out


def _article_md(
    n: dict, law: str, current: Dict[str, str], timeline: LawTimeline, law_pages: Dict[str, List[Tuple[str, Path]]]
) -> List[str]:
    ref = n["_refs"][0]
    memo = "；".join(n.get("memo", []))
    head = ref[len(law) :] + (f"　{memo}" if memo else "")
    badges = _badges(n)
    status = n["_status"]
    if status == "changed":
        badges.append('<span class="pb-count er-warn">條文已修正</span>')
    elif status == "missing" and law in timeline.laws:
        badges.append('<span class="pb-count er-warn">現行法規查無此條</span>')
    for fam, page in law_pages.get(ref, []):
        badges.append(
            f'<a class="pb-count er-law" href="../exam-reader/{page.parent.parent.name}/laws/{page.stem}.md">'
            f"{fam}歷屆題目</a>"
        )
    url = timeline.url(ref)
    if url:
        badges.append(f'<a class="pb-count" href="{url}" target="_blank">全國法規資料庫</a>')
    lines = [f"### {_html_safe(head)} {{#{n['_anchor']}}}", "", f'<p class="qb-meta">{"".join(badges)}</p>', ""]
    old = [ln for ln in n.get("text", []) if ln.strip()]
    cur = current.get(ref)
    if cur and status != "missing":
        lines += ['??? quote "現行條文"' if status == "same" else '!!! quote "現行條文"', ""]
        lines += _indent([x for par in cur.split("\n") if par.strip() for x in (_html_safe(par.strip()), "")])
    if old and status != "same":
        title = "原整理條文（與現行不同，僅供對照）" if status == "changed" else "原整理條文"
        lines += [f'??? note "{title}"', ""] + _indent([x for ln in old for x in (_html_safe(ln), "")])
    elif old and not cur:
        lines += ['??? note "原整理條文"', ""] + _indent([x for ln in old for x in (_html_safe(ln), "")])
    return lines


def _topic_md(
    n: dict, law: str, current: Dict[str, str], timeline: LawTimeline, law_pages: Dict[str, List[Tuple[str, Path]]]
) -> List[str]:
    chips = _badges(n) + [_ref_chip(r, law, current, timeline, law_pages, "../") for r in n["_refs"][:10]]
    lines = [f"### {_html_safe(n['title'])} {{#{n['_anchor']}}}", ""]
    if chips:
        lines += [f'<p class="qb-meta">{"".join(chips)}</p>', ""]
    return lines + [_html_safe(n["body"]), ""]


def _write_index(path: Path, by_law: Dict[str, List[dict]], slugs: Dict[str, str], stats: Dict[str, dict]) -> None:
    total = sum(len(v) for v in by_law.values())
    changed = sum(s["changed"] for s in stats.values())
    lines = [
        HIDE_NAV,
        "# 我的法條筆記",
        "",
        f"地政士、不動產經紀人備考時手工整理的重點，依法規拆成 **{total}** 則筆記：",
        "",
        "- **條文重點**：條號、重要度與口訣，附現行條文。每次網站更新都會跟全國法規資料庫比對，"
        f"目前有 **{changed}** 條跟整理時不同，標「條文已修正」，原整理條文收合在下方供對照。",
        "- **主題整理**：申論題架構、比較表與歷屆考題出處。引用的條文標籤可點開，"
        "逐題讀有這一條的會連到歷屆題目；整理後（2021 年以後）修正過的條文標橘色。",
        "",
        "逐題讀的法條頁也會在「我的筆記」區塊列出相關筆記。",
        "",
        "| 法規 | 條文重點 | 主題整理 | 已修正 |",
        "|---|---:|---:|---:|",
    ]
    for law in by_law:
        s = stats[law]
        nums = " | ".join(str(s[k] or "") for k in ("articles", "topics", "changed"))
        lines.append(f"| [{law}]({slugs[law]}.md) | {nums} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _inject(
    docs_dir: Path, law_pages: Dict[str, List[Tuple[str, Path]]], by_ref: Dict[str, List[Tuple[str, str, dict]]]
) -> int:
    """法條頁的 MARK 換成「我的筆記」：條文卡顯示口訣，主題卡列標題連回筆記頁。"""
    linked = 0
    for ref, pages in law_pages.items():
        items = by_ref.get(ref, [])
        for _, path in pages:
            block = ""
            if items:
                body = []
                for slug, anchor, n in items:
                    href = f"../../../{NOTES_ROOT}/{slug}.md#{anchor}"
                    if n["kind"] == "article":
                        extra = "　".join(x for x in (n.get("level") or "", "；".join(n.get("memo", []))) if x)
                        flag = "（整理後條文已修正）" if n["_status"] == "changed" else ""
                        body.append(f"- [條文重點]({href}){flag}" + (f"：{_html_safe(extra)}" if extra else ""))
                    else:
                        exams = f"（{'、'.join(n['exams'])}）" if n.get("exams") else ""
                        body.append(f"- [{_html_safe(n['title'])}]({href}){exams}")
                block = "\n".join([f'???+ tip "我的筆記（{len(items)} 則）"', ""] + _indent(body)) + "\n"
                linked += 1
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace(MARK, block), encoding="utf-8")
    for path in (docs_dir / "exam-reader").glob("*/laws/*.md"):  # 沒有對到筆記的頁面
        text = path.read_text(encoding="utf-8")
        if MARK in text:
            path.write_text(text.replace(MARK, ""), encoding="utf-8")
    return linked
