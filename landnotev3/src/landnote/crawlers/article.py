import time
import random
import re
import hashlib
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Set, Any
import requests
import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm

from landnote.config import ARTICLE_BASE_URL, ARTICLE_AUTHORS, DATA_DIR, LOGS_DIR
from landnote.core.scraper import BaseScraper, ScraperConfig
from landnote.utils.text import TextUtils
from landnote.utils.logger import Logger

class ArticleCrawler(BaseScraper):
    def __init__(self, mode: str = "all", check_specific: bool = True):
        super().__init__("ArticleCrawler", ScraperConfig())
        self.mode = mode
        self.check_specific = check_specific
        
        # 設定
        self.base_url = ARTICLE_BASE_URL
        self.detail_url = f"{self.base_url}detail.aspx"
        self.journal_url = f"{self.base_url}journal.aspx"
        self.target_authors = ARTICLE_AUTHORS
        
        # 目錄設定
        self.base_dir = DATA_DIR / "real_estate_articles"
        self.articles_dir = self.base_dir / "articles"
        self.images_dir = self.articles_dir / "images"
        self.data_file = self.base_dir / "articles.xlsx"
        self.logs_dir = LOGS_DIR
        
        self.processed_articles: Set[str] = set()
        self.pno_values = ["51120", "51121"]
        
        # 初始化
        self.setup_directories()
        self.load_processed_articles()
        
        # 更新 Logger
        self.logger = Logger.setup_logger("ArticleCrawler", self.logs_dir)

    def setup_directories(self):
        """建立必要的目錄結構"""
        for directory in [self.base_dir, self.articles_dir, self.images_dir]:
            directory.mkdir(parents=True, exist_ok=True)
            
        # 創建預設的失敗圖片 (Optional)
        self.failed_image_path = self.images_dir / "image_download_failed.png"
        if not self.failed_image_path.exists():
            try:
                from PIL import Image, ImageDraw
                img = Image.new('RGB', (400, 100), color='white')
                d = ImageDraw.Draw(img)
                d.text((10, 40), "Image Download Failed", fill='black')
                img.save(self.failed_image_path)
            except ImportError:
                # Pillow not installed or failed
                pass
            except Exception:
                self.failed_image_path.touch()

    def load_processed_articles(self):
        """載入已處理的文章"""
        if self.data_file.exists():
            try:
                df = pd.read_excel(self.data_file)
                if '文章編號' in df.columns:
                    self.processed_articles = set(df['文章編號'].astype(str))
            except Exception as e:
                self.logger.error(f"Error loading processed articles: {e}")

    def run(self):
        """執行爬蟲主流程"""
        self.logger.info(f"Starting crawl. Mode: {self.mode}")
        
        if self.mode == "update":
            # 更新模式：只檢查前幾頁
            max_pages_to_check = 5 
        else:
            # 完整模式：檢查所有頁面
            max_pages_to_check = self.get_max_page_number()
            
        self.logger.info(f"Scanning up to page {max_pages_to_check}")

        total_new = 0
        for page_no in range(1, max_pages_to_check + 1):
            self.logger.info(f"Processing page {page_no}...")
            new_articles = self.get_article_urls_from_journal(page_no)
            
            if not new_articles and self.mode == "update":
                 self.logger.info("No new articles found on this page in update mode. Stopping.")
                 break
                 
            for article_no in tqdm(new_articles, desc=f"Page {page_no}"):
                result = self.fetch_article(article_no)
                if result:
                    self.save_article(result)
                    total_new += 1
                time.sleep(self.config.retry_delay / 10) # Small delay
                
        self.logger.info(f"Crawl completed. Collected {total_new} new articles.")

    def get_max_page_number(self) -> int:
        """獲取期刊最大頁數"""
        max_page = 1
        for pno in self.pno_values:
            params = {"no": "1282", "pno": pno}
            try:
                response = self.make_request("GET", self.journal_url, params=params)
                if not response: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                pagination = soup.select('.pagination a')
                if pagination:
                    page_numbers = [int(a.text.strip()) for a in pagination if a.text.strip().isdigit()]
                    if page_numbers:
                        max_page = max(max_page, max(page_numbers))
            except Exception as e:
                self.logger.error(f"Error getting max page for pno={pno}: {e}")
        return max_page

    def get_article_urls_from_journal(self, page_no: int) -> List[int]:
        """從期刊頁面獲取文章編號列表"""
        articles = []
        for pno in self.pno_values:
            params = {"no": "1282", "pno": pno, "page_no": page_no}
            try:
                response = self.make_request("GET", self.journal_url, params=params)
                if not response: continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                for link in soup.select('a[href*="detail.aspx?no="]'):
                    href = link.get('href', '')
                    if match := re.search(r'no=(\d+)', href):
                        article_no = int(match.group(1))
                        # 如果是更新模式，且文章已存在，則不加入列表 (除非我們想更新內容)
                        if str(article_no) not in self.processed_articles:
                            articles.append(article_no)
            except Exception as e:
                self.logger.error(f"Error getting articles from pno={pno} page={page_no}: {e}")
        return articles

    def fetch_article(self, article_no: int) -> Optional[Dict]:
        """抓取並解析單篇文章"""
        # 再次檢查 (防止重複)
        if str(article_no) in self.processed_articles:
            return None
            
        url = f"{self.detail_url}?no={article_no}"
        try:
            response = self.make_request("GET", url)
            if not response or response.status_code == 404:
                return None
                
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 簡易驗證
            if not soup.select('.columnsDetail_tableRow'):
                 return None

            article_data = self.parse_article(soup, article_no)
            return article_data

        except Exception as e:
            self.logger.error(f"Failed to fetch article {article_no}: {e}")
            return None

    def parse_article(self, soup: BeautifulSoup, article_no: int) -> Optional[Dict]:
        """解析文章內容"""
        try:
            article_info = {}
            
            # Meta parsing
            meta_author = soup.select_one('meta[name="citation_author"]')
            meta_title = soup.select_one('meta[name="citation_title"]')
            meta_date = soup.select_one('meta[name="citation_publication_date"]')
            
            if meta_author: article_info['作者'] = meta_author.get('content', '').strip()
            if meta_title: article_info['標題'] = meta_title.get('content', '').strip()
            if meta_date: article_info['日期'] = meta_date.get('content', '').strip()

            # Table parsing
            rows = soup.select('.columnsDetail_tableRow')
            for row in rows:
                th = row.select_one('.columnsDetail_tableth')
                td = row.select_one('.columnsDetail_tabletd')
                if th and td:
                    key = th.text.strip()
                    value = td.text.strip()
                    if key == '篇名': article_info['標題'] = value
                    elif key == '作者': article_info['作者'] = value
                    elif key == '日期': article_info['日期'] = value
                    elif key == '內文': article_info['內文HTML'] = str(td)
                    elif key == '關鍵詞': article_info['關鍵詞'] = value

            # 驗證作者
            author = article_info.get('作者')
            if not author or not any(target in author for target in self.target_authors):
                return None

            # 處理內文
            html_content = article_info.get('內文HTML', '')
            if not html_content:
                content_div = soup.select_one('.columnsDetail_tabletd#SearchItem')
                if content_div:
                    html_content = str(content_div)
            
            processed_content = self.process_content(html_content, article_no)
            
            return {
                '文章編號': article_no,
                '標題': article_info.get('標題', ''),
                '作者': article_info.get('作者', ''),
                '日期': article_info.get('日期', ''),
                '內文': processed_content,
                'URL': f"{self.detail_url}?no={article_no}",
                '爬取時間': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                '關鍵詞': article_info.get('關鍵詞', '')
            }
        except Exception as e:
            self.logger.error(f"Error parsing article {article_no}: {e}")
            return None

    def process_content(self, html_content: str, article_no: int) -> str:
        """處理文章內容: 圖片下載 -> 表格處理 -> 文本格式化"""
        if not html_content:
            return ""

        soup = BeautifulSoup(html_content, 'html.parser')

        # 1. 處理圖片（去重：同一檔名只保留第一次出現）
        image_references = []
        seen_filenames: Set[str] = set()
        img_counter = 0
        for img in soup.find_all('img'):
            img_url = img.get('src', '')
            if img_url:
                local_filename = self.download_image(img_url, article_no)
                if local_filename:
                    img_counter += 1
                    if local_filename not in seen_filenames:
                        seen_filenames.add(local_filename)
                        image_references.append(f"\n![圖片{img_counter}](./images/{local_filename})\n")
                    img.replace_with(f"[圖片{img_counter}]")
                else:
                    img.replace_with("[圖片下載失敗]")

        # 2. 處理表格 (HTML -> Markdown)
        tables = soup.find_all('table')
        table_placeholders = {}
        for i, table in enumerate(tables, 1):
            md_table = TextUtils.html_table_to_markdown(table)
            placeholder = f"TABLE_PLACEHOLDER_{i}"
            table_placeholders[placeholder] = md_table
            table.replace_with(f"{placeholder}")

        # 3. 格式化剩餘文本
        content = TextUtils.format_content(soup)

        # 4. 替換回 Markdown 表格
        for placeholder, md_table in table_placeholders.items():
            content = content.replace(placeholder, f"\n\n{md_table}\n\n")

        # 5. 附加圖片
        if image_references:
            content += "\n\n## 文章圖片\n" + "".join(image_references)

        return content

    def download_image(self, img_url: str, article_no: int) -> Optional[str]:
        """下載圖片"""
        try:
            if not img_url.startswith(('http://', 'https://')):
                img_url = urllib.parse.urljoin(self.base_url, img_url)
                
            url_hash = hashlib.md5(img_url.encode()).hexdigest()[:8]
            file_ext = Path(img_url).suffix or '.jpg'
            local_filename = f"{article_no}_{url_hash}{file_ext}"
            local_path = self.images_dir / local_filename
            
            if local_path.exists():
                return local_filename
                
            response = self.make_request("GET", img_url)
            if response:
                with open(local_path, 'wb') as f:
                    f.write(response.content)
                return local_filename
            return None
        except Exception as e:
            self.logger.warning(f"Image download failed {img_url}: {e}")
            return None

    def save_article(self, article_data: Dict) -> None:
        """儲存文章 (Excel & Markdown)"""
        try:
            # 1. Update Excel
            new_df = pd.DataFrame([article_data])
            if self.data_file.exists():
                df = pd.read_excel(self.data_file)
                df = pd.concat([df, new_df]).drop_duplicates(subset=['文章編號'])
            else:
                df = new_df
            df.to_excel(self.data_file, index=False)
            
            # 2. Save Markdown
            article_no = article_data['文章編號']
            safe_title = re.sub(r'[<>:"/\\|?*]', '', article_data['標題'])[:50]
            
            keywords_section = ""
            if '關鍵詞' in article_data and article_data['關鍵詞']:
                keywords_section = f"- 關鍵詞：{article_data['關鍵詞']}\n"

            markdown_content = f"""# {article_data['標題']}

## 文章資訊
- 文章編號：{article_no}
- 作者：{article_data['作者']}
- 發布日期：{article_data['日期']}
{keywords_section}- 爬取時間：{article_data['爬取時間']}
- 原文連結：[閱讀原文]({article_data['URL']})

## 內文
{article_data['內文']}

---
*注：本文圖片存放於 ./images/ 目錄下*
"""
            file_path = self.articles_dir / f"{article_no}_{safe_title}.md"
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
                
            self.processed_articles.add(str(article_no))
            self.logger.info(f"Saved article {article_no}")
            
        except Exception as e:
            self.logger.error(f"Failed to save article {article_data.get('文章編號')}: {e}")
