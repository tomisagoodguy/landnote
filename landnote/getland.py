import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib.parse
import re
import time
import os
import logging
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Iterator
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from tqdm import tqdm


class RecentArticleScraper:
    def __init__(self, scan_mode: str = "all"):
        """初始化爬蟲設定
        
        Args:
            scan_mode: 掃描模式 ("all", "new", "old")
        """
        # 基本設定
        self.base_url = "https://real-estate.get.com.tw/Columns/detail.aspx?no="
        self.target_authors = ["曾榮耀", "許文昌", "蘇偉強"]

        # 時間範圍設定（近五年）
        self.end_date = datetime.now()
        self.start_date = self.end_date - timedelta(days=5*365)

        # 日期格式設定
        self.date_formats = [
            "%Y/%m/%d",
            "%Y-%m-%d",
            "%Y年%m月%d日"
        ]

        # 文章編號範圍設定
        self.start_no = 900000  # 起始編號
        self.max_no = 915000    # 最大編號

        # 最新已知文章編號列表（用於參考）
        self.known_article_numbers = [
            913331,  # 2025/01/23 國土計畫法
            913325,  # 2025/01/21 都市計畫訴訟
            913285,  # 2025/01/14 承攬人抵押權
            913274,  # 2025/01/09 公路法
            913286,  # 2025/01/16 借名契約
            913225,  # 2025/01/02 憲判字第20號
            910390   # 2024/01/23 太陽光電
        ]

        # 掃描設定
        self.scan_mode = scan_mode
        self.batch_size = 50    # 每批次處理的文章數
        self.max_workers = 4    # 最大執行緒數

        # 建立目錄結構
        self.setup_directories()

        # 設定請求Session
        self.setup_session()

        # 設定日誌
        self.setup_logger()

        # 載入已處理的文章
        self.processed_articles = set()
        self.load_processed_articles()

        # 進度條設定
        self.pbar = None

    def setup_directories(self):
        """建立必要的目錄結構"""
        self.base_dir = Path("real_estate_articles")
        self.articles_dir = self.base_dir / "articles"
        self.images_dir = self.articles_dir / "images"
        self.logs_dir = self.base_dir / "logs"

        # 建立所需目錄
        for directory in [self.base_dir, self.articles_dir, self.images_dir, self.logs_dir]:
            directory.mkdir(parents=True, exist_ok=True)

        # 設定檔案路徑
        self.index_file = self.articles_dir / "index.md"
        self.data_file = self.base_dir / "articles.xlsx"

        # 確保索引文件存在
        if not self.index_file.exists():
            with open(self.index_file, 'w', encoding='utf-8') as f:
                f.write("# 文章索引\n\n")

    def setup_session(self):
        """設定請求session並加入錯誤重試機制"""
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
            'Referer': 'https://real-estate.get.com.tw/'
        }
        self.session.headers.update(self.headers)

        # 重試機制設定
        self.max_retries = 3
        self.retry_delay = 5

    def setup_logger(self):
        """設定日誌系統"""
        self.logger = logging.getLogger('RecentArticleScraper')
        self.logger.setLevel(logging.INFO)

        # 建立檔案處理器
        log_file = self.logs_dir / \
            f"scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)

        # 建立控制台處理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 設定格式
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # 添加處理器
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def load_processed_articles(self):
        """載入已處理的文章記錄"""
        try:
            if self.data_file.exists():
                df = pd.read_excel(self.data_file)
                if '文章編號' in df.columns:
                    self.processed_articles = set(
                        df['文章編號'].astype(str).tolist())
                    self.logger.info(
                        f"已載入 {len(self.processed_articles)} 篇已處理文章記錄")
        except Exception as e:
            self.logger.error(f"載入已處理文章記錄時發生錯誤: {str(e)}")
            self.processed_articles = set()

    def parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期字串
        
        Args:
            date_str: 日期字串，格式如 "2025/01/23"
        
        Returns:
            datetime 物件或 None（如果解析失敗）
        """
        try:
            for date_format in self.date_formats:
                try:
                    return datetime.strptime(date_str.strip(), date_format)
                except ValueError:
                    continue
            return None
        except Exception as e:
            self.logger.error(f"解析日期 '{date_str}' 時發生錯誤: {str(e)}")
            return None

    def is_recent_date(self, date: datetime) -> bool:
        """檢查日期是否在指定範圍內
        
        Args:
            date: 要檢查的日期
        
        Returns:
            bool: 是否在範圍內
        """
        return self.start_date <= date <= self.end_date

    def get_latest_article_number(self) -> int:
        """獲取最新文章編號"""
        try:
            if self.data_file.exists():
                df = pd.read_excel(self.data_file)
                if not df.empty and '文章編號' in df.columns:
                    return max(df['文章編號'].astype(int))
            return max(self.known_article_numbers)
        except Exception as e:
            self.logger.error(f"獲取最新文章編號時發生錯誤: {str(e)}")
            return max(self.known_article_numbers)

    def validate_article_info(self, article_info: Dict[str, Any]) -> bool:
        """驗證文章資訊是否完整
        
        Args:
            article_info: 文章資訊字典
        
        Returns:
            bool: 是否通過驗證
        """
        required_fields = ['篇名', '作者', '日期', '內文']
        return all(field in article_info for field in required_fields)

    def fetch_article(self, article_no: int) -> Optional[Dict[str, Any]]:
        """抓取單篇文章
        
        Args:
            article_no: 文章編號
        
        Returns:
            文章資料字典或 None（如果抓取失敗）
        """
        if str(article_no) in self.processed_articles:
            return None

        retries = 0
        while retries < self.max_retries:
            try:
                url = f"{self.base_url}{article_no}"
                response = self.session.get(url, timeout=30)
                response.encoding = 'utf-8'

                if response.status_code != 200:
                    return None

                soup = BeautifulSoup(response.text, 'html.parser')

                # 檢查文章是否存在
                if not soup.select('.columnsDetail_tableRow'):
                    return None

                article_info = {}

                # 解析文章資訊
                for row in soup.select('.columnsDetail_tableRow'):
                    th = row.select_one('.columnsDetail_tableth')
                    td = row.select_one('.columnsDetail_tabletd')
                    if th and td:
                        key = th.text.strip()
                        value = td.text.strip()

                        if key == '日期':
                            parsed_date = self.parse_date(value)
                            if not parsed_date or not self.is_recent_date(parsed_date):
                                return None

                        article_info[key] = value

                        if key == '內文':
                            article_info['內文HTML'] = td

                # 驗證必要欄位
                if not self.validate_article_info(article_info):
                    return None

                # 檢查作者
                if not any(author in article_info.get('作者', '') for author in self.target_authors):
                    return None

                # 處理內文
                processed_content = self.process_content(
                    article_info.get('內文HTML'), article_no)

                article_data = {
                    '文章編號': article_no,
                    '標題': article_info.get('篇名', ''),
                    '作者': article_info.get('作者', ''),
                    '日期': article_info.get('日期', ''),
                    '關鍵詞': article_info.get('關鍵詞', ''),
                    '內文': processed_content,
                    'URL': url,
                    '爬取時間': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

                return article_data

            except requests.exceptions.RequestException as e:
                retries += 1
                if retries < self.max_retries:
                    time.sleep(self.retry_delay)
            except Exception as e:
                self.logger.error(f"處理文章 {article_no} 時發生錯誤: {str(e)}")
                return None

        return None

    def process_content(self, content_html: BeautifulSoup, article_no: int) -> str:
        """處理文章內容
        
        Args:
            content_html: BeautifulSoup物件
            article_no: 文章編號
        
        Returns:
            處理後的文章內容
        """
        if not content_html:
            return ""

        content = []
        try:
            for element in content_html.descendants:
                if isinstance(element, str):
                    text = element.strip()
                    if text and not any(parent.name in ['style', 'script'] for parent in element.parents):
                        content.append(text)

                elif element.name == 'img':
                    img_src = element.get('src')
                    if img_src:
                        local_filename = self.download_image(
                            img_src, article_no)
                        if local_filename:
                            content.append(
                                f"\n![圖片](./images/{local_filename})\n")

                elif element.name in ['p', 'div', 'br']:
                    content.append('\n')

            return '\n'.join(filter(None, content))
        except Exception as e:
            self.logger.error(f"處理文章 {article_no} 內文時發生錯誤: {str(e)}")
            return ""

    def download_image(self, img_url: str, article_no: int) -> Optional[str]:
        """下載圖片
        
        Args:
            img_url: 圖片URL
            article_no: 文章編號
        
        Returns:
            本地圖片檔名或 None（如果下載失敗）
        """
        try:
            if not img_url.startswith('http'):
                img_url = urllib.parse.urljoin(self.base_url, img_url)

            response = self.session.get(img_url, stream=True)
            response.raise_for_status()

            img_data = response.content
            img_hash = hashlib.md5(img_data).hexdigest()
            img_ext = os.path.splitext(urllib.parse.urlparse(img_url).path)[
                1] or '.jpg'
            local_filename = f"{article_no}_{img_hash}{img_ext}"
            local_path = self.images_dir / local_filename

            if not local_path.exists():
                with open(local_path, 'wb') as f:
                    f.write(img_data)

            return local_filename
        except Exception as e:
            self.logger.error(f"下載圖片失敗 {img_url}: {str(e)}")
            return None

    def save_article(self, article_data: Dict[str, Any]):
        """儲存文章
        
        Args:
            article_data: 文章資料字典
        """
        try:
            article_no = article_data['文章編號']
            title = re.sub(r'[<>:"/\\|?*]', '', article_data['標題'])[:100]

            # 生成Markdown內容
            markdown_content = f"""# {article_data['標題']}

