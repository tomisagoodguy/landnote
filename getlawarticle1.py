import requests
from bs4 import BeautifulSoup
import os
import time
import re
import random
import pikepdf
import argparse
from collections import defaultdict
import pandas as pd
from tqdm import tqdm
import datetime
import logging
import sys
import json

# 配置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("crawler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("LawExamCrawler")


class PDFProcessor:
    """PDF處理類，負責PDF檔案的解鎖和儲存"""

    @staticmethod
    def unlock_pdf(input_path, output_path):
        """解除PDF檔案的保護，使其可編輯、複製等"""
        try:
            with pikepdf.open(input_path) as pdf:
                pdf.save(output_path)
            logger.info(f"已解鎖: {os.path.basename(output_path)}")
            return True
        except Exception as e:
            logger.error(f"解鎖失敗: {e}")
            return False


class ExamDocument:
    """考古題文件類，代表單一份考古題"""

    def __init__(self, index, exam_type, subject, year, download_url, download_params):
        self.index = index
        self.exam_type = exam_type
        self.subject = subject
        self.year = year
        self.download_url = download_url
        self.download_params = download_params
        self.filename = f"{year}年_{exam_type}_{subject}.pdf"
        self.filename = self.filename.replace('\r', '').replace('\n', '')

    def display_info(self):
        """顯示考古題資訊"""
        logger.info(f'編號: {self.index}')
        logger.info(f'類組: {self.exam_type}')
        logger.info(f'科目: {self.subject}')
        logger.info(f'年度: {self.year}')
        logger.info(f'連結: {self.download_url}')

    def to_dict(self):
        """將考古題資訊轉換為字典格式，方便儲存為JSON"""
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
        """從字典建立考古題物件"""
        return cls(
            data["index"],
            data["exam_type"],
            data["subject"],
            data["year"],
            data["download_url"],
            data["download_params"]
        )


