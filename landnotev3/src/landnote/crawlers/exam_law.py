"""高點法律網考古題爬蟲。

列表頁 List.aspx?iPageNo=N 依年度由新到舊排列，每頁 15 筆。
檔案存成 高點法律考古題/<考試類組>/<科目>/<民國年>年_<考試類組>_<科目>.pdf，
已存在的檔案不重下載；all_exams.csv 與 README.md 記錄全部已收錄的試題。
"""

import csv
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from bs4 import BeautifulSoup

from landnote.config import BASE_DIR, LAW_EXAM_BASE_URL, LOGS_DIR
from landnote.core.scraper import BaseScraper, ScraperConfig
from landnote.utils.logger import Logger
from landnote.utils.pdf_processor import PDFProcessor

DOWNLOAD_URL = "https://lawyer.get.com.tw/exam/Download.ashx"
CSV_FIELDS = ["id", "type", "subject", "year", "download_url", "filename"]


@dataclass
class LawExamDocument:
    exam_type: str
    subject: str
    year: str
    download_url: str

    @property
    def filename(self) -> str:
        return f"{self.year}年_{self.exam_type}_{self.subject}.pdf"


class LawExamCrawler(BaseScraper):
    def __init__(self, base_folder: Optional[Path] = None, debug: bool = False):
        super().__init__("LawExamCrawler", ScraperConfig())
        self.debug = debug
        self.base_folder = base_folder or BASE_DIR / "高點法律考古題"
        self.base_folder.mkdir(parents=True, exist_ok=True)
        self.csv_file = self.base_folder / "all_exams.csv"
        self.readme_file = self.base_folder / "README.md"
        self.logger = Logger.setup_logger("LawExamCrawler", LOGS_DIR)

    def run(self, max_pages: Optional[int] = None, only_update: bool = False, stop_after: int = 3) -> int:
        """爬列表並下載缺少的 PDF，回傳新下載份數。

        Args:
            max_pages: 最多爬幾頁，None 為全部。
            only_update: 只找新題目；連續 stop_after 頁都沒有新題目就停止（列表由新到舊）。
            stop_after: only_update 時的停止門檻。
        """
        self.make_request("GET", "https://lawyer.get.com.tw/")  # 先取得 session cookie
        first = self.get_page(1)
        if first is None:
            raise RuntimeError("無法取得高點法律網考古題列表")
        total_pages = self.get_total_pages(first)
        if max_pages:
            total_pages = min(total_pages, max_pages)
        self.logger.info(f"列表共 {total_pages} 頁（{'只找新題目' if only_update else '完整掃描'}）")

        known = self.load_csv()
        known_names = {d.filename for d in known}
        found: List[LawExamDocument] = []
        downloaded = 0
        idle_pages = 0
        for page_no in range(1, total_pages + 1):
            soup = first if page_no == 1 else self.get_page(page_no)
            if soup is None:
                self.logger.error(f"第 {page_no} 頁取得失敗，略過")
                continue
            new_on_page = 0
            for doc in self.parse_exam_info(soup):
                is_new = not self.target_path(doc).exists()
                if is_new and self.download_pdf(doc):
                    downloaded += 1
                    time.sleep(random.uniform(1, 3))
                if doc.filename not in known_names:
                    known_names.add(doc.filename)
                    found.append(doc)
                    is_new = True
                new_on_page += is_new
            self.logger.info(f"第 {page_no}/{total_pages} 頁：{new_on_page} 份新題目")
            idle_pages = 0 if new_on_page else idle_pages + 1
            if only_update and idle_pages >= stop_after:
                self.logger.info(f"連續 {stop_after} 頁沒有新題目，停止")
                break
            time.sleep(random.uniform(1, 3))

        if found:
            # 新題目接在最後，舊紀錄的編號與 README 順序不變，diff 只有新增的部分
            self.save_csv(known + found)
            self.write_readme(known + found)
        self.logger.info(f"完成：新下載 {downloaded} 份 PDF，新增 {len(found)} 筆紀錄")
        return downloaded

    def get_total_pages(self, soup: BeautifulSoup) -> int:
        """從「第 1 頁,共 193 頁」或分頁連結取得總頁數。"""
        match = re.search(r"共\s*(\d+)\s*頁", soup.get_text())
        if match:
            return int(match.group(1))
        pages = [
            int(m.group(1)) for a in soup.select("a[href*='iPageNo=']") if (m := re.search(r"iPageNo=(\d+)", a["href"]))
        ]
        return max(pages, default=1)

    def get_page(self, page_no: int) -> Optional[BeautifulSoup]:
        response = self.make_request("GET", LAW_EXAM_BASE_URL, params={"iPageNo": page_no})
        return BeautifulSoup(response.text, "html.parser") if response else None

    def parse_exam_info(self, soup: BeautifulSoup) -> List[LawExamDocument]:
        """解析 table.examlist：編號、考試類組、考試科目、年度、下載連結。"""
        table = soup.find("table", class_="examlist")
        if not table:
            self.logger.warning("找不到 table.examlist，來源網站可能改版")
            return []
        exams = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            link = cells[4].find("a", href=True) if len(cells) >= 5 else None
            if not link or "Download.ashx" not in link["href"]:
                continue
            query = link["href"].split("?", 1)[1] if "?" in link["href"] else ""
            exams.append(
                LawExamDocument(
                    exam_type=cells[1].get_text(strip=True),
                    subject=cells[2].get_text(strip=True),
                    year=cells[3].get_text(strip=True),
                    download_url=f"{DOWNLOAD_URL}?{query}",
                )
            )
        return exams

    def target_path(self, doc: LawExamDocument) -> Path:
        return self.base_folder / doc.exam_type / doc.subject / doc.filename

    def download_pdf(self, doc: LawExamDocument) -> bool:
        final_path = self.target_path(doc)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        response = self.make_request("GET", doc.download_url, stream=True)
        if not response or response.status_code != 200:
            self.logger.error(f"下載失敗：{doc.filename}")
            return False
        temp_path = final_path.with_name(f"temp_{doc.filename}")
        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        if not temp_path.read_bytes()[:5].startswith(b"%PDF"):
            temp_path.unlink()
            self.logger.error(f"下載內容不是 PDF：{doc.filename}")
            return False
        if PDFProcessor.unlock_pdf(str(temp_path), str(final_path)):
            temp_path.unlink(missing_ok=True)
        else:
            temp_path.replace(final_path)
        self.logger.info(f"已下載：{final_path.relative_to(self.base_folder)}")
        return True

    def load_csv(self) -> List[LawExamDocument]:
        if not self.csv_file.exists():
            return []
        with open(self.csv_file, encoding="utf-8-sig", newline="") as f:
            return [LawExamDocument(r["type"], r["subject"], r["year"], r["download_url"]) for r in csv.DictReader(f)]

    def save_csv(self, docs: List[LawExamDocument]) -> None:
        with open(self.csv_file, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(CSV_FIELDS)
            for i, d in enumerate(docs, 1):
                writer.writerow([i, d.exam_type, d.subject, d.year, d.download_url, d.filename])

    def write_readme(self, docs: List[LawExamDocument]) -> None:
        """依考試類組 → 科目列出全部試題（沿用原 README 格式）。"""
        grouped: Dict[str, Dict[str, List[LawExamDocument]]] = {}
        for d in docs:
            grouped.setdefault(d.exam_type, {}).setdefault(d.subject, []).append(d)
        subjects: Set[str] = {f"{t}/{s}" for t, subs in grouped.items() for s in subs}

        def anchor(exam_type: str, subject: str) -> str:
            return re.sub(r"[（）]", "", f"{exam_type}-{subject}").replace(" ", "-")

        lines = [
            "# 高點法律網考古題下載整理",
            "",
            f"最後更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"總共收集了 {len(docs)} 份考古題，涵蓋 {len(grouped)} 種考試類型，{len(subjects)} 個科目。",
            "",
            "## 目錄",
            "",
        ]
        for exam_type, subs in grouped.items():
            lines.append(f"- [{exam_type}](#{exam_type.replace(' ', '-')})")
            lines.extend(f"  - [{s} ({len(items)}份)](#{anchor(exam_type, s)})" for s, items in subs.items())
        lines.append("")
        for exam_type, subs in grouped.items():
            lines.extend([f"## {exam_type}", ""])
            for s, items in subs.items():
                lines.extend([f"### <a id='{anchor(exam_type, s)}'></a>{s} ({len(items)}份)", ""])
                items = sorted(items, key=lambda d: -int(d.year) if d.year.isdigit() else 0)
                lines.extend(f"- [{d.year}年 {exam_type} {s}]({d.download_url})" for d in items)
                lines.append("")
        self.readme_file.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