## 文章資訊
- 文章編號：{article_no}
- 作者：{article_data['作者']}
- 發布日期：{article_data['日期']}
- 關鍵詞：{article_data['關鍵詞']}
- 爬取時間：{article_data['爬取時間']}
- 原文連結：[閱讀原文]({article_data['URL']})

## 內文
{article_data['內文']}

---
*注：本文圖片存放於 ./images/ 目錄下*
"""

            # 儲存文章
            file_path = self.articles_dir / f"{article_no}_{title}.md"
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)

            # 更新索引
            index_entry = f"- [{title}](./{article_no}_{title}.md) (文章編號: {article_no}, 作者: {
                article_data['作者']}, 日期: {article_data['日期']})"
            with open(self.index_file, 'a', encoding='utf-8') as f:
                f.write(index_entry + '\n')

            # 更新Excel資料庫
            new_df = pd.DataFrame([article_data])
            if self.data_file.exists():
                existing_df = pd.read_excel(self.data_file)
                combined_df = pd.concat([existing_df, new_df])
                combined_df = combined_df.drop_duplicates(
                    subset=['文章編號'], keep='last')
            else:
                combined_df = new_df

            combined_df = combined_df.sort_values('日期', ascending=False)
            combined_df.to_excel(self.data_file, index=False)

            # 更新已處理文章集合
            self.processed_articles.add(str(article_no))

            if self.pbar:
                self.pbar.update(1)

        except Exception as e:
            self.logger.error(f"儲存文章時發生錯誤: {str(e)}")

    def generate_article_numbers(self, start: int, end: int, direction: str = "forward") -> Iterator[int]:
        """生成文章編號序列
        
        Args:
            start: 起始編號
            end: 結束編號
            direction: 掃描方向 ("forward" 或 "backward")
        """
        if direction == "forward":
            return range(start, end + 1)
        else:
            return range(start, end - 1, -1)

    def process_batch(self, article_numbers: List[int]):
        """處理一批文章
        
        Args:
            article_numbers: 文章編號列表
        """
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_article = {
                executor.submit(self.fetch_article, article_no): article_no
                for article_no in article_numbers
            }

            for future in as_completed(future_to_article):
                article_no = future_to_article[future]
                try:
                    article_data = future.result()
                    if article_data:
                        self.save_article(article_data)
                except Exception as e:
                    self.logger.error(f"處理文章 {article_no} 時發生錯誤: {str(e)}")

    def scan_range(self, start_no: int, end_no: int, direction: str = "forward"):
        """掃描指定範圍的文章
        
        Args:
            start_no: 起始編號
            end_no: 結束編號
            direction: 掃描方向
        """
        article_numbers = list(
            self.generate_article_numbers(start_no, end_no, direction))
        total_articles = len(article_numbers)

        self.logger.info(f"開始掃描 {direction} 方向的文章 ({start_no} -> {end_no})")

        with tqdm(total=total_articles, desc=f"掃描{direction}方向") as self.pbar:
            for i in range(0, total_articles, self.batch_size):
                batch = article_numbers[i:i + self.batch_size]
                self.process_batch(batch)
                time.sleep(1)  # 批次間隔

    def run(self):
        """執行主要爬蟲流程"""
        self.logger.info(f"開始執行文章爬蟲程序 (模式: {self.scan_mode})")

        try:
            latest_no = self.get_latest_article_number()

            if self.scan_mode in ["all", "new"]:
                # 掃描新文章
                self.logger.info("開始掃描新文章...")
                self.scan_range(latest_no + 1, self.max_no, "forward")

            if self.scan_mode in ["all", "old"]:
                # 掃描舊文章
                self.logger.info("開始掃描舊文章...")
                self.scan_range(latest_no - 1, self.start_no, "backward")

            self.logger.info("完成文章掃描")

        except KeyboardInterrupt:
            self.logger.info("程式被使用者中斷")
        except Exception as e:
            self.logger.error(f"執行過程中發生錯誤: {str(e)}")
        finally:
            self.logger.info("程式結束執行")


if __name__ == "__main__":
    # 掃描所有文章（新舊都包含）
    scraper = RecentArticleScraper(scan_mode="all")
    scraper.run()
