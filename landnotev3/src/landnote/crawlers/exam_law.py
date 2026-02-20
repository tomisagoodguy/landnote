import json
import time
import random
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict
from bs4 import BeautifulSoup
import pandas as pd
from tqdm import tqdm

from landnote.config import LAW_EXAM_BASE_URL, DATA_DIR, LOGS_DIR
from landnote.core.scraper import BaseScraper, ScraperConfig
from landnote.utils.logger import Logger
from landnote.utils.pdf_processor import PDFProcessor

class LawExamDocument:
    def __init__(self, index, exam_type, subject, year, download_url, download_params, filename):
        self.index = index
        self.exam_type = exam_type
        self.subject = subject
        self.year = year
        self.download_url = download_url
        self.download_params = download_params
        self.filename = filename

    def to_dict(self):
        return {
            "index": self.index,
            "exam_type": self.exam_type,
            "subject": self.subject,
            "year": self.year,
            "download_url": self.download_url,
            "download_params": self.download_params,
            "filename": self.filename
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            data["index"],
            data["exam_type"],
            data["subject"],
            data["year"],
            data["download_url"],
            data["download_params"],
            data["filename"]
        )

class LawExamCrawler(BaseScraper):
    def __init__(self, base_folder=None, debug=False):
        super().__init__("LawExamCrawler", ScraperConfig())
        self.debug = debug
        self.base_folder = base_folder if base_folder else DATA_DIR / "高點法律考古題"
        self.download_base_url = "https://lawyer.get.com.tw/exam/Download.ashx"
        self.base_url = LAW_EXAM_BASE_URL
        
        # Ensure directories
        self.base_folder.mkdir(parents=True, exist_ok=True)
        self.log_file = self.base_folder / "download_log.txt"
        self.checkpoint_file = self.base_folder / "checkpoint.json"
        
        # Logger
        self.logger = Logger.setup_logger("LawExamCrawler", LOGS_DIR)

    def run(self, max_pages=None, resume=True):
        self.logger.info("Starting Law Exam Crawler...")
        
        start_page = 1
        all_exams = []

        if resume and self.checkpoint_file.exists():
            # Load checkpoint logic (simplified)
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    start_page = data.get("last_page", 1) + 1
                    all_exams = [LawExamDocument.from_dict(d) for d in data.get("exams", [])]
                self.logger.info(f"Resuming from page {start_page} with {len(all_exams)} exams.")
            except Exception as e:
                self.logger.error(f"Failed to load checkpoint: {e}")

        total_pages = self.get_total_pages() or 176 # Fallback
        if max_pages and max_pages < total_pages:
            total_pages = max_pages

        self.logger.info(f"Total pages to process: {total_pages}")

        # Crawl List
        for page_no in range(start_page, total_pages + 1):
             self.logger.info(f"Processing page {page_no}/{total_pages}")
             soup = self.get_page(page_no)
             if soup:
                 exams = self.parse_exam_info(soup)
                 all_exams.extend(exams)
                 self.save_checkpoint(page_no, all_exams)
             time.sleep(random.uniform(2, 5))

        # Download
        self.download_all(all_exams)
        self.generate_readme(all_exams)

    def get_total_pages(self):
        # Retrieve homepage to get cookies/session if needed
        self.make_request("GET", "https://lawyer.get.com.tw/")
        
        soup = self.get_page(1)
        if not soup: return 0
        
        # Try to find total pages
        page_div = soup.find("div", class_="page")
        if page_div:
            match = re.search(r'共\s+(\d+)', page_div.text)
            if match: return int(match.group(1))
            
        # Fallback to links
        links = soup.select("a[href*='iPageNo=']")
        if links:
            pages = [int(re.search(r'iPageNo=(\d+)', l['href']).group(1)) for l in links if re.search(r'iPageNo=(\d+)', l['href'])]
            return max(pages) if pages else 0
            
        return 0

    def get_page(self, page_no):
        params = {"iPageNo": page_no}
        response = self.make_request("GET", self.base_url, params=params)
        if response:
            return BeautifulSoup(response.text, "html.parser")
        return None

    def parse_exam_info(self, soup) -> List[LawExamDocument]:
        exams = []
        table = soup.find("table", class_="examlist")
        if not table: return []
        
        rows = table.find_all("tr")
        for row in rows:
            if "head" in row.get("class", []): continue
            
            cells = row.find_all("td")
            if len(cells) >= 5:
                try:
                    exam_type = cells[1].text.strip()
                    subject = cells[2].text.strip()
                    year = cells[3].text.strip()
                    filename = f"{year}年_{exam_type}_{subject}.pdf"
                    
                    link = cells[4].find("a")
                    if link and "href" in link.attrs:
                        href = link["href"]
                        # extract params
                        params = {}
                        if "?" in href:
                            query = href.split("?")[1]
                            for pair in query.split("&"):
                                if "=" in pair:
                                    k, v = pair.split("=")
                                    params[k] = v
                                    
                        doc = LawExamDocument(
                            cells[0].text.strip(),
                            exam_type,
                            subject,
                            year,
                            self.download_base_url,
                            params,
                            filename
                        )
                        exams.append(doc)
                except Exception as e:
                    self.logger.error(f"Error parsing row: {e}")
        return exams

    def save_checkpoint(self, page_no, exams):
        data = {
            "last_page": page_no,
            "exams": [e.to_dict() for e in exams],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(self.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def download_all(self, exams: List[LawExamDocument]):
        downloaded = set()
        progress_file = self.base_folder / "download_progress.json"
        
        if progress_file.exists():
            with open(progress_file, 'r', encoding='utf-8') as f:
                downloaded = set(json.load(f))
                
        to_download = [e for e in exams if e.filename not in downloaded]
        
        for doc in tqdm(to_download, desc="Downloading PDFs"):
            if self.download_pdf(doc):
                downloaded.add(doc.filename)
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump(list(downloaded), f)
            time.sleep(random.uniform(2, 5))

    def download_pdf(self, doc: LawExamDocument):
        # Create directories
        type_dir = self.base_folder / doc.exam_type
        subject_dir = type_dir / doc.subject
        subject_dir.mkdir(parents=True, exist_ok=True)
        
        final_path = subject_dir / doc.filename
        if final_path.exists(): return True
        
        try:
            response = self.make_request("GET", self.download_base_url, params=doc.download_params, stream=True)
            if not response or response.status_code != 200: return False
            
            temp_path = subject_dir / f"temp_{doc.filename}"
            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Unlock
            success = PDFProcessor.unlock_pdf(str(temp_path), str(final_path))
            if success:
                temp_path.unlink(missing_ok=True)
            else:
                if not final_path.exists():
                    temp_path.rename(final_path)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to download {doc.filename}: {e}")
            return False

    def generate_readme(self, exams):
        # Simplified README generation
        readme_path = self.base_folder / "README.md"
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write("# Law Exams\n\n")
            for exam in exams:
                f.write(f"- {exam.year} {exam.exam_type} {exam.subject}\n")
