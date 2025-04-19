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
                    "start": 900000,
                    "end": 915000,
                    "description": "新年份範圍"
                },
                {
                    "start": 409187,
                    "end": 421516,
                    "description": "早期年份範圍"
                }
            ]
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
                    return None
                response.raise_for_status()
                response.encoding = 'utf-8'
                content_length = len(response.text)
                self.logger.info(f"文章 {article_no} 響應內容長度: {content_length}")
                if content_length < 100:
                    self.logger.error(f"文章 {article_no} 響應內容過短，可能是無效響應")
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
            meta_date = soup.select_one(
                'meta[name="citation_publication_date"]')
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
                content_div = soup.select_one(
                    '.columnsDetail_tabletd#SearchItem')
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
                '爬取時間': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
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
        """處理文章內容，包括下載圖片和清理HTML"""
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, 'html.parser')
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
        content = self._format_content(soup)
        if image_references:
            content += "\n\n## 文章圖片\n" + "".join(image_references)
        return content

    def _format_content(self, soup: BeautifulSoup) -> str:
        """格式化文章內容，處理換行和縮排"""
        allowed_tags = {'p', 'br', 'h1', 'h2', 'h3',
                        'h4', 'h5', 'h6', 'ul', 'ol', 'li'}
        for tag in soup.find_all():
            if tag.name not in allowed_tags:
                tag.unwrap()
        for p in soup.find_all('p'):
            text = p.get_text().strip()
            if text:
                p.string = ' '.join(text.split())
                p.append('\n\n')
        for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            level = int(h.name[1])
            prefix = '#' * level + ' '
            h.string = f'\n{prefix}{h.get_text().strip()}\n'
        for li in soup.find_all('li'):
            indent = '  '
            if li.parent.name == 'ol':
                index = len(li.find_previous_siblings('li')) + 1
                li.insert(0, f'{indent}{index}. ')
            else:
                li.insert(0, f'{indent}• ')
            li.append('\n')
        content = soup.get_text()
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r'[ \t]+', ' ', content)
        content = re.sub(r' *\n *', '\n', content)
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
            markdown_content = f"""# {article_data['標題']}

## 文章資訊
- 文章編號：{article_no}
- 作者：{article_data['作者']}
- 發布日期：{article_data['日期']}
- 爬取時間：{article_data['爬取時間']}
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

    def run(self):
        """執行文章更新"""
        self.logger.info(f"開始執行爬蟲 (模式: {self.scan_mode})")
        success_count = 0
        fail_count = 0
        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = []
                # 從期刊頁面獲取文章
                max_page = self.get_max_page_number()
                self.logger.info(f"檢測到期刊總頁數: {max_page}")
                article_numbers = set()
                for page_no in range(1, max_page + 1):
                    self.logger.info(f"正在檢查第 {page_no} 頁的文章列表")
                    page_articles = self.get_article_urls_from_journal(page_no)
                    article_numbers.update(page_articles)
                    if not page_articles and page_no > 10:
                        self.logger.info(f"第 {page_no} 頁沒有新文章，停止檢查")
                        break
                self.logger.info(
                    f"從期刊頁面共找到 {len(article_numbers)} 篇新文章: {sorted(list(article_numbers))}")
                # 如果是全量模式，掃描所有編號範圍
                if self.scan_mode == "all":
                    for range_info in self.article_ranges:
                        self.logger.info(
                            f"開始處理範圍 {range_info['start']} 到 {range_info['end']}")
                        for article_no in range(range_info['start'], range_info['end'] + 1, self.batch_size):
                            batch = range(article_no, min(
                                article_no + self.batch_size, range_info['end'] + 1))
                            article_numbers.update([
                                no for no in batch
                                if str(no) not in self.processed_articles
                            ])
                # 處理所有文章
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
    scraper = ArticleScraper(scan_mode="all", check_specific=True)
    if scraper.check_specific:
        specific_articles = [913706, 913623, 913646]  # 測試特定文章
        for article_no in specific_articles:
            scraper.check_specific_article(article_no)
    scraper.run()


# python getlandarticle.py --scan_mode all --check_specific True