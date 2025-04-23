import json
import requests
from bs4 import BeautifulSoup
import re
import time
import random
import os
from datetime import datetime
from collections import defaultdict
import markdown
from fpdf import FPDF
import textwrap
import logging
import sys
from fake_useragent import UserAgent
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 設置日誌
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class JasperRealEstateScraper:
    """爬取 Jasper 不動產網站文章的爬蟲類"""

    def __init__(self, base_url="https://www.jasper-realestate.com/posts/", output_dir="scraped_data", resume_file=None):
        """
        初始化爬蟲
        
        Args:
            base_url: 目標網站的基礎URL
            output_dir: 輸出數據的目錄
            resume_file: 如果要繼續上次的爬取，提供上次保存的文件路徑
        """
        self.base_url = base_url
        self.ua = UserAgent()
        self.output_dir = output_dir
        self.results = []
        self.current_page = 1
        self.scraped_urls = set()  # 用於追蹤已經爬取過的URL
        self.latest_article_date = 'N/A'  # 最新文章日期
        self.checkpoint_file = os.path.join(
            output_dir, "scraper_checkpoint.json")

        # 確保輸出目錄存在
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 如果提供了恢復文件，加載之前的結果
        if resume_file and os.path.exists(resume_file):
            self.load_previous_results(resume_file)

        # 如果存在檢查點文件，加載檢查點
        if os.path.exists(self.checkpoint_file):
            self.load_checkpoint()

    def load_previous_results(self, resume_file):
        """
        加載之前爬取的結果
        
        Args:
            resume_file: 之前保存的結果文件路徑
        """
        try:
            with open(resume_file, 'r', encoding='utf-8') as f:
                self.results = json.load(f)

            # 更新已爬取的URL集合
            for article in self.results:
                if 'link' in article and article['link'] != 'N/A':
                    self.scraped_urls.add(article['link'])

            print(f"已加載 {len(self.results)} 篇之前爬取的文章")
        except Exception as e:
            print(f"加載之前的結果時出錯: {str(e)}")
            self.results = []

    def save_checkpoint(self):
        """保存當前爬取的檢查點，包括當前頁碼、已爬取的URL和最新文章日期"""
        latest_date = 'N/A'
        if self.results:
            valid_dates = []
            for article in self.results:
                if article['date'] != 'N/A':
                    try:
                        date = datetime.strptime(article['date'], "%Y-%m-%d")
                        valid_dates.append(date)
                    except ValueError as e:
                        logger.warning(
                            f"無法解析檢查點中的日期: {article['date']}，錯誤: {str(e)}")
            if valid_dates:
                latest_date = max(valid_dates).strftime("%Y-%m-%d")

        checkpoint = {
            'current_page': self.current_page,
            'scraped_urls': list(self.scraped_urls),
            'latest_article_date': latest_date
        }

        with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=4)

        print(f"檢查點已保存至 {self.checkpoint_file}")

    def load_checkpoint(self):
        """加載之前保存的檢查點"""
        try:
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)

            self.current_page = checkpoint.get('current_page', 1)
            self.scraped_urls = set(checkpoint.get('scraped_urls', []))
            self.latest_article_date = checkpoint.get(
                'latest_article_date', 'N/A')

            print(
                f"已加載檢查點: 當前頁碼 {self.current_page}, 已爬取 {len(self.scraped_urls)} 個URL, 最新文章日期 {self.latest_article_date}")
        except Exception as e:
            print(f"加載檢查點時出錯: {str(e)}")

    def random_sleep(self, min_seconds=2, max_seconds=5):
        """
        隨機休息一段時間Avoid too fast requests
        
        Args:
            min_seconds: Minimum sleep seconds
            max_seconds: Maximum sleep seconds
        """
        sleep_time = random.uniform(min_seconds, max_seconds)
        print(f"休息 {sleep_time:.2f} 秒...")
        time.sleep(sleep_time)

    def get_page(self, url, max_retries=3, retry_delay=5):
        """
        獲取頁面內容，增加重試機制
        
        Args:
            url: 要獲取的頁面URL
            max_retries: 最大重試次數
            retry_delay: 重試間隔(秒)
        
        Returns:
            BeautifulSoup 對象
        """
        for attempt in range(max_retries):
            try:
                headers = {
                    "User-Agent": self.ua.random,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "zh-TW,zh;q=0.8,en-US;q=0.5,en;q=0.3",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Cache-Control": "max-age=0"
                }

                logger.info(f"嘗試獲取頁面 {url} (第 {attempt+1} 次嘗試)")

                session = requests.Session()
                adapter = requests.adapters.HTTPAdapter(max_retries=3)
                session.mount('https://', adapter)
                session.mount('http://', adapter)

                response = session.get(
                    url,
                    headers=headers,
                    timeout=30,
                    verify=False  # 禁用 SSL 驗證
                )

                response.encoding = 'utf-8'

                # 檢查是否是有效的HTML
                if 'text/html' in response.headers.get('Content-Type', ''):
                    soup = BeautifulSoup(response.text, 'html.parser')
                    # 檢查是否有基本的HTML結構
                    if soup.find('body'):
                        return soup
                    else:
                        logger.warning(f"獲取的頁面沒有body標籤，可能不是有效的HTML")
                else:
                    logger.warning(
                        f"獲取的內容不是HTML: {response.headers.get('Content-Type')}")

                # 如果代碼執行到這裡，表示獲取的頁面有問題，嘗試下一次
                logger.warning(f"獲取的頁面內容有問題，嘗試下一次")
                if attempt < max_retries - 1:
                    logger.info(f"等待 {retry_delay} 秒後重試...")
                    time.sleep(retry_delay)

            except requests.exceptions.RequestException as e:
                logger.error(f"獲取頁面時出錯: {url}, 錯誤: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"等待 {retry_delay} 秒後重試...")
                    time.sleep(retry_delay)
            except Exception as e:
                logger.error(f"獲取頁面時發生未知錯誤: {url}, 錯誤: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"等待 {retry_delay} 秒後重試...")
                    time.sleep(retry_delay)

        logger.error(f"已達最大重試次數，放棄獲取頁面: {url}")
        return None

    def log_invalid_date(self, date, article_title):
        """記錄無效日期到日誌文件"""
        log_file = os.path.join(self.output_dir, "invalid_dates.log")
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now()}: 無法解析日期 '{date}' 在文章 '{article_title}'\n")

    def extract_article_preview(self, article):
        """
        從文章預覽中提取信息
        
        Args:
            article: 包含文章預覽的 BeautifulSoup 對象
        
        Returns:
            包含文章預覽信息的字典
        """
        # 提取標題和連結
        title_elem = article.find('h3', class_='elementor-post__title')
        title = title_elem.find('a').text.strip(
        ) if title_elem and title_elem.find('a') else 'N/A'
        link = title_elem.find(
            'a')['href'] if title_elem and title_elem.find('a') else 'N/A'

        # 提取摘要和條文依據
        excerpt_elem = article.find('div', class_='elementor-post__excerpt')
        if excerpt_elem:
            paragraphs = excerpt_elem.find_all('p')
            excerpt = paragraphs[0].text.strip() if paragraphs else 'N/A'
            legal_basis = paragraphs[1].text.strip() if len(
                paragraphs) > 1 else 'N/A'
        else:
            excerpt, legal_basis = 'N/A', 'N/A'

        # 提取發布日期並標準化
        date_elem = article.find('span', class_='elementor-post-date')
        raw_date = date_elem.text.strip() if date_elem else 'N/A'
        date = 'N/A'
        if raw_date != 'N/A':
            try:
                # 嘗試解析 'YYYY 年 MM 月 DD 日' 格式
                parsed_date = datetime.strptime(
                    raw_date, "%Y 年 %m 月 %d 日")
                date = parsed_date.strftime("%Y-%m-%d")
            except ValueError:
                # 如果失敗，嘗試 '%Y-%m-%d' 格式
                try:
                    parsed_date = datetime.strptime(raw_date, "%Y-%m-%d")
                    date = parsed_date.strftime("%Y-%m-%d")
                except ValueError as e:
                    logger.warning(f"無法解析日期: {raw_date}，錯誤: {str(e)}")
                    self.log_invalid_date(raw_date, title)

        # 提取縮圖 URL
        thumbnail_elem = article.find(
            'div', class_='elementor-post__thumbnail')
        thumbnail_url = 'N/A'
        if thumbnail_elem:
            img = thumbnail_elem.find('img')
            # 優先從 data-lazy-src 提取，若無則從 src 提取
            thumbnail_url = img.get('data-lazy-src') or img.get('src') or 'N/A'
            # 清理 SVG 占位符
            if 'data:image/svg+xml' in thumbnail_url:
                thumbnail_url = img.get('data-lazy-src') or 'N/A'

        # 提取標籤
        badge_elem = article.find('div', class_='elementor-post__badge')
        badge = badge_elem.text.strip() if badge_elem else 'N/A'

        # 標準化法律依據格式
        legal_basis = self.standardize_legal_basis(legal_basis)

        # 添加爬取時間戳
        crawled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return {
            'title': title,
            'link': link,
            'excerpt': excerpt,
            'legal_basis': legal_basis,
            'date': date,
            'thumbnail_url': thumbnail_url,
            'badge': badge,
            'crawled_at': crawled_at
        }

    def standardize_legal_basis(self, legal_basis):
        """
        標準化法律依據格式，便於後續分組
        
        Args:
            legal_basis: 原始法律依據文本
        
        Returns:
            標準化後的法律依據
        """
        if legal_basis == 'N/A':
            return legal_basis

        # 移除"條布置據："前綴
        legal_basis = legal_basis.replace("條文依據：", "").strip()

        # 移除多餘的空白和換行符
        legal_basis = re.sub(r'\s+', ' ', legal_basis).strip()

        return legal_basis

    def extract_full_content(self, article_url):
        """
        從文章頁面提取完整內容
        
        Args:
            article_url: 文章頁面URL
        
        Returns:
            文章的完整內容
        """
        if article_url == 'N/A':
            return "無法獲取完整內容，鏈接不可用"

        try:
            print(f"正在抓取文章內容: {article_url}")
            article_soup = self.get_page(article_url)

            if not article_soup:
                return "無法獲取文章頁面"

            # 根據HTML結構，精確定位文章內容
            content_section = article_soup.find(
                'div', class_='elementor-widget-theme-post-content')

            if content_section:
                # 提取文章內容
                content_container = content_section.find(
                    'div', class_='elementor-widget-container')

                if content_container:
                    # 提取所有標題和段落
                    content_elements = content_container.find_all(
                        ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 'li'])

                    # 組織內容，保留標題層級結構
                    full_content = ""
                    for elem in content_elements:
                        # 檢查是否是延伸閱讀或免費諮詢部分
                        if elem.get_text().strip() in ["．延伸閱讀", "．免費諮詢", "延伸閱讀", "免費諮詢"]:
                            # 如果找到延伸閱讀或免費諮詢，則停止處理
                            break

                        if elem.name.startswith('h'):  # 如果是標題
                            full_content += f"\n\n## {elem.get_text().strip()}\n\n"
                        elif elem.name == 'p':  # 如果是段落
                            # 檢查段落是否為空
                            text = elem.get_text().strip()
                            if text:
                                full_content += f"{text}\n\n"
                        elif elem.name in ['ul', 'ol']:  # 如果是列表
                            for li in elem.find_all('li'):
                                full_content += f"- {li.get_text().strip()}\n"
                            full_content += "\n"
                        # 單獨的列表項
                        elif elem.name == 'li' and not elem.parent.name in ['ul', 'ol']:
                            full_content += f"- {elem.get_text().strip()}\n"

                    # 清理多餘的空行
                    full_content = re.sub(
                        r'\n{3,}', '\n\n', full_content).strip()
                else:
                    # 如果找不到特定容器，則獲取整個內容區域的文本
                    full_content = content_section.get_text(
                        separator="\n").strip()

                    # 移除延伸閱讀和免費諮詢部分
                    sections_to_remove = ["．延伸閱讀", "．免費諮詢", "延伸閱讀", "免費諮詢"]
                    for section in sections_to_remove:
                        if section in full_content:
                            full_content = full_content.split(section)[
                                0].strip()
            else:
                # 如果找不到主要內容區域，嘗試其他可能的選擇器
                full_content = "無法找到主要內容區域，嘗試其他方法..."

                # 嘗試查找任何可能包含文章內容的區域
                possible_content_areas = article_soup.find_all(
                    'div', class_=['elementor-widget-container', 'entry-content', 'post-content'])

                if possible_content_areas:
                    # 選擇最長的內容區域作為可能的文章內容
                    longest_content = ""
                    for area in possible_content_areas:
                        content = area.get_text(separator="\n").strip()
                        if len(content) > len(longest_content):
                            longest_content = content

                    # 移除延伸閱讀和免費諮詢部分
                    sections_to_remove = ["．延伸閱讀", "．免費諮詢", "延伸閱讀", "免費諮詢"]
                    for section in sections_to_remove:
                        if section in longest_content:
                            longest_content = longest_content.split(section)[
                                0].strip()

                    full_content = longest_content
                else:
                    full_content = "無法獲取文章內容"

            return full_content

        except Exception as e:
            return f"獲取內容時出錯: {str(e)}"

    def has_next_page(self, soup):
        """
        檢查是否有下一頁
        
        Args:
            soup: 當前頁面的 BeautifulSoup 對象
        
        Returns:
            布爾值，表示是否有下一頁
        """
        # 查找分頁導航元素
        pagination = soup.find('nav', class_='elementor-pagination')
        if not pagination:
            return False

        # 檢查是否有下一頁按鈕或連結
        current_page_links = pagination.find_all('a', class_='page-numbers')
        for link in current_page_links:
            # 檢查是否有"下一頁"按鈕或更高的頁碼
            if link.text.strip() == '下一頁' or link.text.strip() == '»' or (link.text.strip().isdigit() and int(link.text.strip()) > self.current_page):
                return True

        return False

    def get_next_page_url(self, soup):
        """
        獲取下一頁的URL
        
        Args:
            soup: 當前頁面的 BeautifulSoup 對象
        
        Returns:
            下一頁的URL，如果沒有下一頁則返回None
        """
        # 查找分頁導航元素
        pagination = soup.find('nav', class_='elementor-pagination')
        if not pagination:
            return None

        # 尋找"下一頁"按鈕
        next_page_link = pagination.find(
            'a', string=['下一頁', '»']) or pagination.find('a', class_='next')
        if next_page_link and 'href' in next_page_link.attrs:
            return next_page_link['href']

        # 如果沒有明確的"下一頁"按鈕，尋找比當前頁碼更高的頁碼連結
        page_links = pagination.find_all('a', class_='page-numbers')
        for link in page_links:
            if link.text.strip().isdigit() and int(link.text.strip()) > self.current_page:
                return link['href']

        return None

    def scrape_all_articles(self):
        """爬取所有文章"""
        # 如果之前有檢查點，從檢查點頁面開始
        if self.current_page > 1:
            current_url = f"{self.base_url}page/{self.current_page}/"
        else:
            current_url = self.base_url

        total_articles = len(self.results)

        try:
            while current_url:
                print(f"\n正在爬取第 {self.current_page} 頁: {current_url}")
                soup = self.get_page(current_url)

                if not soup:
                    print(f"無法獲取頁面: {current_url}")
                    break

                # 嘗試多種可能的文章選擇器
                articles = soup.find_all('article', class_='elementor-post')
                if not articles:
                    # 如果找不到，嘗試其他可能的選擇器
                    articles = soup.find_all('article')
                    if not articles:
                        # 嘗試使用更廣泛的選擇器
                        articles = soup.find_all(['div', 'section'], class_=lambda c: c and (
                            'post' in c.lower() or 'article' in c.lower()))
                        if not articles:
                            # 最後嘗試找到所有可能的文章容器
                            articles = soup.find_all(
                                ['div', 'section'], class_=lambda c: c and ('content' in c.lower()))

                if not articles:
                    # 如果仍然找不到，記錄HTML以便調試
                    debug_file = os.path.join(
                        self.output_dir, f"debug_page_{self.current_page}.html")
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        f.write(str(soup))
                    logger.warning(f"在頁面上找不到文章: {current_url}")
                    logger.info(f"已保存頁面HTML至 {debug_file} 以供調試")
                    break

                print(f"找到 {len(articles)} 篇文章")

                for index, article in enumerate(articles):
                    print(f"正在處理第 {self.current_page} 頁的第 {index+1} 篇文章...")

                    # 提取文章預覽信息
                    article_info = self.extract_article_preview(article)

                    # 檢查是否已經爬取過這篇文章
                    if article_info['link'] in self.scraped_urls:
                        print(f"已經爬取過文章: {article_info['title']}")
                        continue

                    # 將URL添加到已爬取集合中
                    if article_info['link'] != 'N/A':
                        self.scraped_urls.add(article_info['link'])

                    # 隨機休息，避免過快請求
                    self.random_sleep()

                    # 獲取完整內容
                    full_content = self.extract_full_content(
                        article_info['link'])

                    # 添加完整內容到文章信息中
                    article_info['full_content'] = full_content

                    # 添加到結果列表
                    self.results.append(article_info)

                    print(f"已抓取文章: {article_info['title']}")
                    total_articles += 1

                    # 每抓取5篇文章保存一次結果和檢查點，防止中途中斷丟失數據
                    if total_articles % 5 == 0:
                        self.save_results(
                            f"jasper_articles_partial_{total_articles}.json")
                        self.save_checkpoint()

                    # 隨機休息，避免過快請求
                    self.random_sleep()

                # 檢查是否有下一頁
                if self.has_next_page(soup):
                    next_page_url = self.get_next_page_url(soup)
                    if next_page_url:
                        current_url = next_page_url
                        self.current_page += 1
                        self.save_checkpoint()  # 保存檢查點
                        # 頁面之間的休息時間更長，避免被檢測
                        self.random_sleep(5, 10)
                    else:
                        print("找不到下一頁的URL")
                        break
                else:
                    print("沒有更多頁面")
                    break

        except KeyboardInterrupt:
            print("\n爬蟲被中斷，保存當前結果和檢查點...")
            self.save_results()
            self.save_checkpoint()
            print("您可以稍後使用相同的檢查點文件繼續爬取")
            return self.results
        except Exception as e:
            print(f"\n爬取過程中出錯: {str(e)}")
            print("保存當前結果和檢查點...")
            self.save_results()
            self.save_checkpoint()
            return self.results

        print(f"\n爬取完成，共獲取 {len(self.results)} 篇文章")
        # 移除檢查點文件，因為已經完成爬取
        if os.path.exists(self.checkpoint_file):
            os.remove(self.checkpoint_file)
            print("已移除檢查點文件")

        return self.results

    def save_results(self, filename=None):
        """
        保存爬取結果
        
        Args:
            filename: 保存的文件名，如果為None則自動生成
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"jasper_articles_{timestamp}.json"

        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=4)

        print(f"結果已保存至 {filepath}")
        return filepath

    def organize_articles_by_date_and_legal_basis(self):
        """
        將文章按照日期和法律依據組織
        
        Returns:
            組織後的文章字典
        """
        # 先按日期排序
        sorted_by_date = sorted(
            self.results, key=lambda x: x['date'] if x['date'] != 'N/A' else '0000-00-00', reverse=True)

        # 然後按法律依據分組
        grouped_by_legal_basis = defaultdict(list)

        for article in sorted_by_date:
            legal_basis = article['legal_basis']
            grouped_by_legal_basis[legal_basis].append(article)

        return grouped_by_legal_basis

    def group_articles_by_law_type(self):
        """
        將文章按法律類型（如民法、土地法等）分組，每個法律類型下按法律依據分組
        
        Returns:
            按法律類型和法律依據組織的文章字典
        """
        # 先按法律依據分組
        organized = self.organize_articles_by_date_and_legal_basis()

        # 定義法律類型關鍵詞（根據提供的法律依據清單）
        law_types = [
            '民法', '土地法', '土地稅法', '土地登記規則', '地籍測量實施規則',
            '公平交易法', '土地徵收條例', '經紀業管理條例', '遺產及贈與稅法',
            '不動產估價技術規則', '平均地權條例', '房屋稅條例', '所得稅法',
            '地政士法', '契稅條例', '公寓大廈管理條例', '消費者保護法',
            '都市計畫法', '大法官釋字', '民事訴訟法', '憲法', '遺贈法'
        ]

        # 初始化按法律類型分組的字典
        grouped_by_law_type = defaultdict(lambda: defaultdict(list))

        # 將文章分配到對應的法律類型
        for legal_basis, articles in organized.items():
            assigned = False
            for law_type in law_types:
                if law_type in legal_basis or legal_basis.startswith(law_type):
                    grouped_by_law_type[law_type][legal_basis] = articles
                    assigned = True
                    break
            if not assigned:
                # 如果不屬於任何已知法律類型，放入「其他」或「未分類」
                grouped_by_law_type['未分類文章'][legal_basis] = articles

        # 將「未分類文章」中的「N/A」移到「未分類文章」類型
        if 'N/A' in organized:
            grouped_by_law_type['未分類文章']['N/A'] = organized['N/A']

        return grouped_by_law_type

    def save_organized_results(self):
        """保存按日期和法律依據組織的結果"""
        organized = self.organize_articles_by_date_and_legal_basis()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"jasper_articles_organized_{timestamp}.json"
        filepath = os.path.join(self.output_dir, filename)

        # 將defaultdict轉換為普通dict以便JSON序列化
        organized_dict = {k: v for k, v in organized.items()}

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(organized_dict, f, ensure_ascii=False, indent=4)

        print(f"組織後的結果已保存至 {filepath}")

        # 生成一個摘要文件，顯示每個法律依據下有多少篇文章
        summary_filename = f"jasper_articles_summary_{timestamp}.txt"
        summary_filepath = os.path.join(self.output_dir, summary_filename)

        with open(summary_filepath, 'w', encoding='utf-8') as f:
            f.write("法律依據分類摘要：\n\n")
            for legal_basis, articles in organized.items():
                f.write(f"{legal_basis}: {len(articles)} 篇文章\n")
                for article in articles:
                    f.write(f"  - {article['date']} | {article['title']}\n")
                f.write("\n")

        print(f"摘要已保存至 {summary_filepath}")
        return summary_filepath

    def generate_readme(self):
        """生成README.md文件，總結所有爬取的文章"""
        organized = self.organize_articles_by_date_and_legal_basis()

        readme_content = "# Jasper 不動產文章集合\n\n"
        readme_content += f"爬取日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        readme_content += f"共爬取 {len(self.results)} 篇文章\n\n"

        # 添加目錄
        readme_content += "## 目錄\n\n"
        for legal_basis in sorted(organized.keys()):
            # 創建一個錨點，用於目錄跳轉
            anchor = legal_basis.replace(
                " ", "-").replace(":", "").replace("、", "").replace("§", "section")
            if legal_basis == "N/A":
                anchor = "未分類文章"
            readme_content += f"- [{legal_basis} ({len(organized[legal_basis])}篇)](#{anchor})\n"

        readme_content += "\n## 文章分類\n\n"

        # 按法律依據分組添加文章
        for legal_basis in sorted(organized.keys()):
            anchor = legal_basis.replace(
                " ", "-").replace(":", "").replace("、", "").replace("§", "section")
            if legal_basis == "N/A":
                anchor = "未分類文章"
                readme_content += f"### 未分類文章 ({len(organized[legal_basis])}篇) <a id='{anchor}'></a>\n\n"
            else:
                readme_content += f"### {legal_basis} ({len(organized[legal_basis])}篇) <a id='{anchor}'></a>\n\n"

            # 添加該分類下的所有文章
            for article in organized[legal_basis]:
                readme_content += f"#### {article['title']}\n\n"
                readme_content += f"- 發布日期: {article['date']}\n"
                readme_content += f"- 摘要: {article['excerpt']}\n"
                if article['link'] != 'N/A':
                    readme_content += f"- [原文連結]({article['link']})\n"
                readme_content += "\n"

                # 添加文章預覽（僅顯示前300個字符）
                if article['full_content'] and article['full_content'] != "無法獲取文章內容":
                    preview = article['full_content'][:300] + "..." if len(
                        article['full_content']) > 300 else article['full_content']
                    readme_content += f"**內容預覽:**\n\n{preview}\n\n"

                readme_content += "---\n\n"

        # 保存README.md
        readme_path = os.path.join(self.output_dir, "README.md")
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(readme_content)

        print(f"README.md 已生成至 {readme_path}")

        return readme_path

    def generate_text_files(self):
        """生成文本文件作為PDF的替代"""
        organized = self.organize_articles_by_date_and_legal_basis()
        text_dir = os.path.join(self.output_dir, "text_articles")
        if not os.path.exists(text_dir):
            os.makedirs(text_dir)

        # 生成總目錄
        index_text_path = os.path.join(text_dir, "00_總目錄.txt")
        with open(index_text_path, 'w', encoding='utf-8') as f:
            f.write("Jasper 不動產文章集合\n\n")
            f.write(f"爬取日期: {datetime.now().strftime('%Y-%m-%d')}\n\n")
            f.write(f"共爬取 {len(self.results)} 篇文章\n\n")
            f.write("目錄:\n\n")
            for i, (legal_basis, articles) in enumerate(sorted(organized.items())):
                basis_name = legal_basis if legal_basis != "N/A" else "未分類文章"
                f.write(f"{i+1}. {basis_name} ({len(articles)}篇)\n")

        # 生成各分類文本文件
        for legal_basis, articles in organized.items():
            basis_name = legal_basis if legal_basis != "N/A" else "未分類文章"
            safe_name = re.sub(r'[\\/*?:"<>|]', "_", basis_name)
            text_filename = f"{safe_name}_{len(articles)}篇.txt"
            text_path = os.path.join(text_dir, text_filename)
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write(f"{basis_name} 相關文章\n")
                f.write(f"共 {len(articles)} 篇文章\n\n")
                for i, article in enumerate(articles):
                    f.write(f"{i+1}. {article['title']}\n")
                    f.write(f"發布日期: {article['date']}\n")
                    f.write(f"摘要: {article['excerpt']}\n")
                    f.write(f"爬取時間: {article.get('crawled_at', 'N/A')}\n")
                    if article['link'] != 'N/A':
                        f.write(f"原文連結: {article['link']}\n")
                    f.write("\n文章內容:\n")
                    f.write(article['full_content']
                            if article['full_content'] else "無法獲取文章內容")
                    f.write("\n\n" + "-" * 50 + "\n\n")
            logger.info(f"文本文件已保存至: {text_path}")

        logger.info(f"所有文本文件已保存至目錄: {text_dir}")
        return text_dir

    def generate_pdfs(self):
        """生成單一PDF文件，包含所有文章，按法律類型和法律依據分類整理，每篇文章從新頁開始，無原文連結，包含頁碼"""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.lib.units import inch

            # 嘗試註冊中文字體
            try:
                # 嘗試註冊微軟正黑體（Windows系統）
                pdfmetrics.registerFont(TTFont('MSGothic', 'msgothic.ttc'))
                chinese_font = 'MSGothic'
                logger.info("已註冊微軟正黑體字體")
            except:
                try:
                    # 嘗試註冊思源黑體（跨平台）
                    pdfmetrics.registerFont(
                        TTFont('NotoSansCJK', 'NotoSansCJK-Regular.ttc'))
                    chinese_font = 'NotoSansCJK'
                    logger.info("已註冊思源黑體字體")
                except:
                    # 如果都失敗，使用文本文件代替
                    logger.error("無法找到合適的中文字體，將生成文本文件代替PDF")
                    return self.generate_text_files()

            # 按法律類型和法律依據分組文章
            grouped_by_law_type = self.group_articles_by_law_type()
            pdf_dir = os.path.join(self.output_dir, "pdf_articles")
            if not os.path.exists(pdf_dir):
                os.makedirs(pdf_dir)

            # 創建樣式
            styles = getSampleStyleSheet()
            styles.add(ParagraphStyle(name='Chinese',
                                      fontName=chinese_font,
                                      fontSize=10,
                                      leading=12,
                                      wordWrap='CJK'))
            styles.add(ParagraphStyle(name='ChineseTitle',
                                      fontName=chinese_font,
                                      fontSize=14,
                                      leading=16,
                                      alignment=1))  # 居中
            styles.add(ParagraphStyle(name='ChineseLawType',
                                      fontName=chinese_font,
                                      fontSize=13,
                                      leading=15,
                                      spaceAfter=12))
            styles.add(ParagraphStyle(name='ChineseHeading',
                                      fontName=chinese_font,
                                      fontSize=12,
                                      leading=14))

            # 定義頁碼函數
            def add_page_number(canvas, doc):
                page_num = canvas.getPageNumber()
                canvas.setFont(chinese_font, 10)
                page_width = letter[0]  # 612 points
                text = str(page_num)
                text_width = canvas.stringWidth(text, chinese_font, 10)
                canvas.drawString(
                    (page_width - text_width) / 2, 0.5 * inch, text)

            # 生成單一PDF
            pdf_path = os.path.join(pdf_dir, "jasper_articles_combined.pdf")
            doc = SimpleDocTemplate(pdf_path, pagesize=letter)
            story = []

            # 添加封面
            story.append(Paragraph("Jasper 不動產文章集合", styles['ChineseTitle']))
            story.append(Spacer(1, 12))
            story.append(
                Paragraph(f"爬取日期: {datetime.now().strftime('%Y-%m-%d')}", styles['Chinese']))
            story.append(
                Paragraph(f"共爬取 {len(self.results)} 篇文章", styles['Chinese']))
            story.append(Spacer(1, 24))

            # 添加目錄
            story.append(Paragraph("目錄", styles['ChineseTitle']))
            story.append(Spacer(1, 12))
            for law_type, legal_bases in sorted(grouped_by_law_type.items()):
                total_articles = sum(len(articles)
                                     for articles in legal_bases.values())
                story.append(
                    Paragraph(f"{law_type} ({total_articles}篇)", styles['ChineseLawType']))
                for legal_basis, articles in sorted(legal_bases.items()):
                    basis_name = legal_basis if legal_basis != "N/A" else "未分類"
                    story.append(
                        Paragraph(f"  - {basis_name} ({len(articles)}篇)", styles['Chinese']))
                story.append(Spacer(1, 6))
            story.append(PageBreak())

            # 添加各法律類型和文章
            for i, (law_type, legal_bases) in enumerate(sorted(grouped_by_law_type.items())):
                total_articles = sum(len(articles)
                                     for articles in legal_bases.values())
                story.append(
                    Paragraph(f"{law_type} 相關文章", styles['ChineseLawType']))
                story.append(Spacer(1, 12))
                story.append(
                    Paragraph(f"共 {total_articles} 篇文章", styles['Chinese']))
                story.append(Spacer(1, 24))

                for legal_basis, articles in sorted(legal_bases.items()):
                    basis_name = legal_basis if legal_basis != "N/A" else "未分類"
                    story.append(
                        Paragraph(f"{basis_name} 相關文章", styles['ChineseHeading']))
                    story.append(Spacer(1, 12))
                    story.append(
                        Paragraph(f"共 {len(articles)} 篇文章", styles['Chinese']))
                    story.append(Spacer(1, 12))

                    for j, article in enumerate(articles):
                        if j > 0:
                            story.append(PageBreak())  # 每篇文章從新頁開始（除了第一篇）
                        story.append(
                            Paragraph(f"{j+1}. {article['title']}", styles['Chinese']))
                        story.append(Spacer(1, 6))
                        story.append(
                            Paragraph(f"發布日期: {article['date']}", styles['Chinese']))
                        story.append(
                            Paragraph(f"摘要: {article['excerpt']}", styles['Chinese']))
                        story.append(Spacer(1, 12))

                        if article['full_content'] and article['full_content'] != "無法獲取文章內容":
                            content = re.sub(
                                r'##\s+', '', article['full_content'])
                            content = re.sub(r'\*\*|\*', '', content)
                            paragraphs = content.split('\n\n')
                            for para in paragraphs:
                                if para.strip():
                                    story.append(
                                        Paragraph(para.strip(), styles['Chinese']))
                                    story.append(Spacer(1, 6))

                    story.append(Spacer(1, 24))

                # 在每個法律類型後添加分頁（除了最後一個）
                if i < len(grouped_by_law_type) - 1:
                    story.append(PageBreak())

            # 應用頁碼
            doc.build(story, onFirstPage=add_page_number,
                      onLaterPages=add_page_number)
            logger.info(f"單一PDF已保存至: {pdf_path}")
            return pdf_dir

        except Exception as e:
            logger.error(f"生成PDF時出錯: {str(e)}")
            # 如果PDF生成失敗，則生成文本文件
            return self.generate_text_files()

    def generate_markdown_files(self):
        """生成Markdown文件，按法律依據分類整理文章"""
        organized = self.organize_articles_by_date_and_legal_basis()

        # 創建Markdown 輸出目錄
        md_dir = os.path.join(self.output_dir, "markdown_articles")
        if not os.path.exists(md_dir):
            os.makedirs(md_dir)

        # 創建一個總目錄文件
        index_md_path = os.path.join(md_dir, "00_總目錄.md")

        with open(index_md_path, 'w', encoding='utf-8') as f:
            f.write("# Jasper 不動產文章集合\n\n")
            f.write(f"爬取日期: {datetime.now().strftime('%Y-%m-%d')}\n\n")
            f.write(f"共爬取 {len(self.results)} 篇文章\n\n")

            # 添加目錄
            f.write("## 目錄\n\n")

            for i, (legal_basis, articles) in enumerate(sorted(organized.items())):
                basis_name = legal_basis if legal_basis != "N/A" else "未分類文章"
                safe_name = re.sub(r'[\\/*?:"<>|]', "_",
                                   basis_name)  # 替換不安全的文件名字符
                md_filename = f"{i+1:02d}_{safe_name}_{len(articles)}篇.md"

                # 添加到目錄中
                f.write(
                    f"{i+1}. [{basis_name} ({len(articles)}篇)]({md_filename})\n")

        logger.info(f"總目錄Markdown已保存至: {index_md_path}")

        # 為每個法律依據創建一個Markdown文件
        for i, (legal_basis, articles) in enumerate(sorted(organized.items())):
            basis_name = legal_basis if legal_basis != "N/A" else "未分類文章"
            safe_name = re.sub(r'[\\/*?:"<>|]', "_", basis_name)  # 替換不安全的文件名字符
            md_filename = f"{i+1:02d}_{safe_name}_{len(articles)}篇.md"
            md_path = os.path.join(md_dir, md_filename)

            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(f"# {basis_name} 相關文章\n\n")
                f.write(f"共 {len(articles)} 篇文章\n\n")
                f.write(f"[返回總目錄](00_總目錄.md)\n\n")

                # 添加該分類下的所有文章
                for j, article in enumerate(articles):
                    f.write(f"## {j+1}. {article['title']}\n\n")
                    f.write(f"- 發布日期: {article['date']}\n")
                    f.write(f"- 摘要: {article['excerpt']}\n")
                    if article['link'] != 'N/A':
                        f.write(f"- [原文連結]({article['link']})\n")
                    f.write("\n### 文章內容:\n\n")

                    if article['full_content'] and article['full_content'] != "無法獲取文章內容":
                        f.write(article['full_content'])
                    else:
                        f.write("無法獲取文章內容")

                    f.write("\n\n---\n\n")

            logger.info(f"Markdown文件已保存至: {md_path}")

        # 創建一個合併所有文章的大Markdown文件
        all_articles_md_path = os.path.join(md_dir, "所有文章合集.md")

        with open(all_articles_md_path, 'w', encoding='utf-8') as f:
            f.write("# Jasper 不動產文章合集\n\n")
            f.write(f"爬取日期: {datetime.now().strftime('%Y-%m-%d')}\n\n")
            f.write(f"共爬取 {len(self.results)} 篇文章\n\n")
            f.write(f"[返回總目錄](00_總目錄.md)\n\n")

            # 按日期排序所有文章
            all_articles = sorted(
                self.results, key=lambda x: x['date'] if x['date'] != 'N/A' else '0000-00-00', reverse=True)

            # 添加所有文章
            for i, article in enumerate(all_articles):
                title = f"{article['title']}"
                if article['legal_basis'] != 'N/A':
                    title += f" ({article['legal_basis']})"

                f.write(f"## {i+1}. {title}\n\n")
                f.write(f"- 發布日期: {article['date']}\n")
                f.write(f"- 摘要: {article['excerpt']}\n")
                if article['link'] != 'N/A':
                    f.write(f"- [原文連結]({article['link']})\n")
                f.write("\n### 文章內容:\n\n")

                if article['full_content'] and article['full_content'] != "無法獲取文章內容":
                    f.write(article['full_content'])
                else:
                    f.write("無法獲取文章內容")

                f.write("\n\n---\n\n")

        logger.info(f"所有文章合集Markdown已保存至: {all_articles_md_path}")

        return md_dir


def check_for_updates(scraper):
    """檢查網站是否有新文章或內容更新"""
    print("正在檢查是否有新文章或內容更新...")

    # 獲取第一頁的文章
    first_page_url = scraper.base_url
    logger.info(f"檢查更新: {first_page_url}")
    first_page_soup = scraper.get_page(first_page_url)
    if not first_page_soup:
        print("無法獲取第一頁，跳過更新檢查")
        return False, []

    # 提取第一頁的文章
    articles = first_page_soup.find_all('article', class_='elementor-post')
    if not articles:
        articles = first_page_soup.find_all('article')

    # 儲存新文章的資訊
    new_articles = []
    has_updates = False

    # 獲取已爬取的最新文章日期
    latest_date = None
    if scraper.results:
        valid_dates = []
        for article in scraper.results:
            if article['date'] != 'N/A':
                try:
                    # 嘗試解析 '%Y-%m-%d' 格式
                    date = datetime.strptime(article['date'], "%Y-%m-%d")
                    valid_dates.append(date)
                except ValueError:
                    # 如果失敗，嘗試 'YYYY 年 MM 月 DD 日' 格式
                    try:
                        date = datetime.strptime(
                            article['date'], "%Y 年 %m 月 %d 日")
                        valid_dates.append(date)
                    except ValueError as e:
                        logger.warning(
                            f"無法解析文章日期: {article['date']}，錯誤: {str(e)}")
                        scraper.log_invalid_date(
                            article['date'], article['title'])
                        continue
        if valid_dates:
            latest_date = max(valid_dates)

    for article in articles[:5]:  # 只檢查最新的 5 篇文章
        article_info = scraper.extract_article_preview(article)
        if article_info['link'] != 'N/A' and article_info['link'] not in scraper.scraped_urls:
            # 檢查文章日期是否比已爬取的最新日期更新
            article_date = None
            if article_info['date'] != 'N/A':
                try:
                    # 日期已經在 extract_article_preview 中標準化為 '%Y-%m-%d'
                    article_date = datetime.strptime(
                        article_info['date'], "%Y-%m-%d")
                except ValueError as e:
                    logger.warning(
                        f"無法解析新文章日期: {article_info['date']}，錯誤: {str(e)}")
                    scraper.log_invalid_date(
                        article_info['date'], article_info['title'])
                    continue

            if latest_date is None or (article_date and article_date > latest_date):
                print(
                    f"發現新文章: {article_info['title']} ({article_info['date']})")
                has_updates = True
                new_articles.append(article_info)

    if not has_updates:
        print("沒有新文章或更新")

    return has_updates, new_articles


if __name__ == "__main__":
    # 檢查是否有之前的結果文件，如果有則提示用戶是否繼續
    output_dir = "scraped_data"
    checkpoint_file = os.path.join(output_dir, "scraper_checkpoint.json")

    # 確保輸出目錄存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    resume_file = None
    if os.path.exists(checkpoint_file):
        print("發現之前的爬取檢查點，是否要繼續上次的爬取？(y/n)")
        choice = input().lower()
        if choice == 'y':
            # 查找最新的部分結果文件
            partial_files = [f for f in os.listdir(
                output_dir) if f.startswith("jasper_articles_partial_")]
            if partial_files:
                latest_file = sorted(partial_files, key=lambda x: int(
                    x.split("_")[-1].split(".")[0]))[-1]
                resume_file = os.path.join(output_dir, latest_file)
                print(f"將繼續從 {resume_file} 開始爬取")

    # 選擇代理測試模式
    print("\n請選擇代理測試模式：")
    print("1. 快速模式 - 找到 3 個有效代理就開始爬取")
    print("2. 測試所有代理")
    print("3. 不使用代理，直接爬取")
    proxy_mode = input("請選擇 (1/2/3，預設為1): ").strip() or "1"

    # 選擇運行模式
    print("\n選擇運行模式：")
    print("1. 正常爬取")
    print("2. 調試模式 - 只爬取一頁並保存HTML")
    mode = input("請選擇 (1/2，預設為1): ").strip() or "1"

    debug_mode = (mode == "2")

    try:
        # 初始化爬蟲
        scraper = JasperRealEstateScraper(resume_file=resume_file)

        # 調試模式
        if debug_mode:
            print("進入調試模式，只爬取一頁並保存HTML...")
            url = scraper.base_url
            soup = scraper.get_page(url)
            if soup:
                debug_file = os.path.join(output_dir, "debug_page.html")
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(str(soup))
                print(f"已保存HTML至 {debug_file}")

                # 分析頁面結構
                print("\n分析頁面結構...")
                print(f"找到 {len(soup.find_all('article'))} 個 article 標籤")
                print(
                    f"找到 {len(soup.find_all('article', class_='elementor-post'))} 個 class 為 elementor-post 的 article 標籤")
                print(
                    f"找到 {len(soup.find_all('div', class_='elementor-posts-container'))} 個 class 為 elementor-posts-container 的 div 標籤")

                # 嘗試找出文章容器
                possible_containers = soup.find_all(['div', 'section'], class_=lambda c: c and (
                    'post' in c.lower() or 'article' in c.lower() or 'content' in c.lower()))
                print(f"找到 {len(possible_containers)} 個可能的文章容器")
                # 只顯示前5個
                for i, container in enumerate(possible_containers[:5]):
                    print(f"\n容器 {i+1}:")
                    print(f"標籤: {container.name}")
                    print(f"類名: {container.get('class')}")
                    print(f"ID: {container.get('id')}")
                    print(f"內容預覽: {container.get_text()[:100]}...")
            else:
                print("無法獲取頁面HTML")

            print("\n調試完成，退出程序")
            sys.exit(0)

        # 檢查是否有更新
        has_updates, new_articles = check_for_updates(scraper)

        if has_updates:
            print(f"發現 {len(new_articles)} 篇新文章，開始爬取新內容...")
            # 僅爬取新文章的完整內容
            for article_info in new_articles:
                if article_info['link'] != 'N/A':
                    scraper.scraped_urls.add(article_info['link'])
                    scraper.random_sleep()
                    full_content = scraper.extract_full_content(
                        article_info['link'])
                    article_info['full_content'] = full_content
                    scraper.results.append(article_info)
                    print(f"已抓取新文章: {article_info['title']}")

            # 如果有更多頁面，繼續爬取直到沒有新文章
            scraper.current_page = 1
            scraper.scrape_all_articles()  # 爬取剩餘的新文章（如果有）

            # 保存結果
            result_file = scraper.save_results()
            logger.info(f"結果已保存至 {result_file}")
        else:
            print("無需爬取新內容，使用現有數據生成文件...")

        # 按日期和法律依據組織結果
        summary_file = scraper.save_organized_results()
        logger.info(f"摘要已保存至 {summary_file}")

        # 生成README.md
        print("正在生成README.md...")
        readme_path = scraper.generate_readme()
        logger.info(f"README.md 已生成至 {readme_path}")
        print(f"README.md 已生成至 {readme_path}")

        # 生成Markdown文件
        print("正在生成Markdown文件...")
        md_dir = scraper.generate_markdown_files()
        print(f"Markdown文件已生成至 {md_dir}")

        # 生成PDF文件
        print("正在生成PDF文件...")
        try:
            pdf_dir = scraper.generate_pdfs()
            print(f"PDF文件已生成至 {pdf_dir}")
        except Exception as e:
            print(f"生成PDF時出錯: {str(e)}")
            text_dir = scraper.generate_text_files()
            print(f"已生成文本文件代替PDF，保存至 {text_dir}")

        print("\n所有任務完成！")

    except Exception as e:
        print(f"執行過程中出錯: {str(e)}")
        import traceback
        traceback.print_exc()



# python jasper.py