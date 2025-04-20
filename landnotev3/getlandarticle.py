import argparse
from typing import Optional, Dict, Any, List
import urllib3
import re
import hashlib
from tqdm import tqdm
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import urllib.parse
from bs4 import BeautifulSoup
import requests
import pandas as pd
import random
import time
import os


class ArticleScraper:
    def __init__(self, scan_mode="all", data_file="articles.xlsx", check_specific=True):
        """初始化爬蟲設定"""
        # 常量設定
        self.SETTINGS = {
            'BASE_URL': "https://real-estate.get.com.tw/Columns/",
            'TARGET_AUTHORS': ["曾榮耀", "許文昌", "蘇偉強"],
            'PNO_VALUES': ["51120", "51121"],  # 支持多個 pno
            'JOURNAL_PARAMS': {
                "no": "1282",
                "pno": "51121"  # 預設 pno
            },
            'PERFORMANCE': {
                'BATCH_SIZE': 50,
                'MAX_WORKERS': 4,
                'MAX_RETRIES': 5,
                'RETRY_DELAY': 3,
                'REQUEST_INTERVAL': 1.5
            },
            'ARTICLE_RANGES': [
                {
                    "start": 914900,
                    "end": 915000,
                    "description": "近期文章範圍"
                }
            ],
            'BUFFER_SIZE': 500  # 新增：文章編號範圍緩衝區大小
        }

        # 基本設定
        self.base_url = self.SETTINGS['BASE_URL']
        self.detail_url = f"{self.base_url}detail.aspx"
        self.journal_url = f"{self.base_url}journal.aspx"
        self.target_authors = self.SETTINGS['TARGET_AUTHORS']
        self.pno_values = self.SETTINGS['PNO_VALUES']
        self.scan_mode = scan_mode
        self.data_file = Path(data_file)
        self.check_specific = check_specific
        self.buffer_size = self.SETTINGS['BUFFER_SIZE']

        # 期刊參數設定
        self.journal_params = self.SETTINGS['JOURNAL_PARAMS']

        # 時間範圍設定
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=9*365)

        # 效能設定
        self.batch_size = self.SETTINGS['PERFORMANCE']['BATCH_SIZE']
        self.max_workers = self.SETTINGS['PERFORMANCE']['MAX_WORKERS']
        self.max_retries = self.SETTINGS['PERFORMANCE']['MAX_RETRIES']
        self.retry_delay = self.SETTINGS['PERFORMANCE']['RETRY_DELAY']
        self.request_interval = self.SETTINGS['PERFORMANCE']['REQUEST_INTERVAL']

        # 文章編號範圍設定
        self.article_ranges = self.SETTINGS['ARTICLE_RANGES']

        # 最新文章編號緩存
        self.latest_article_number = None

        # 初始化其他組件
        self.setup_directories()
        self.setup_session()
        self.setup_logger()
        self.processed_articles = set()
        self.load_processed_articles()
        self.last_request_time = 0

        # 記錄掃描設定到日誌
        self.logger.info(f"初始化更新模式: {scan_mode}, 檢查特定文章: {check_specific}")
        for range_info in self.article_ranges:
            self.logger.info(
                f"設定文章範圍: {range_info['description']} - "
                f"從 {range_info['start']} 到 {range_info['end']}"
            )

    def setup_directories(self):
        """建立必要的目錄結構"""
        self.base_dir = Path("real_estate_articles")
        self.articles_dir = self.base_dir / "articles"
        self.images_dir = self.articles_dir / "images"
        self.logs_dir = self.base_dir / "logs"

        for directory in [self.base_dir, self.articles_dir, self.images_dir, self.logs_dir]:
            directory.mkdir(parents=True, exist_ok=True)

        # 創建預設的失敗圖片
        self.failed_image_path = self.images_dir / "image_download_failed.png"
        if not self.failed_image_path.exists():
            try:
                from PIL import Image, ImageDraw
                img = Image.new('RGB', (400, 100), color='white')
                d = ImageDraw.Draw(img)
                d.text((10, 40), "Image Download Failed", fill='black')
                img.save(self.failed_image_path)
            except Exception:
                self.failed_image_path.touch()

    def setup_session(self):
        """設定請求session"""
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })

    def setup_logger(self):
        """設定日誌系統"""
        self.logger = logging.getLogger('ArticleScraper')
        self.logger.handlers = []
        self.logger.setLevel(logging.INFO)

        log_file = self.logs_dir / \
            f"scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        handlers = [
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]

        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s')
        for handler in handlers:
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def load_processed_articles(self):
        """載入已處理的文章"""
        if self.data_file.exists():
            df = pd.read_excel(self.data_file)
            if '文章編號' in df.columns:
                self.processed_articles = set(df['文章編號'].astype(str))

    def load_specific_articles(self):
        """載入特定文章清單"""
        specific_file = self.base_dir / "specific_articles.txt"
        if specific_file.exists():
            with open(specific_file, 'r') as f:
                return [int(line.strip()) for line in f if line.strip().isdigit()]
        return [913706, 913623, 913646]

    def wait_between_requests(self):
        """控制請求間隔"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if elapsed < self.request_interval:
            time.sleep(self.request_interval -
                       elapsed + random.uniform(0, 0.5))
        self.last_request_time = current_time

    def get_max_page_number(self) -> int:
        """獲取期刊最大頁數"""
        max_page = 1
        for pno in self.pno_values:
            params = {"no": "1282", "pno": pno}
            try:
                self.wait_between_requests()
                response = self.session.get(
                    self.journal_url, params=params, timeout=30, verify=False)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                pagination = soup.select('.pagination a')
                if pagination:
                    page_numbers = [int(a.text.strip())
                                    for a in pagination if a.text.strip().isdigit()]
                    max_page = max(max_page, max(page_numbers)
                                   if page_numbers else 1)
                self.logger.info(f"pno={pno} 檢測到最大頁數: {max_page}")
            except Exception as e:
                self.logger.error(f"獲取 pno={pno} 最大頁數失敗: {str(e)}")
        self.logger.info(f"最終最大頁數: {max_page}")
        return max_page

    def get_article_urls_from_journal(self, page_no: int) -> List[int]:
        """從期刊頁面獲取文章編號列表"""
        articles = []
        for pno in self.pno_values:
            params = {"no": "1282", "pno": pno, "page_no": page_no}
            try:
                self.wait_between_requests()
                response = self.session.get(
                    self.journal_url, params=params, timeout=30, verify=False)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                for link in soup.select('a[href*="detail.aspx?no="]'):
                    try:
                        href = link.get('href', '')
                        if match := re.search(r'no=(\d+)', href):
                            article_no = int(match.group(1))
                            if str(article_no) not in self.processed_articles:
                                articles.append(article_no)
                    except ValueError:
                        continue
                self.logger.info(
                    f"pno={pno} 第 {page_no} 頁找到 {len(articles)} 篇新文章: {articles}")
            except Exception as e:
                self.logger.error(
                    f"獲取 pno={pno} 第 {page_no} 頁文章列表失敗: {str(e)}")
        if articles:
            self.logger.info(
                f"第 {page_no} 頁共找到 {len(articles)} 篇新文章: {articles}")
        else:
            self.logger.info(f"第 {page_no} 頁沒有新文章")
        return articles

    def fetch_article(self, article_no: int) -> Optional[Dict]:
        """抓取單篇文章"""
        if str(article_no) in self.processed_articles:
            self.logger.debug(f"文章 {article_no} 已處理過，跳過")
            return None
        invalid_file = self.base_dir / "invalid_articles.txt"
        invalid_articles = set()
        if invalid_file.exists():
            with open(invalid_file, 'r') as f:
                invalid_articles = set(line.strip() for line in f)
        if str(article_no) in invalid_articles:
            self.logger.debug(f"文章 {article_no} 已知無效，跳過")
            return None
        for retry in range(self.max_retries):
            try:
                self.wait_between_requests()
                url = f"{self.detail_url}?no={article_no}"
                self.logger.info(f"開始請求文章 URL: {url}")
                response = self.session.get(url, timeout=30, verify=False)
                self.logger.info(
                    f"文章 {article_no} 請求狀態碼: {response.status_code}")
                if response.status_code == 404:
                    self.logger.error(f"文章 {article_no} 不存在 (404)")
                    with open(invalid_file, 'a') as f:
                        f.write(f"{article_no}\n")
                    return None
                response.raise_for_status()
                response.encoding = 'utf-8'
                content_length = len(response.text)
                self.logger.info(f"文章 {article_no} 響應內容長度: {content_length}")
                if content_length < 500:
                    self.logger.error(f"文章 {article_no} 響應內容過短，可能是無效頁面")
                    self.logger.debug(f"響應內容樣本: {response.text[:100]}")
                    with open(invalid_file, 'a') as f:
                        f.write(f"{article_no}\n")
                    return None
                debug_file = self.logs_dir / \
                    f"article_{article_no}_response.html"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                self.logger.info(f"已保存文章 {article_no} 的原始響應到: {debug_file}")
                soup = BeautifulSoup(response.text, 'html.parser')
                if not soup.select('.columnsDetail_tableRow'):
                    self.logger.error(
                        f"文章 {article_no} 頁面結構不符合預期，未找到 .columnsDetail_tableRow")
                    self.logger.debug(f"響應內容樣本: {response.text[:100]}")
                    with open(invalid_file, 'a') as f:
                        f.write(f"{article_no}\n")
                    return None
                article_data = self.parse_article(soup, article_no)
                if article_data and self.validate_article(article_data):
                    self.logger.info(f"文章 {article_no} 解析成功")
                    return article_data
                else:
                    self.logger.error(f"文章 {article_no} 解析失敗或不符合條件")
                    return None
            except requests.exceptions.RequestException as e:
                self.logger.error(
                    f"抓取文章 {article_no} 失敗 (嘗試 {retry + 1}/{self.max_retries}): {str(e)}")
                if hasattr(e, 'response') and hasattr(e.response, 'text'):
                    self.logger.error(f"錯誤回應內容: {e.response.text[:200]}")
                if retry < self.max_retries - 1:
                    wait_time = self.retry_delay * (retry + 1)
                    self.logger.info(f"等待 {wait_time} 秒後重試...")
                    time.sleep(wait_time)
                continue
            except Exception as e:
                self.logger.error(f"處理文章 {article_no} 時發生未預期錯誤: {str(e)}")
                import traceback
                self.logger.error(f"錯誤堆疊: {traceback.format_exc()}")
                if retry < self.max_retries - 1:
                    wait_time = self.retry_delay * (retry + 1)
                    self.logger.info(f"等待 {wait_time} 秒後重試...")
                    time.sleep(wait_time)
                continue
        self.logger.error(f"文章 {article_no} 重試 {self.max_retries} 次後仍失敗")
        return None

    def check_specific_article(self, article_no: int):
        """檢查特定文章"""
        if str(article_no) in self.processed_articles:
            self.logger.info(f"特定文章 {article_no} 已處理，跳過檢查")
            return
        self.logger.info(f"開始檢查特定文章: {article_no}")
        try:
            url = f"{self.detail_url}?no={article_no}"
            self.logger.info(f"請求 URL: {url}")
            response = self.session.get(url, timeout=30, verify=False)
            self.logger.info(f"文章 {article_no} 請求狀態碼: {response.status_code}")
            debug_file = self.logs_dir / f"debug_article_{article_no}.html"
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(response.text)
            self.logger.info(f"已保存原始 HTML 到: {debug_file}")
            soup = BeautifulSoup(response.text, 'html.parser')
            meta_tags = soup.find_all('meta')
            meta_info = {}
            for tag in meta_tags:
                name = tag.get('name', '')
                content = tag.get('content', '')
                if name and content:
                    meta_info[name] = content
            self.logger.info(f"頁面 meta 信息: {meta_info}")
            meta_author = soup.select_one('meta[name="citation_author"]')
            if meta_author:
                author = meta_author.get('content', '')
                self.logger.info(f"Meta 標籤中的作者: {author}")
                author_match = any(
                    target in author for target in self.target_authors)
                if not author_match:
                    self.logger.warning(f"作者不在目標列表中: {author}")
            result = self.fetch_article(article_no)
            if result:
                self.logger.info(f"文章 {article_no} 抓取成功，開始保存")
                self.save_article(result)
                self.create_index()
                self.logger.info(f"成功抓取並保存文章 {article_no}")
            else:
                self.logger.error(f"無法抓取文章 {article_no}")
        except Exception as e:
            self.logger.error(f"檢查文章 {article_no} 時發生錯誤: {str(e)}")
            import traceback
            self.logger.error(f"錯誤堆疊: {traceback.format_exc()}")

    def parse_article(self, soup: BeautifulSoup, article_no: int) -> Optional[Dict]:
        """解析文章內容"""
        try:
            article_info = {}
            found_fields = 0
            # 優先從 meta 標籤獲取資訊
            meta_author = soup.select_one('meta[name="citation_author"]')
            meta_title = soup.select_one('meta[name="citation_title"]')
            meta_date = soup.select_one('meta[name="citation_publication_date"]')
            if meta_author and meta_title and meta_date:
                self.logger.info(f"從 meta 標籤找到文章資訊")
                article_info['作者'] = meta_author.get('content', '').strip()
                article_info['標題'] = meta_title.get('content', '').strip()
                article_info['日期'] = meta_date.get('content', '').strip()
                found_fields += 3
            # 從表格中提取資訊
            rows = soup.select('.columnsDetail_tableRow')
            self.logger.info(f"文章 {article_no} 找到 {len(rows)} 個資料列")
            for row in rows:
                th = row.select_one('.columnsDetail_tableth')
                td = row.select_one('.columnsDetail_tabletd')
                if th and td:
                    key = th.text.strip()
                    value = td.text.strip()
                    self.logger.debug(
                        f"文章 {article_no} 欄位: {key} = {value[:50]}...")
                    if key == '篇名':
                        article_info['標題'] = value
                        found_fields += 1
                    elif key == '作者':
                        article_info['作者'] = value
                        found_fields += 1
                    elif key == '日期':
                        article_info['日期'] = value
                        found_fields += 1
                    elif key == '內文':
                        article_info['內文HTML'] = str(td)
                        found_fields += 1
                    elif key == '關鍵詞':  # 新增關鍵詞提取
                        article_info['關鍵詞'] = value
                        found_fields += 1
            self.logger.info(f"文章 {article_no} 成功解析 {found_fields} 個欄位")
            # 如果不是目標作者，直接返回
            author = article_info.get('作者')
            if not author or not any(target in author for target in self.target_authors):
                self.logger.warning(f"文章 {article_no} 作者不符合目標: {author}")
                return None
            # 檢查日期範圍
            if '日期' in article_info:
                try:
                    article_date = pd.to_datetime(article_info['日期'])
                    if not (self.start_date <= article_date <= self.end_date):
                        self.logger.warning(
                            f"文章 {article_no} 日期 {article_info['日期']} 不在範圍內")
                        return None
                except ValueError:
                    self.logger.error(
                        f"文章 {article_no} 日期格式無效: {article_info['日期']}")
                    return None
            # 處理內文
            if '內文HTML' not in article_info:
                content_div = soup.select_one('.columnsDetail_tabletd#SearchItem')
                if content_div:
                    article_info['內文HTML'] = str(content_div)
                    self.logger.info("從頁面中提取內文 HTML")
            content = self.process_content(
                article_info.get('內文HTML', ''), article_no)
            if not content:
                self.logger.error(f"文章 {article_no} 內文處理後為空")
                return None
            article_data = {
                '文章編號': article_no,
                '標題': article_info.get('標題', ''),
                '作者': article_info.get('作者', ''),
                '日期': article_info.get('日期', ''),
                '內文': content,
                'URL': f"{self.detail_url}?no={article_no}",
                '爬取時間': datetime.now().strftime("%Y-%m-d %H:%M:%S")
            }
            # 添加關鍵詞到文章數據中
            if '關鍵詞' in article_info:
                article_data['關鍵詞'] = article_info.get('關鍵詞', '')
            return article_data
        except Exception as e:
            self.logger.error(f"解析文章 {article_no} 失敗: {str(e)}")
            import traceback
            self.logger.error(f"錯誤堆疊: {traceback.format_exc()}")
            return None


    def download_image(self, img_url: str, article_no: int) -> Optional[str]:
        """下載圖片並返回本地檔名"""
        try:
            if not img_url.startswith(('http://', 'https://')):
                img_url = urllib.parse.urljoin(self.base_url, img_url)
            url_hash = hashlib.md5(img_url.encode()).hexdigest()[:8]
            file_ext = os.path.splitext(img_url)[1] or '.jpg'
            local_filename = f"{article_no}_{url_hash}{file_ext}"
            local_path = self.images_dir / local_filename
            if local_path.exists():
                return local_filename
            self.wait_between_requests()
            response = self.session.get(img_url, timeout=30, verify=False)
            response.raise_for_status()
            with open(local_path, 'wb') as f:
                f.write(response.content)
            return local_filename
        except Exception as e:
            self.logger.error(f"下載圖片失敗 ({img_url}): {str(e)}")
            return None

    def process_content(self, html_content: str, article_no: int) -> str:
        """處理文章內容，包括下載圖片和清理HTML，並保留表格格式"""
        if not html_content:
            return ""

        soup = BeautifulSoup(html_content, 'html.parser')

        # 處理圖片
        image_references = []
        for index, img in enumerate(soup.find_all('img'), 1):
            img_url = img.get('src', '')
            if img_url:
                local_filename = self.download_image(img_url, article_no)
                if local_filename:
                    image_references.append(
                        f"\n![圖片{index}](./images/{local_filename})\n")
                    img.replace_with(f"[圖片{index}]")
                else:
                    img.replace_with("[圖片下載失敗]")

        # 處理表格
        tables = soup.find_all('table')
        table_placeholders = {}
        for i, table in enumerate(tables, 1):
            md_table = self._html_table_to_markdown(table)
            placeholder = f"TABLE_PLACEHOLDER_{i}"
            table_placeholders[placeholder] = md_table
            table.replace_with(f"{placeholder}")

        # 處理其他內容
        content = self._format_content(soup)

        # 替換表格佔位符
        for placeholder, md_table in table_placeholders.items():
            content = content.replace(placeholder, f"\n\n{md_table}\n\n")

        # 添加圖片
        if image_references:
            content += "\n\n## 文章圖片\n" + "".join(image_references)

        return content

    def _html_table_to_markdown(self, table) -> str:
        """將 HTML 表格轉換為 Markdown 表格，並處理長文本換行"""
        try:
            # 收集所有表格數據
            headers = []
            data_rows = []

            # 尋找表頭行
            thead = table.find('thead')
            if thead:
                header_row = thead.find('tr')
                if header_row:
                    headers = [th.get_text().strip()
                            for th in header_row.find_all(['th', 'td'])]

            # 如果沒有找到表頭，嘗試從第一行獲取
            if not headers and table.find('tr'):
                first_row = table.find('tr')
                if first_row.find('th'):
                    headers = [th.get_text().strip()
                            for th in first_row.find_all('th')]
                else:
                    headers = [td.get_text().strip()
                            for td in first_row.find_all('td')]
                    # 如果使用第一行作為表頭，從數據行中移除
                    data_rows = []

            # 收集數據行
            for tr in table.find_all('tr'):
                # 跳過已處理的表頭行
                if tr == table.find('tr') and not thead and headers == [td.get_text().strip() for td in tr.find_all('td')]:
                    continue

                row_data = []
                for td in tr.find_all(['td', 'th']):
                    # 處理合併單元格
                    colspan = int(td.get('colspan', 1))
                    cell_text = td.get_text().strip()
                    cell_text = re.sub(r'\s+', ' ', cell_text)
                    
                    # 處理長文本自動換行
                    cell_text = self._wrap_text(cell_text, 25)

                    # 添加單元格文本
                    row_data.append(cell_text)

                    # 如果有合併單元格，添加額外的空單元格
                    for _ in range(colspan - 1):
                        row_data.append('')

                if row_data and not (len(row_data) == len(headers) and all(cell == '' for cell in row_data)):
                    data_rows.append(row_data)

            # 如果仍然沒有表頭，創建默認表頭
            if not headers:
                max_cols = max(len(row)
                            for row in data_rows) if data_rows else 0
                headers = [f"欄位 {i+1}" for i in range(max_cols)]

            # 確保所有數據行的列數與表頭一致
            for i in range(len(data_rows)):
                while len(data_rows[i]) < len(headers):
                    data_rows[i].append('')
                # 截斷過長的行
                data_rows[i] = data_rows[i][:len(headers)]

            # 生成 Markdown 表格
            md_table = []

            # 添加表頭
            md_table.append('| ' + ' | '.join(headers) + ' |')

            # 添加分隔行
            md_table.append('| ' + ' | '.join(['---' for _ in headers]) + ' |')

            # 添加數據行
            for row in data_rows:
                md_table.append('| ' + ' | '.join(row) + ' |')

            return '\n'.join(md_table)
        except Exception as e:
            self.logger.error(f"轉換表格失敗: {str(e)}")
            import traceback
            self.logger.error(f"錯誤堆疊: {traceback.format_exc()}")
            return "*表格轉換失敗*"

    def _wrap_text(self, text, max_width=30):
        """智能地將文本按照自然斷句點換行"""
        if len(text) <= max_width:
            return text
            
        # 嘗試在標點符號處換行
        punctuation = ['.', '，', '。', '；', '：', '、', '!', '?', '；', '：']
        wrapped_text = []
        current_chunk = ""
        
        for char in text:
            current_chunk += char
            
            # 如果當前塊達到最大寬度，尋找合適的換行點
            if len(current_chunk) >= max_width:
                # 尋找最後的標點符號位置
                last_punct = -1
                for p in punctuation:
                    pos = current_chunk.rfind(p)
                    if pos > last_punct:
                        last_punct = pos
                
                # 如果找到標點符號且不是在開頭，則在標點後換行
                if last_punct > 0 and last_punct < len(current_chunk) - 1:
                    wrapped_text.append(current_chunk[:last_punct+1])
                    current_chunk = current_chunk[last_punct+1:]
                else:
                    # 如果沒有找到合適的標點，則直接在最大寬度處換行
                    wrapped_text.append(current_chunk)
                    current_chunk = ""
        
        # 添加剩餘的文本
        if current_chunk:
            wrapped_text.append(current_chunk)
            
        return "<br>".join(wrapped_text)

    def _format_content(self, soup: BeautifulSoup) -> str:
        """格式化文章內容，處理換行和縮排，並自動處理列表項目"""
        allowed_tags = {'p', 'br', 'h1', 'h2', 'h3',
                        'h4', 'h5', 'h6', 'ul', 'ol', 'li'}
        for tag in soup.find_all():
            if tag.name not in allowed_tags:
                tag.unwrap()

        # 處理段落和標題
        for p in soup.find_all('p'):
            text = p.get_text().strip()
            if text:
                p.string = ' '.join(text.split())
                p.append('\n\n')

        for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            level = int(h.name[1])
            prefix = '#' * level + ' '
            h.string = f'\n{prefix}{h.get_text().strip()}\n'

        # 處理已有的列表
        for li in soup.find_all('li'):
            indent = '  '
            if li.parent.name == 'ol':
                index = len(li.find_previous_siblings('li')) + 1
                li.insert(0, f'{indent}{index}. ')
            else:
                li.insert(0, f'{indent}• ')
            li.append('\n')

        # 獲取基本文本內容
        content = soup.get_text()

        # 自動檢測和處理未標記的列表項目
        lines = content.split('\n')
        processed_lines = []

        list_patterns = [
            # 數字列表: 1. 2. 3.
            (r'^(\d+)\.(.+)$', lambda m: f"  {m.group(1)}. {m.group(2).strip()}"),
            # 中文數字列表: 一、二、三、
            (r'^([一二三四五六七八九十百千]+)、(.+)$',
            lambda m: f"  • {m.group(1)}、{m.group(2).strip()}"),
            # 帶括號的數字: (1) (2) (3)
            (r'^\((\d+)\)(.+)$',
            lambda m: f"  • ({m.group(1)}) {m.group(2).strip()}"),
            # 帶括號的中文數字: (一) (二) (三)
            (r'^\(([一二三四五六七八九十百千]+)\)(.+)$',
            lambda m: f"  • ({m.group(1)}) {m.group(2).strip()}"),
            # 英文字母列表: A. B. C. 或 A B C
            (r'^([A-Za-z])\.?(.+)$',
            lambda m: f"  • {m.group(1)}. {m.group(2).strip()}")
        ]

        for line in lines:
            line = line.strip()
            if not line:
                processed_lines.append('')
                continue

            # 檢查是否匹配任何列表模式
            matched = False
            for pattern, replacement in list_patterns:
                if re.match(pattern, line):
                    processed_line = re.sub(pattern, replacement, line)
                    processed_lines.append(processed_line)
                    matched = True
                    break

            # 如果沒有匹配任何列表模式，保持原樣
            if not matched:
                processed_lines.append(line)

        # 合併處理後的行
        content = '\n'.join(processed_lines)

        # 清理多餘的空白和換行
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r'[ \t]+', ' ', content)
        content = re.sub(r' *\n *', '\n', content)

        # 將內容分段並重新組合
        paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
        formatted_content = '\n\n'.join(paragraphs)

        return formatted_content.strip()


    def validate_article(self, article_data: Dict) -> bool:
        """驗證文章資料完整性"""
        required_fields = ['標題', '作者', '日期', '內文']
        return all(field in article_data and article_data[field] for field in required_fields)


    def save_article(self, article_data: Dict) -> None:
        """儲存文章"""
        try:
            new_df = pd.DataFrame([article_data])
            if self.data_file.exists():
                df = pd.read_excel(self.data_file)
                df = pd.concat([df, new_df]).drop_duplicates(subset=['文章編號'])
            else:
                df = new_df
            df.to_excel(self.data_file, index=False)
            article_no = article_data['文章編號']
            title = re.sub(r'[<>:"/\\|?*]', '', article_data['標題'])[:100]

            # 添加關鍵詞部分
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
            file_path = self.articles_dir / f"{article_no}_{title}.md"
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            self.processed_articles.add(str(article_no))
            self.logger.info(f"文章 {article_no} 已保存到 {file_path}")
        except Exception as e:
            self.logger.error(f"儲存文章 {article_data.get('文章編號')} 失敗: {str(e)}")

    def reprocess_articles(self, article_numbers=None):
        """重新處理已爬取的文章，修復表格格式並添加關鍵詞"""
        self.logger.info("開始重新處理已爬取文章的表格格式和關鍵詞")

        try:
            if not self.data_file.exists():
                self.logger.error("未找到 articles.xlsx，無法重新處理文章")
                return

            df = pd.read_excel(self.data_file)
            if '文章編號' not in df.columns:
                self.logger.error("文章資料中缺少文章編號欄位")
                return

            # 如果指定了文章編號，確保它們是字符串類型
            if article_numbers is not None:
                article_numbers = [str(num) for num in article_numbers]
            # 如果沒有指定文章編號，處理所有已爬取的文章
            else:
                article_numbers = df['文章編號'].astype(str).tolist()

            self.logger.info(f"將重新處理 {len(article_numbers)} 篇文章")

            success_count = 0
            fail_count = 0

            for article_no in tqdm(article_numbers, desc="重新處理文章"):
                try:
                    # 檢查文章檔案是否存在
                    article_files = list(
                        self.articles_dir.glob(f"{article_no}_*.md"))
                    if not article_files:
                        self.logger.warning(f"找不到文章 {article_no} 的檔案")
                        fail_count += 1
                        continue

                    article_file = article_files[0]

                    # 讀取原始 HTML 檔案
                    html_file = self.logs_dir / \
                        f"article_{article_no}_response.html"

                    # 如果找不到原始 HTML 檔案，嘗試重新爬取
                    if not html_file.exists():
                        self.logger.info(f"找不到文章 {article_no} 的原始 HTML 檔案，嘗試重新爬取")
                        try:
                            self.wait_between_requests()
                            url = f"{self.detail_url}?no={article_no}"
                            response = self.session.get(
                                url, timeout=30, verify=False)
                            response.raise_for_status()
                            response.encoding = 'utf-8'

                            # 保存重新爬取的 HTML
                            with open(html_file, 'w', encoding='utf-8') as f:
                                f.write(response.text)
                            self.logger.info(f"成功重新爬取文章 {article_no} 的 HTML")
                        except Exception as e:
                            self.logger.error(f"重新爬取文章 {article_no} 失敗: {str(e)}")
                            fail_count += 1
                            continue

                    # 讀取 HTML 內容
                    with open(html_file, 'r', encoding='utf-8') as f:
                        html_content = f.read()

                    # 解析 HTML 並提取內文
                    soup = BeautifulSoup(html_content, 'html.parser')
                    content_div = None

                    # 查找內文區域
                    for row in soup.select('.columnsDetail_tableRow'):
                        th = row.select_one('.columnsDetail_tableth')
                        td = row.select_one('.columnsDetail_tabletd')
                        if th and td and th.text.strip() == '內文':
                            content_div = td
                            break

                    if not content_div:
                        content_div = soup.select_one(
                            '.columnsDetail_tabletd#SearchItem')

                    if not content_div:
                        self.logger.warning(f"文章 {article_no} 找不到內文區域")
                        fail_count += 1
                        continue

                    # 提取關鍵詞
                    keywords = None
                    for row in soup.select('.columnsDetail_tableRow'):
                        th = row.select_one('.columnsDetail_tableth')
                        td = row.select_one('.columnsDetail_tabletd')
                        if th and td and th.text.strip() == '關鍵詞':
                            keywords = td.text.strip()
                            self.logger.info(
                                f"從文章 {article_no} 中提取到關鍵詞: {keywords}")
                            break

                    # 重新處理內文，特別是表格
                    new_content = self.process_content(
                        str(content_div), article_no)

                    # 讀取原始 Markdown 檔案
                    with open(article_file, 'r', encoding='utf-8') as f:
                        markdown_content = f.read()

                    # 找到內文部分並替換
                    content_pattern = re.compile(
                        r'## 內文\n(.*?)(?=\n---|\n## 文章圖片|\Z)', re.DOTALL)
                    match = content_pattern.search(markdown_content)

                    if match:
                        updated_markdown = markdown_content.replace(
                            match.group(0),
                            f"## 內文\n{new_content}"
                        )

                        # 添加關鍵詞（如果有）
                        if keywords:
                            # 檢查 Markdown 是否已經有關鍵詞部分
                            if '- 關鍵詞：' not in updated_markdown:
                                # 在發布日期後添加關鍵詞
                                pattern = r'- 發布日期：(.*?)\n'
                                replacement = r'- 發布日期：\1\n- 關鍵詞：' + keywords + '\n'
                                updated_markdown = re.sub(
                                    pattern, replacement, updated_markdown)
                                self.logger.info(
                                    f"已添加關鍵詞到文章 {article_no} 的 Markdown 文件")
                            else:
                                # 更新已存在的關鍵詞
                                pattern = r'- 關鍵詞：(.*?)\n'
                                replacement = r'- 關鍵詞：' + keywords + '\n'
                                updated_markdown = re.sub(
                                    pattern, replacement, updated_markdown)
                                self.logger.info(f"已更新文章 {article_no} 的關鍵詞")

                        # 寫回檔案
                        with open(article_file, 'w', encoding='utf-8') as f:
                            f.write(updated_markdown)

                        # 更新 Excel 中的關鍵詞
                        if keywords and '關鍵詞' in df.columns:
                            df.loc[df['文章編號'].astype(
                                str) == article_no, '關鍵詞'] = keywords
                        elif keywords:
                            df.loc[df['文章編號'].astype(
                                str) == article_no, '關鍵詞'] = keywords

                        self.logger.info(f"成功更新文章 {article_no} 的表格格式和關鍵詞")
                        success_count += 1
                    else:
                        self.logger.warning(f"無法在文章 {article_no} 中找到內文部分")
                        fail_count += 1

                except Exception as e:
                    self.logger.error(f"重新處理文章 {article_no} 時發生錯誤: {str(e)}")
                    import traceback
                    self.logger.error(f"錯誤堆疊: {traceback.format_exc()}")
                    fail_count += 1

            # 保存更新後的 Excel 文件
            df.to_excel(self.data_file, index=False)
            self.logger.info(f"已更新 Excel 文件中的關鍵詞資訊")

            self.logger.info(f"重新處理完成：成功 {success_count} 篇，失敗 {fail_count} 篇")

        except Exception as e:
            self.logger.error(f"重新處理文章時發生未預期錯誤: {str(e)}")
            import traceback
            self.logger.error(f"錯誤堆疊: {traceback.format_exc()}")




    def create_index(self):
        """創建文章索引，整合原有目錄內容"""
        try:
            if not self.data_file.exists():
                self.logger.info("未找到 articles.xlsx，無法創建索引")
                return
            df = pd.read_excel(self.data_file)
            index_path = self.base_dir / "README.md"
            existing_content = []
            existing_articles = set()
            if index_path.exists():
                with open(index_path, 'r', encoding='utf-8') as f:
                    existing_content = f.read().splitlines()
                    for line in existing_content:
                        if match := re.search(r'/(\d+)_[^/]+\.md', line):
                            existing_articles.add(match.group(1))
            df['文章編號'] = df['文章編號'].astype(str)
            new_articles = df[~df['文章編號'].isin(existing_articles)]
            if new_articles.empty and existing_content:
                self.logger.info("沒有新文章需要添加到目錄")
                return
            index_content = []
            for line in existing_content:
                if line.startswith('## '):
                    break
                index_content.append(line)
            if not index_content:
                index_content = ["# 文章目錄", ""]
            all_articles = pd.concat([
                df[df['文章編號'].isin(existing_articles)],
                new_articles
            ]).drop_duplicates(subset=['文章編號'])
            all_articles['日期'] = pd.to_datetime(all_articles['日期'])
            all_articles = all_articles.sort_values(
                ['作者', '日期'], ascending=[True, False])
            for author in sorted(all_articles['作者'].unique()):
                index_content.append(f"## {author}")
                author_articles = all_articles[all_articles['作者'] == author]
                for year in sorted(author_articles['日期'].dt.year.unique(), reverse=True):
                    index_content.append(f"\n### {year}年")
                    year_articles = author_articles[all_articles['日期'].dt.year == year]
                    for _, article in year_articles.iterrows():
                        title = re.sub(r'[<>:"/\\|?*]', '',
                                       article['標題'])[:100]
                        file_name = f"{article['文章編號']}_{title}.md"
                        date_str = article['日期'].strftime('%Y-%m-%d')
                        index_content.append(
                            f"- {date_str} [{article['標題']}](./articles/{file_name})")
                index_content.append("")
            with open(index_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(index_content))
            self.logger.info(f"已成功更新文章目錄，新增 {len(new_articles)} 篇文章")
        except Exception as e:
            self.logger.error(f"更新目錄失敗: {str(e)}")

    def _get_latest_article_number(self) -> Optional[int]:
        """獲取最新的文章編號，並緩存結果"""
        if self.latest_article_number is not None:
            return self.latest_article_number

        try:
            # 從第一頁獲取文章編號
            page_articles = self.get_article_urls_from_journal(1)
            if page_articles:
                self.latest_article_number = max(page_articles)
                self.logger.info(f"檢測到最新文章編號: {self.latest_article_number}")
                return self.latest_article_number

            # 如果第一頁沒有找到文章，嘗試檢查已處理的文章
            if self.processed_articles:
                try:
                    processed_numbers = [int(no)
                                         for no in self.processed_articles]
                    latest = max(processed_numbers)
                    self.logger.info(f"從已處理文章中獲取最新編號: {latest}")
                    self.latest_article_number = latest
                    return latest
                except (ValueError, TypeError):
                    pass

            # 如果都沒有找到，返回配置中的最大值
            max_end = max(range_info['end']
                          for range_info in self.article_ranges)
            self.logger.info(f"使用配置中的最大編號: {max_end}")
            return max_end
        except Exception as e:
            self.logger.error(f"獲取最新文章編號失敗: {str(e)}")
            return None

    def _update_article_ranges(self):
        """根據最新文章編號更新文章範圍"""
        latest_no = self._get_latest_article_number()
        if not latest_no:
            self.logger.warning("無法獲取最新文章編號，使用原有範圍")
            return

        # 更新每個範圍的結束編號
        for range_info in self.article_ranges:
            if latest_no > range_info['end']:
                old_end = range_info['end']
                range_info['end'] = latest_no + self.buffer_size
                self.logger.info(
                    f"更新文章範圍 '{range_info['description']}' 結束編號: "
                    f"{old_end} -> {range_info['end']} (增加緩衝區 {self.buffer_size})"
                )

    def run(self):
        """執行文章更新"""
        self.logger.info(f"開始執行爬蟲 (模式: {self.scan_mode})")
        success_count = 0
        fail_count = 0
        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = []
                article_numbers = set()

                # 先獲取最新文章編號並更新範圍
                self._update_article_ranges()

                if self.scan_mode == "recent":
                    page_articles = self.get_article_urls_from_journal(1)
                    article_numbers.update(page_articles)
                    self.logger.info(f"近期模式：第一頁找到 {len(page_articles)} 篇新文章")

                    if page_articles:
                        min_article = min(page_articles)
                        max_article = max(page_articles)
                        self.logger.info(
                            f"期刊頁面文章範圍: {min_article} 到 {max_article}")

                        # 使用動態上限，加上緩衝區
                        latest_end = max_article + self.buffer_size
                        self.logger.info(
                            f"設定動態上限: {latest_end} (原始最大值 {max_article} + 緩衝區 {self.buffer_size})")
                        article_numbers.update(
                            range(max(min_article, self.article_ranges[0]['start']), latest_end + 1))
                else:
                    max_page = self.get_max_page_number()
                    for page_no in range(1, max_page + 1):
                        page_articles = self.get_article_urls_from_journal(
                            page_no)
                        article_numbers.update(page_articles)
                        if not page_articles and page_no > 10:
                            self.logger.info(f"第 {page_no} 頁沒有新文章，停止檢查")
                            break

                    # 使用更新後的文章範圍
                    for range_info in self.article_ranges:
                        self.logger.info(
                            f"處理文章範圍: {range_info['description']} - "
                            f"從 {range_info['start']} 到 {range_info['end']}"
                        )
                        for article_no in range(range_info['start'], range_info['end'] + 1, self.batch_size):
                            batch = range(article_no, min(
                                article_no + self.batch_size, range_info['end'] + 1))
                            article_numbers.update(
                                [no for no in batch if str(no) not in self.processed_articles])

                self.logger.info(
                    f"共找到 {len(article_numbers)} 篇新文章: {sorted(list(article_numbers))[:20]}...")
                for article_no in article_numbers:
                    if str(article_no) not in self.processed_articles:
                        futures.append(executor.submit(
                            self.fetch_article, article_no))

                with tqdm(total=len(futures), desc="處理文章") as pbar:
                    for future in futures:
                        try:
                            result = future.result()
                            if result:
                                self.save_article(result)
                                success_count += 1
                            else:
                                fail_count += 1
                            pbar.update(1)
                        except Exception as e:
                            self.logger.error(f"處理文章結果失敗: {str(e)}")
                            fail_count += 1
                            pbar.update(1)
        finally:
            self.logger.info(f"更新完成：成功 {success_count} 篇，失敗 {fail_count} 篇")
            if success_count > 0:
                self.create_index()
            self.logger.info("程式結束執行")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Article Scraper for real-estate.get.com.tw")
    parser.add_argument('--scan_mode', type=str, default='all',
                        choices=['all', 'recent'], help="Scan mode: 'all' or 'recent'")
    parser.add_argument('--check_specific', type=lambda x: (str(x).lower() ==
                        'true'), default=True, help="Check specific articles: True or False")
    parser.add_argument('--buffer_size', type=int, default=500,
                        help="Buffer size for article number range")
    parser.add_argument('--reprocess', action='store_true',
                        help="Reprocess existing articles to fix table formatting")
    parser.add_argument('--article_numbers', type=str, default=None,
                        help="Comma-separated list of article numbers to reprocess")
    args = parser.parse_args()

    scraper = ArticleScraper(scan_mode=args.scan_mode,
                             check_specific=args.check_specific)
    if args.buffer_size:
        scraper.buffer_size = args.buffer_size

    if args.reprocess:
        article_numbers = None
        if args.article_numbers:
            article_numbers = [num.strip()
                               for num in args.article_numbers.split(',')]
        scraper.reprocess_articles(article_numbers)
    else:
        if scraper.check_specific:
            specific_articles = scraper.load_specific_articles()
            for article_no in specific_articles:
                scraper.check_specific_article(article_no)
        scraper.run()





'''
# 近期模式，檢查特定文章，使用預設緩衝區大小(500)
python getlandarticle.py --scan_mode recent --check_specific True

# 完整模式，檢查特定文章，使用預設緩衝區大小(500)
python getlandarticle.py --scan_mode all --check_specific True

# 近期模式，檢查特定文章，使用自訂緩衝區大小(1000)
python getlandarticle.py --scan_mode recent --check_specific True --buffer_size 1000

使用以下命令重新處理所有已爬取的文章：
python getlandarticle.py --reprocess

或者指定特定文章編號進行重新處理：
python getlandarticle.py --reprocess --article_numbers 912898


'''