class LawExamCrawler:
    """高點法律考古題爬蟲類"""

    def __init__(self, base_folder="./高點法律考古題", debug=False):
        self.base_url = "https://lawyer.get.com.tw/exam/List.aspx"
        self.download_base_url = "https://lawyer.get.com.tw/exam/Download.ashx"
        self.debug = debug  # 先設定 debug 屬性

        # 使用 fake_useragent 隨機生成 User-Agent
        try:
            self.ua = None
        except:
            self.ua = None

        # 初始化 headers
        self.update_headers()

        self.base_folder = base_folder
        self.debug = debug
        self.log_file = f"{base_folder}/download_log.txt"

        # 檢查點檔案路徑
        self.checkpoint_file = os.path.join(base_folder, "checkpoint.json")
        self.temp_exams_file = os.path.join(base_folder, "temp_exams.json")

        # 創建基礎資料夾
        if not os.path.exists(base_folder):
            os.makedirs(base_folder)

        # 初始化session以保持cookies
        self.session = requests.Session()

        # 設置延遲參數
        self.min_delay = 5.0  # 最小延遲秒數
        self.max_delay = 10.0  # 最大延遲秒數
        self.retry_delay = 30.0  # 遇到429錯誤時的等待時間
        self.consecutive_429_count = 0  # 連續429錯誤計數

        # 代理伺服器列表 (如果有的話)
        self.proxies = []
        self.current_proxy_index = 0

    def update_headers(self):
        """更新請求頭，使用隨機 User-Agent"""
        if self.ua:
            user_agent = self.ua.random
        else:
            # 預設 User-Agent 列表
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5.2 Safari/605.1.15",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            ]
            user_agent = random.choice(user_agents)

        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Referer": "https://lawyer.get.com.tw/exam/List.aspx",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }

        if self.debug:
            logger.info(f"使用 User-Agent: {user_agent}")

    def rotate_proxy(self):
        """輪換代理伺服器"""
        if not self.proxies:
            return None

        self.current_proxy_index = (
            self.current_proxy_index + 1) % len(self.proxies)
        proxy = self.proxies[self.current_proxy_index]

        if self.debug:
            logger.info(f"切換到代理: {proxy}")

        return {
            "http": proxy,
            "https": proxy
        }

    def handle_429_error(self):
        """處理429錯誤"""
        self.consecutive_429_count += 1

        # 根據連續429錯誤次數增加等待時間
        wait_time = self.retry_delay * \
            (2 ** min(self.consecutive_429_count - 1, 5))  # 指數退避，最多等待32倍初始時間

        logger.warning(f"檢測到429錯誤 (請求過多)，等待 {wait_time:.1f} 秒")

        # 更新 User-Agent
        self.update_headers()

        # 輪換代理 (如果有)
        self.rotate_proxy()

        # 等待一段時間
        time.sleep(wait_time)

    def get_page(self, page_no=None, max_retries=3):
        """獲取頁面內容"""
        params = {}
        if page_no:
            params["iPageNo"] = page_no

        for retry in range(max_retries):
            try:
                # 使用session保持cookies
                proxies = self.rotate_proxy()

                response = self.session.get(
                    self.base_url,
                    headers=self.headers,
                    params=params,
                    timeout=30,
                    proxies=proxies
                )

                # 檢查響應狀態
                if response.status_code == 429:
                    logger.warning(f"獲取頁面時遇到429錯誤 (請求過多)")
                    self.handle_429_error()
                    continue

                elif response.status_code != 200:
                    logger.warning(f"獲取頁面失敗，狀態碼: {response.status_code}")
                    if retry < max_retries - 1:
                        time.sleep(random.uniform(
                            self.min_delay, self.max_delay))
                        continue
                    else:
                        return None

                # 成功獲取頁面，重置429計數
                self.consecutive_429_count = 0

                response.encoding = "utf-8"  # 確保中文正常顯示

                # 保存頁面內容以便調試
                if self.debug:
                    with open(f"{self.base_folder}/page_{page_no}.html", "w", encoding="utf-8") as f:
                        f.write(response.text)

                # 成功後等待一段時間，避免請求過於頻繁
                time.sleep(random.uniform(self.min_delay, self.max_delay))

                return BeautifulSoup(response.text, "html.parser")
            except Exception as e:
                logger.error(f"獲取頁面失敗: {e}")
                if retry < max_retries - 1:
                    time.sleep(random.uniform(self.min_delay, self.max_delay))
                else:
                    return None

    def get_total_pages(self):
        """獲取總頁數"""
        logger.info("正在獲取總頁數...")

        # 先訪問首頁，獲取cookies
        try:
            proxies = self.rotate_proxy()
            home_response = self.session.get(
                "https://lawyer.get.com.tw/",
                headers=self.headers,
                timeout=30,
                proxies=proxies
            )

            if home_response.status_code == 429:
                logger.warning("訪問首頁時遇到429錯誤 (請求過多)")
                self.handle_429_error()
            elif home_response.status_code != 200:
                logger.warning(f"訪問首頁失敗，狀態碼: {home_response.status_code}")
        except Exception as e:
            logger.error(f"訪問首頁失敗: {e}")

        # 等待一下再訪問考古題頁面
        time.sleep(random.uniform(self.min_delay, self.max_delay))

        soup = self.get_page(1)
        if not soup:
            logger.error("無法獲取頁面，請檢查網路連接")
            # 保存錯誤頁面以便調試
            if self.debug:
                with open(f"{self.base_folder}/error_page.html", "w", encoding="utf-8") as f:
                    f.write("Failed to get page")
            return 0

        try:
            # 嘗試多種方式獲取頁數
            # 方式1: 查找頁碼div
            page_div = soup.find("div", class_="page")
            if page_div:
                page_text = page_div.text.strip()
                match = re.search(r'共\s+(\d+)', page_text)
                if match:
                    return int(match.group(1))

            # 方式2: 查找頁碼連結
            page_links = soup.select("a[href*='iPageNo=']")
            if page_links:
                max_page = 0
                for link in page_links:
                    href = link.get("href", "")
                    match = re.search(r'iPageNo=(\d+)', href)
                    if match:
                        page_num = int(match.group(1))
                        if page_num > max_page:
                            max_page = page_num
                if max_page > 0:
                    return max_page

            # 方式3: 如果找不到頁碼，但頁面有內容，至少返回1頁
            exam_table = soup.find("table", class_="examlist")
            if exam_table and exam_table.find_all("tr"):
                logger.info("找不到頁碼信息，但頁面有內容，假設至少有1頁")
                return 1

            logger.warning("無法找到頁碼信息")
            return 0
        except Exception as e:
            logger.error(f"獲取總頁數失敗: {e}")
            return 0

    def parse_exam_info(self, soup):
        """解析頁面獲取考古題信息"""
        exam_list = []

        if not soup:
            return exam_list

        # 找到表格
        exam_table = soup.find("table", class_="examlist")
        if not exam_table:
            logger.warning("找不到考古題表格")
            return exam_list

        # 找到表格中的所有行
        rows = exam_table.find_all("tr")

        # 跳過表頭行
        for row in rows:
            if row.get("class") and "head" in row.get("class"):
                continue

            # 獲取所有單元格
            cells = row.find_all("td")
            if len(cells) >= 5:  # 確保行有足夠的單元格
                try:
                    exam_id = cells[0].text.strip()
                    exam_type = cells[1].text.strip()
                    exam_subject = cells[2].text.strip()
                    exam_year = cells[3].text.strip()

                    # 獲取下載連結
                    download_link = cells[4].find("a")
                    if download_link and "href" in download_link.attrs:
                        download_url = download_link["href"]
                        # 提取參數
                        params = {}
                        if "?" in download_url:
                            for param in download_url.split("?")[1].split("&"):
                                if "=" in param:
                                    key, value = param.split("=")
                                    params[key] = value

                        # 構建完整下載URL
                        full_download_url = f"{self.download_base_url}?{download_url.split('?')[1]}" if "?" in download_url else ""

                        exam_doc = ExamDocument(
                            exam_id,
                            exam_type,
                            exam_subject,
                            exam_year,
                            full_download_url,
                            params
                        )
                        exam_list.append(exam_doc)

                        if self.debug:
                            logger.debug(
                                f"解析到考古題: {exam_year}年 {exam_type} {exam_subject}")
                except Exception as e:
                    logger.error(f"解析考古題資訊失敗: {e}")
                    continue

        return exam_list

    def download_pdf(self, exam_doc, skip_existing=True, max_retries=5):
        """下載並解鎖PDF檔案"""
        try:
            # 創建類型和科目目錄
            type_dir = os.path.join(self.base_folder, exam_doc.exam_type)
            os.makedirs(type_dir, exist_ok=True)

            subject_dir = os.path.join(type_dir, exam_doc.subject)
            os.makedirs(subject_dir, exist_ok=True)

            file_path = os.path.join(subject_dir, exam_doc.filename)

            # 檢查文件是否已存在
            if skip_existing and os.path.exists(file_path):
                if self.debug:
                    logger.debug(f"文件已存在，跳過下載: {exam_doc.filename}")
                return True

            # 下載PDF
            for retry in range(max_retries):
                try:
                    # 更新 User-Agent
                    if retry > 0:
                        self.update_headers()

                    # 輪換代理 (如果有)
                    proxies = self.rotate_proxy()

                    response = self.session.get(
                        self.download_base_url,
                        headers=self.headers,
                        params=exam_doc.download_params,
                        stream=True,
                        timeout=60,
                        proxies=proxies
                    )

                    # 檢查響應狀態
                    if response.status_code == 429:
                        logger.warning(
                            f"下載 {exam_doc.filename} 時遇到429錯誤 (請求過多)")
                        self.handle_429_error()
                        continue

                    elif response.status_code == 200:
                        # 檢查內容類型，確保是PDF
                        content_type = response.headers.get(
                            'Content-Type', '').lower()
                        if 'pdf' not in content_type and 'octet-stream' not in content_type:
                            logger.warning(
                                f"下載失敗: {exam_doc.filename}, 非PDF內容: {content_type}")
                            if retry < max_retries - 1:
                                time.sleep(random.uniform(
                                    self.min_delay, self.max_delay))
                                continue
                            else:
                                return False

                        # 暫存原始PDF
                        temp_path = f'{subject_dir}/temp_{exam_doc.filename}'
                        with open(temp_path, "wb") as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)

                        # 解鎖PDF
                        unlock_success = PDFProcessor.unlock_pdf(
                            temp_path, file_path)

                        # 刪除暫存檔
                        if unlock_success and os.path.exists(temp_path):
                            os.remove(temp_path)
                        else:
                            # 如果解鎖失敗，至少保留原始PDF
                            if not os.path.exists(file_path):
                                os.rename(temp_path, file_path)
                                logger.warning(
                                    f"無法解鎖，已保存原始PDF: {exam_doc.filename}")

                        # 成功後重置429計數
                        self.consecutive_429_count = 0

                        if self.debug:
                            logger.info(f"已下載: {exam_doc.filename}")

                        # 成功下載後等待一段時間，避免請求過於頻繁
                        time.sleep(random.uniform(
                            self.min_delay, self.max_delay))

                        return True
                    else:
                        logger.warning(
                            f"下載失敗，狀態碼: {response.status_code}，正在重試 ({retry+1}/{max_retries})")
                        if retry < max_retries - 1:
                            time.sleep(random.uniform(
                                self.min_delay, self.max_delay))
                        else:
                            logger.error(
                                f"下載失敗: {exam_doc.filename}, 狀態碼: {response.status_code}")
                            return False
                except Exception as e:
                    logger.error(f"下載出錯: {str(e)}")
                    if retry < max_retries - 1:
                        time.sleep(random.uniform(
                            self.min_delay, self.max_delay))
                    else:
                        logger.error(
                            f"下載出錯: {exam_doc.filename}, 錯誤: {str(e)}")
                        return False

            return False
        except Exception as e:
            logger.error(f"下載處理失敗: {str(e)}")
            return False

    def generate_readme(self, exam_docs):
        """生成README文件，包含考古題下載連結"""
        logger.info("正在生成README.md檔案...")

        # 按考試類組和科目組織數據
        organized_data = defaultdict(lambda: defaultdict(list))

        for exam in exam_docs:
            organized_data[exam.exam_type][exam.subject].append(exam)

        # 生成README內容
        readme_content = "# 高點法律網考古題下載整理\n\n"
        readme_content += f"最後更新時間：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        # 統計資訊
        total_exams = len(exam_docs)
        total_types = len(organized_data)
        total_subjects = sum(len(subjects)
                             for subjects in organized_data.values())

        readme_content += f"總共收集了 {total_exams} 份考古題，涵蓋 {total_types} 種考試類型，{total_subjects} 個科目。\n\n"

        # 目錄
        readme_content += "## 目錄\n\n"

        for exam_type, subjects in organized_data.items():
            safe_type = exam_type.replace(
                ' ', '-').replace('（', '').replace('）', '')
            readme_content += f"- [{exam_type}](#{safe_type})\n"

            for subject, exams in subjects.items():
                safe_subject = subject.replace(
                    ' ', '-').replace('（', '').replace('）', '')
                readme_content += f"  - [{subject} ({len(exams)}份)](#{safe_type}-{safe_subject})\n"

        readme_content += "\n"

        # 詳細內容
        for exam_type, subjects in organized_data.items():
            safe_type = exam_type.replace(
                ' ', '-').replace('（', '').replace('）', '')
            readme_content += f"## {exam_type}\n\n"

            for subject, exams in subjects.items():
                # 按年份排序
                exams.sort(key=lambda x: x.year, reverse=True)

                safe_subject = subject.replace(
                    ' ', '-').replace('（', '').replace('）', '')
                readme_content += f"### <a id='{safe_type}-{safe_subject}'></a>{subject} ({len(exams)}份)\n\n"

                # 添加每個考古題的連結
                for exam in exams:
                    readme_content += f"- [{exam.year}年 {exam.exam_type} {exam.subject}]({exam.download_url})\n"

                readme_content += "\n"

        # 寫入README文件
        with open(os.path.join(self.base_folder, "README.md"), "w", encoding="utf-8") as f:
            f.write(readme_content)

        logger.info("README.md 檔案已生成")
        return True

    def export_to_csv(self, exam_docs):
        """將考古題資訊匯出為CSV檔案"""
        logger.info("正在匯出考古題資訊到CSV檔案...")

        data = []
        for exam in exam_docs:
            data.append({
                "id": exam.index,
                "type": exam.exam_type,
                "subject": exam.subject,
                "year": exam.year,
                "download_url": exam.download_url,
                "filename": exam.filename
            })

        df = pd.DataFrame(data)
        csv_path = os.path.join(self.base_folder, "all_exams.csv")
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        logger.info(f"已匯出 {len(data)} 筆考古題資訊到 {csv_path}")
        return True

    def save_checkpoint(self, page_no, all_exams):
        """儲存目前的爬蟲進度"""
        try:
            # 儲存檢查點資訊
            checkpoint = {
                "last_page": page_no,
                "exams_count": len(all_exams),
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            with open(self.checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)

            # 將考古題資訊儲存到臨時檔案
            if all_exams:
                exams_data = [exam.to_dict() for exam in all_exams]
                with open(self.temp_exams_file, "w", encoding="utf-8") as f:
                    json.dump(exams_data, f, ensure_ascii=False, indent=2)

            logger.info(f"已儲存檢查點：第 {page_no} 頁，共 {len(all_exams)} 份考古題")
            return True
        except Exception as e:
            logger.error(f"儲存檢查點失敗: {e}")
            return False

    def load_checkpoint(self):
        """載入上次的爬蟲進度"""
        if not os.path.exists(self.checkpoint_file) or not os.path.exists(self.temp_exams_file):
            return None, []

        try:
            # 載入檢查點資訊
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)

            # 載入考古題資訊
            with open(self.temp_exams_file, "r", encoding="utf-8") as f:
                exams_data = json.load(f)

            all_exams = [ExamDocument.from_dict(exam) for exam in exams_data]

            logger.info(
                f"已載入檢查點：第 {checkpoint['last_page']} 頁，共 {len(all_exams)} 份考古題 (儲存時間: {checkpoint['timestamp']})")
            return checkpoint["last_page"], all_exams
        except Exception as e:
            logger.error(f"載入檢查點失敗：{e}")
            return None, []

    def clear_checkpoint(self):
        """清除檢查點資訊"""
        try:
            if os.path.exists(self.checkpoint_file):
                os.remove(self.checkpoint_file)
            if os.path.exists(self.temp_exams_file):
                os.remove(self.temp_exams_file)
            logger.info("已清除檢查點資訊")
            return True
        except Exception as e:
            logger.error(f"清除檢查點失敗: {e}")
            return False

    def run(self, max_pages=None, skip_existing=True, batch_size=10, batch_delay=60, resume=True):
        """執行爬蟲程序，支援從中斷處繼續"""
        logger.info("=== 高點法律考古題自動下載與解鎖系統 ===")
        logger.info("系統將自動下載法律考古題並解鎖PDF，使其可編輯、複製")
        logger.info("檔案將依據考試類型和科目分類存放")
        logger.info(
            f"請求間隔: {self.min_delay}-{self.max_delay} 秒，429錯誤等待: {self.retry_delay} 秒")

        # 檢查是否有上次中斷的進度
        start_page = 1
        all_exams = []

        if resume:
            last_page, saved_exams = self.load_checkpoint()
            if last_page is not None:
                start_page = last_page + 1
                all_exams = saved_exams
                logger.info(
                    f"從第 {start_page} 頁繼續執行，已載入 {len(all_exams)} 份考古題資訊")

        # 獲取總頁數
        total_pages = self.get_total_pages()
        if total_pages == 0:
            logger.error("無法獲取頁面資訊，請檢查網路連接或網站是否可訪問")

            # 嘗試直接使用固定頁數
            if self.debug:
                logger.info("嘗試使用固定頁數 (176 頁)")
                total_pages = 176
            else:
                return False

        if max_pages and max_pages < total_pages:
            total_pages = max_pages

        logger.info(f"共找到 {total_pages} 頁考古題資料，從第 {start_page} 頁開始處理")

        # 收集所有考古題資訊
        try:
            for page_no in tqdm(range(start_page, total_pages + 1), desc="處理頁面"):
                logger.info(f"正在處理第 {page_no} 頁，共 {total_pages} 頁")
                soup = self.get_page(page_no)

                if not soup:
                    logger.warning(f"無法獲取第 {page_no} 頁，跳過")
                    continue

                exams = self.parse_exam_info(soup)
                all_exams.extend(exams)

                # 每處理 5 頁儲存一次檢查點
                if page_no % 5 == 0 or page_no == total_pages:
                    self.save_checkpoint(page_no, all_exams)

        except KeyboardInterrupt:
            logger.warning("檢測到使用者中斷，儲存目前進度...")
            self.save_checkpoint(page_no, all_exams)
            logger.info(f"已儲存進度至第 {page_no} 頁，下次執行時可繼續")
            return False

        except Exception as e:
            logger.error(f"處理頁面時發生錯誤：{e}")
            self.save_checkpoint(page_no, all_exams)
            logger.info(f"已儲存進度至第 {page_no} 頁，下次執行時可繼續")
            return False

        logger.info(f"共收集到 {len(all_exams)} 份考古題資訊")

        if len(all_exams) == 0:
            logger.error("沒有找到任何考古題，請檢查網站結構是否變更")
            return False

        # 匯出考古題資訊到CSV
        self.export_to_csv(all_exams)

        # 生成README文件
        self.generate_readme(all_exams)

        # 下載所有PDF文件 - 分批下載以避免429錯誤
        logger.info(
            f"開始下載 {len(all_exams)} 份考古題 (分批下載，每批 {batch_size} 份，批次間隔 {batch_delay} 秒)...")

        # 檢查是否有下載進度紀錄
        download_progress_file = os.path.join(
            self.base_folder, "download_progress.json")
        downloaded_files = set()

        if os.path.exists(download_progress_file) and resume:
            try:
                with open(download_progress_file, "r", encoding="utf-8") as f:
                    downloaded_files = set(json.load(f))
                logger.info(f"已載入下載進度，已完成 {len(downloaded_files)} 份考古題下載")
            except Exception as e:
                logger.error(f"載入下載進度失敗: {e}")

        success_count = len(downloaded_files)
        fail_count = 0

        # 建立待下載清單
        to_download = [
            exam for exam in all_exams if exam.filename not in downloaded_files]
        logger.info(f"待下載: {len(to_download)} 份考古題")

        try:
            # 分批處理
            for i in range(0, len(to_download), batch_size):
                batch = to_download[i:i+batch_size]

                logger.info(
                    f"處理第 {i//batch_size + 1} 批，共 {len(batch)} 份考古題 (總進度: {i}/{len(to_download)})")

                for exam in tqdm(batch, desc=f"批次 {i//batch_size + 1}"):
                    if self.download_pdf(exam, skip_existing):
                        success_count += 1
                        # 記錄下載成功的檔案
                        downloaded_files.add(exam.filename)
                        # 每下載成功一個檔案就更新進度
                        with open(download_progress_file, "w", encoding="utf-8") as f:
                            json.dump(list(downloaded_files), f)
                    else:
                        fail_count += 1

                # 每批次處理完後等待較長時間，避免觸發429
                if i + batch_size < len(to_download):
                    logger.info(f"批次處理完成，等待 {batch_delay} 秒後繼續下一批...")
                    time.sleep(batch_delay)

        except KeyboardInterrupt:
            logger.warning("檢測到使用者中斷，已儲存目前下載進度")
            # 儲存下載進度
            with open(download_progress_file, "w", encoding="utf-8") as f:
                json.dump(list(downloaded_files), f)
            return False

        except Exception as e:
            logger.error(f"下載過程中發生錯誤: {e}")
            # 儲存下載進度
            with open(download_progress_file, "w", encoding="utf-8") as f:
                json.dump(list(downloaded_files), f)
            return False

        logger.info(f"下載完成！成功: {success_count}，失敗: {fail_count}")
        logger.info("PDF檔案已解鎖，可以進行註解、複製和編輯")
        logger.info("檔案已按考試類型和科目分類儲存")

        # 清除檢查點，表示完整執行結束
        self.clear_checkpoint()

        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='高點法律考古題下載系統')
    parser.add_argument('--pages', type=int, default=None,
                        help='要下載的頁數（默認下載所有頁）')
    parser.add_argument('--skip-existing', action='store_true',
                        help='跳過已存在的檔案，不重新下載')
    parser.add_argument('--debug', action='store_true',
                        help='開啟調試模式，顯示更多日誌信息')
    parser.add_argument('--folder', type=str, default="./高點法律考古題",
                        help='指定下載資料夾（默認為./高點法律考古題）')
    parser.add_argument('--fixed-pages', type=int, default=176,
                        help='使用固定頁數而不是嘗試獲取總頁數')
    parser.add_argument('--min-delay', type=float, default=5.0,
                        help='最小請求延遲秒數（默認5秒）')
    parser.add_argument('--max-delay', type=float, default=10.0,
                        help='最大請求延遲秒數（默認10秒）')
    parser.add_argument('--retry-delay', type=float, default=30.0,
                        help='遇到429錯誤時的等待秒數（默認30秒）')
    parser.add_argument('--batch-size', type=int, default=10,
                        help='每批下載的考古題數量（默認10份）')
    parser.add_argument('--batch-delay', type=int, default=60,
                        help='批次之間的等待秒數（默認60秒）')
    parser.add_argument('--proxy-list', type=str, default=None,
                        help='代理伺服器列表文件，每行一個代理地址')
    parser.add_argument('--no-resume', action='store_true',
                        help='不從上次中斷處繼續，重新開始爬蟲')
    parser.add_argument('--clear-checkpoint', action='store_true',
                        help='清除所有檢查點和進度記錄，重新開始')

    args = parser.parse_args()

    # 初始化爬蟲
    crawler = LawExamCrawler(base_folder=args.folder, debug=args.debug)

    # 設置延遲參數
    crawler.min_delay = args.min_delay
    crawler.max_delay = args.max_delay
    crawler.retry_delay = args.retry_delay

    # 加載代理列表（如果有）
    if args.proxy_list:
        try:
            with open(args.proxy_list, 'r') as f:
                crawler.proxies = [line.strip() for line in f if line.strip()]
            logger.info(f"已加載 {len(crawler.proxies)} 個代理伺服器")
        except Exception as e:
            logger.error(f"無法加載代理列表: {e}")

    # 如果指定清除檢查點
    if args.clear_checkpoint:
        crawler.clear_checkpoint()
        # 同時清除下載進度
        download_progress_file = os.path.join(
            args.folder, "download_progress.json")
        if os.path.exists(download_progress_file):
            os.remove(download_progress_file)
            logger.info("已清除下載進度記錄")

    # 運行爬蟲
    if args.fixed_pages:
        # 直接使用固定頁數
        logger.info(f"使用固定頁數: {args.fixed_pages}")
        max_pages = args.pages if args.pages else args.fixed_pages

        # 執行爬蟲，支援恢復功能
        crawler.run(
            max_pages=max_pages,
            skip_existing=args.skip_existing,
            batch_size=args.batch_size,
            batch_delay=args.batch_delay,
            resume=not args.no_resume
        )
    else:
        # 使用原來的方法，但加入恢復功能
        crawler.run(
            max_pages=args.pages,
            skip_existing=args.skip_existing,
            batch_size=args.batch_size,
            batch_delay=args.batch_delay,
            resume=not args.no_resume
        )



'''
正常執行：程式會自動檢查是否有上次的中斷進度，如果有則從中斷處繼續
python getlawarticle1.py


不使用恢復功能：強制從頭開始執行
python getlawarticle1.py - -no-resume

清除所有進度記錄：清除檢查點和下載進度，重新開始
python getlawarticle1.py - -clear-checkpoint


其他參數保持不變：您仍然可以使用原有的參數控制爬蟲行為
python getlawarticle1.py - -min-delay 10 --max-delay 20 --retry-delay 60 --batch-size 5 --batch-delay 120

'''
