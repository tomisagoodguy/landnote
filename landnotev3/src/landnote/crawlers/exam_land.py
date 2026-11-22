import time
import random
import re
from datetime import datetime
from pathlib import Path
from typing import List
from urllib.parse import quote
from tqdm import tqdm
from bs4 import BeautifulSoup

from landnote.config import BASE_DIR, EXAM_BASE_URL, LOGS_DIR, MOEX_EXAM_URL, MOEX_FILE_URL
from landnote.core.scraper import BaseScraper, ScraperConfig
from landnote.utils.logger import Logger
from landnote.utils.pdf_processor import PDFProcessor

class ExamDocument:
    """考古題文件類"""
    def __init__(self, index, group, subject, year, link):
        self.index = index
        self.group = group
        self.subject = subject
        self.year = year
        self.link = link
        self.file_name = f"[{year}][{group}][{subject}].pdf"
        self.file_name = self.file_name.replace('\r', '').replace('\n', '')

class LandExamCrawler(BaseScraper):
    def __init__(self, debug=False):
        super().__init__("LandExamCrawler", ScraperConfig())
        self.debug = debug
        self.base_folder = BASE_DIR / "地政考古題"
        self.readme_path = self.base_folder / "README.md"
        self.log_file = self.base_folder / "download_log.txt"
        
        # Ensure directories exist
        self.base_folder.mkdir(parents=True, exist_ok=True)
        
        # Setup Logger
        self.logger = Logger.setup_logger("LandExamCrawler", LOGS_DIR)
        
        # 高點：類科或科目名稱含任一關鍵字即收錄
        self.keywords = ["地政", "估價", "不動產", "土地"]
        # 考選部：高點沒有的專技考試，依類科名稱比對（每年考試代碼不同）
        self.moex_categories = {"不動產估價師": "專技高考", "地政士": "專技普考", "不動產經紀人": "專技普考"}

    def log(self, message):
        self.logger.info(message)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")

    def run(self, years=10, only_update=False):
        """執行下載流程"""
        self.log("=== 地政考古題自動下載與解鎖系統 ===")
        
        total_downloads = 0
        # 網站使用民國年；其 sFilterDate 年份過濾已失效，改抓全部清單後本地過濾
        min_year = datetime.now().year - 1911 - years + 1
        self.log(f"Processing ROC years >= {min_year}...")
        for keyword in self.keywords:
            total_downloads += self.download_by_keyword(keyword, 'A', '', only_update, min_year)
        for category in self.moex_categories:
            total_downloads += self.download_moex(category, min_year)

        self.generate_readme()
        self.log(f"Completed. Total downloaded: {total_downloads}")

    def download_by_keyword(self, keyword, filter_type='A', year='', skip_existing=True, min_year=0):
        """下載特定關鍵字的考古題（僅下載尚未存在的檔案）"""
        exam_docs = [
            d for d in self.search_exams(keyword, filter_type, year)
            if d.year.isdigit() and int(d.year) >= min_year
        ]
        if skip_existing:
            exam_docs = [d for d in exam_docs if not (self.base_folder / d.subject / d.file_name).exists()]
        if not exam_docs:
            return 0

        download_count = 0
        self.log(f"Found {len(exam_docs)} new exams for keyword '{keyword}'")

        for doc in tqdm(exam_docs, desc=f"Downloading {keyword}"):
            if self.download_and_unlock(doc, skip_existing):
                download_count += 1
                self.log(f"成功下載: {doc.file_name}")

            time.sleep(random.uniform(1.0, 2.0))

        return download_count

    def search_exams(self, keyword, filter_type='A', year='') -> List[ExamDocument]:
        """搜尋考古題"""
        encoded_keyword = quote(keyword)
        # Get total pages
        total_page = self.get_total_pages(keyword, filter_type, year)
        if total_page == 0:
            return []

        exam_documents = []
        
        for i in range(1, total_page + 1):
             url = f'{EXAM_BASE_URL}?iPageNo={i}&sFilter={encoded_keyword}&sFilterDate={year}&sFilterType={filter_type}'
             try:
                 response = self.make_request("GET", url)
                 if not response: continue
                 
                 soup = BeautifulSoup(response.text, "html.parser")
                 for exam in soup.find_all('tr'):
                     cols = exam.find_all('td')
                     if len(cols) >= 5 and cols[3].text.strip().isdigit():
                         group = cols[1].text.strip()
                         subject = cols[2].text.strip()
                         
                         if keyword in group or keyword in subject:
                             link_elem = cols[4].find('a')
                             if link_elem and link_elem.get('href'):
                                 raw_link = link_elem.get('href').replace('./', '')
                                 link = 'http://goldensun.get.com.tw/exam/' + raw_link
                                 
                                 doc = ExamDocument(
                                     index=cols[0].text.strip(),
                                     group=group,
                                     subject=subject,
                                     year=cols[3].text.strip(),
                                     link=link
                                 )
                                 exam_documents.append(doc)
             except Exception as e:
                 self.logger.error(f"Error parsing page {i}: {e}")
                 
        return exam_documents

    def search_moex(self, category: str, min_year: int) -> List[ExamDocument]:
        """搜尋考選部題庫中類科名稱含 category 的所有科目試題。"""
        docs = []
        current_roc = datetime.now().year - 1911
        for roc in range(min_year, current_roc + 1):
            year_page = self.make_request("GET", f"{MOEX_EXAM_URL}?y={roc + 1911}")
            if year_page is None or year_page.status_code != 200:
                self.log(f"考選部 {roc} 年清單讀取失敗")
                continue
            year_page.encoding = "utf-8"
            # 選單上的考試名稱過長會被截斷（如「普通考試地政...」），只能先取所有專技考試再比對類科
            codes = re.findall(r'<option[^>]*value="(%d\d{3})">[^<]*(?:專技|專門職業)' % roc, year_page.text)
            for code in codes:
                page = self.make_request("GET", f"{MOEX_EXAM_URL}?y={roc + 1911}&e={code}")
                if page is None or page.status_code != 200:
                    continue
                page.encoding = "utf-8"
                labels = dict(re.findall(
                    r'<label for="ctl00_holderContent_chk_%s_(\d+(?:_\w+)?)"[^>]*>([^<]*)</label>' % code, page.text))
                for cid, cname in labels.items():
                    if "_" in cid or category not in cname:
                        continue
                    group = f"{self.moex_categories[category]}-{category}"
                    for key, subject in labels.items():
                        if key.startswith(cid + "_"):
                            sid = key.split("_", 1)[1]
                            link = f"{MOEX_FILE_URL}?t=Q&code={code}&c={cid}&s={sid}&q=1"
                            docs.append(ExamDocument("", group, subject.strip(), str(roc), link))
                time.sleep(random.uniform(0.5, 1.0))
        return docs

    def download_moex(self, category: str, min_year: int) -> int:
        """下載考選部題庫中尚未存在的試題。"""
        docs = [d for d in self.search_moex(category, min_year)
                if not (self.base_folder / d.subject / d.file_name).exists()]
        if not docs:
            return 0
        self.log(f"Found {len(docs)} new exams for 考選部 '{category}'")
        count = 0
        for doc in tqdm(docs, desc=f"Downloading {category}"):
            if self.download_and_unlock(doc):
                count += 1
                self.log(f"成功下載: {doc.file_name}")
            time.sleep(random.uniform(1.0, 2.0))
        return count

    def get_total_pages(self, keyword, filter_type, year):
        encoded_keyword = quote(keyword)
        url = f'{EXAM_BASE_URL}?iPageNo=1&sFilter={encoded_keyword}&sFilterDate={year}&sFilterType={filter_type}'
        try:
            response = self.make_request("GET", url)
            if not response: return 0
            
            soup = BeautifulSoup(response.text, "html.parser")
            page_div = soup.find("div", class_="page")
            if not page_div: return 0
            
            # Text example: "第 1 頁,共 36 頁, 540筆資料"
            m = re.search(r"共\s*(\d+)\s*頁", page_div.text)
            return int(m.group(1)) if m else 0
        except Exception as e:
            self.logger.error(f"Failed to get total pages: {e}")
            return 0

    def download_and_unlock(self, doc: ExamDocument, skip_existing=True):
        """下載並解鎖 PDF"""
        subject_folder = self.base_folder / doc.subject
        subject_folder.mkdir(exist_ok=True)
        
        final_path = subject_folder / doc.file_name
        if skip_existing and final_path.exists():
            return True

        # 1. Download（Download.ashx 會轉址到實際 PDF，requests 自動跟隨）
        try:
            response = self.make_request("GET", doc.link)
            if response is None or response.status_code != 200 or not response.content.startswith(b"%PDF"):
                status = response.status_code if response is not None else "no response"
                self.log(f"下載失敗（來源檔案無效，HTTP {status}）: {doc.file_name}")
                return False

            temp_path = subject_folder / f"temp_{doc.file_name}"
            with open(temp_path, "wb") as f:
                f.write(response.content)
                
            # 3. Unlock
            success = PDFProcessor.unlock_pdf(str(temp_path), str(final_path))
            
            if success:
                if temp_path.exists(): temp_path.unlink()
            else:
                # If unlock fails, move temp to final
                if not final_path.exists():
                    temp_path.rename(final_path)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Download failed {doc.file_name}: {e}")
            return False

    def generate_readme(self):
        """生成 README.md"""
        if not self.base_folder.exists(): return

        def year_key(p: Path) -> int:
            m = re.match(r"\[(\d+)\]", p.name)
            return int(m.group(1)) if m else 0

        merged_dir = self.base_folder / "合併後PDF檔案"
        merged_count = len(list(merged_dir.glob("*.pdf"))) if merged_dir.exists() else 0
        sections = []
        for folder in sorted(f for f in self.base_folder.iterdir() if f.is_dir() and f != merged_dir):
            pdfs = sorted(folder.glob("*.pdf"), key=lambda p: (year_key(p), p.name), reverse=True)
            if pdfs:
                sections.append((folder.name, pdfs))
        total = sum(len(pdfs) for _, pdfs in sections)

        def anchor(name: str) -> str:
            return re.sub(r"[（）]", "", name).replace(" ", "-")

        with open(self.readme_path, 'w', encoding='utf-8') as f:
            f.write("# 地政考古題資料庫\n\n")
            f.write("本資料庫收集地政、不動產估價相關考古題，按科目分類整理。"
                    "來源：高點公職考古題（類科或科目含「地政／估價／不動產／土地」）、"
                    "考選部題庫（專技高考不動產估價師）。\n\n")
            f.write(f"最後更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"總檔案數：{total} 份考古題，{len(sections)} 個科目"
                    f"（另有 {merged_count} 本[整科合併 PDF](合併後PDF檔案/)）\n\n## 目錄\n\n")
            for name, pdfs in sections:
                f.write(f"- [{name} ({len(pdfs)}份)](#{anchor(name)})\n")
            f.write("\n")
            for name, pdfs in sections:
                f.write(f"## {name}\n\n")
                for pdf in pdfs:
                    f.write(f"- [{pdf.stem}]({quote(name)}/{quote(pdf.name)})\n")
                f.write("\n")
