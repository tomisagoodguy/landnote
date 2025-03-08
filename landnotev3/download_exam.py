import requests
import pandas as pd
from bs4 import BeautifulSoup
import os
import pikepdf
import time
import random
import datetime
from urllib.parse import quote


class PDFProcessor:
    """PDF處理類，負責PDF檔案的解鎖和儲存"""

    @staticmethod
    def unlock_pdf(input_path, output_path):
        """解除PDF檔案的保護，使其可編輯、複製等"""
        try:
            with pikepdf.open(input_path) as pdf:
                pdf.save(output_path)
            print(f"已解鎖: {os.path.basename(output_path)}")
            return True
        except Exception as e:
            print(f"解鎖失敗: {e}")
            return False


class ExamDocument:
    """考古題文件類，代表單一份考古題"""

    def __init__(self, index, group, subject, year, link):
        self.index = index
        self.group = group
        self.subject = subject
        self.year = year
        self.link = link
        self.file_name = f"[{year}][{group}][{subject}].pdf"
        self.file_name = self.file_name.replace('\r', '').replace('\n', '')

    def display_info(self):
        """顯示考古題資訊"""
        print(f'編號: {self.index}')
        print(f'類組: {self.group}')
        print(f'科目: {self.subject}')
        print(f'年度: {self.year}')
        print(f'連結: {self.link}')

    def download_and_unlock(self, base_folder="./地政考古題", skip_existing=True):
        """下載並解鎖PDF檔案，可選擇跳過已存在的檔案"""
        try:
            # 建立對應科目的資料夾
            subject_folder = f'{base_folder}/{self.subject}'
            if not os.path.exists(subject_folder):
                os.makedirs(subject_folder)

            # 檢查檔案是否已存在
            final_path = f'{subject_folder}/{self.file_name}'
            if skip_existing and os.path.exists(final_path):
                print(f"檔案已存在，跳過: {self.file_name}")
                return True

            # 發送請求獲取重定向後的真實PDF連結
            response = requests.get(self.link)
            pdf_url = response.url

            # 下載PDF檔案
            response = requests.get(pdf_url)

            # 暫存原始PDF
            temp_path = f'{subject_folder}/temp_{self.file_name}'
            with open(temp_path, "wb") as f:
                f.write(response.content)

            # 解鎖PDF
            unlock_success = PDFProcessor.unlock_pdf(temp_path, final_path)

            # 刪除暫存檔
            if unlock_success and os.path.exists(temp_path):
                os.remove(temp_path)
            else:
                # 如果解鎖失敗，至少保留原始PDF
                if not os.path.exists(final_path):
                    os.rename(temp_path, final_path)
                    print(f"無法解鎖，已保存原始PDF: {self.file_name}")

            return True
        except Exception as e:
            print(f"下載失敗: {e}")
            return False


class ExamSearcher:
    """考古題搜尋類，負責搜尋和解析考古題"""

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # 地政相關考試類組和科目
        self.land_exam_groups = [
            "地方政府特考四等-地政", "地方政府特考三等-地政", "普考-地政",
            "高考三級-地政", "地方政府特考五等-地政"
        ]

        self.land_exam_subjects = [
            "土地法規概要（包括土地登記）", "土地法規（包括土地登記）", "土地法大意",
            "土地法規概要", "土地法規", "民法物權編概要", "土地利用概要",
            "民法（包括總則、物權、親屬與繼承）", "土地政策", "土地經濟學",
            "不動產估價", "土地登記"
        ]

    def get_total_pages(self, keyword, filter_type='A', year=''):
        """獲取搜尋結果的總頁數"""
        encoded_keyword = quote(keyword)
        url = f'http://goldensun.get.com.tw/exam/List.aspx?iPageNo=1&sFilter={encoded_keyword}&sFilterDate={year}&sFilterType={filter_type}'

        try:
            r = requests.get(url, headers=self.headers)
            soup = BeautifulSoup(r.text, "html.parser")

            page_div = soup.find("div", class_="page")
            if not page_div:
                return 0

            total_page = page_div.text
            total_page = total_page.replace(
                '第 1 頁,共 ', '').replace('第 0 頁,共 ', '')

            tmp = ''
            for i in range(len(total_page)):
                if total_page[i] != ' ':
                    tmp += total_page[i]
                else:
                    break

            return int(tmp) if tmp else 0
        except Exception as e:
            print(f"獲取頁數失敗: {e}")
            return 0

    def is_land_related(self, group, subject):
        """判斷是否為地政相關考試"""
        # 檢查考試類組
        if any(land_group in group for land_group in self.land_exam_groups):
            return True

        # 檢查考試科目
        if any(land_subject in subject for land_subject in self.land_exam_subjects):
            return True

        return False

    def search_exams(self, keyword, filter_type='A', year=''):
        """搜尋考古題並返回ExamDocument對象列表"""
        print(
            f"正在搜尋關鍵字: {keyword}, 篩選方式: {filter_type}, 年份: {year if year else '不限'}")

        encoded_keyword = quote(keyword)
        total_page = self.get_total_pages(keyword, filter_type, year)

        if total_page == 0:
            print(f'查無 "{keyword}" 相關資料')
            return []

        print(f"關鍵字 '{keyword}' 共找到 {total_page} 頁資料")

        exam_documents = []

        for i in range(1, total_page + 1):
            print(f"正在處理第 {i}/{total_page} 頁")
            page = str(i)

            url = f'http://goldensun.get.com.tw/exam/List.aspx?iPageNo={page}&sFilter={encoded_keyword}&sFilterDate={year}&sFilterType={filter_type}'

            try:
                r = requests.get(url, headers=self.headers)
                soup = BeautifulSoup(r.text, "html.parser")

                exam_list = soup.find_all('tr')

                if len(exam_list) >= 2:
                    exam_list = exam_list[2:]  # 跳過前兩行(快速搜尋和標頭)

                for exam in exam_list:
                    try:
                        ex_info = exam.find_all('td')

                        if len(ex_info) >= 5:
                            index = BeautifulSoup(
                                ex_info[0].text, "html.parser").text.strip()
                            group = BeautifulSoup(
                                ex_info[1].text, "html.parser").text.strip()
                            subject = BeautifulSoup(
                                ex_info[2].text, "html.parser").text.strip()
                            year = BeautifulSoup(
                                ex_info[3].text, "html.parser").text.strip()

                            if self.is_land_related(group, subject):
                                link_element = ex_info[4].find('a')
                                if link_element and link_element.get('href'):
                                    link = 'http://goldensun.get.com.tw/exam/' + \
                                        link_element.get(
                                            'href').replace('./', '')

                                    exam_doc = ExamDocument(
                                        index, group, subject, year, link)
                                    exam_documents.append(exam_doc)
                    except Exception as e:
                        print(f"處理考古題記錄時出錯: {e}")
                        continue

                # 短暫休息，避免過度頻繁請求
                time.sleep(random.uniform(0.5, 1.0))

            except Exception as e:
                print(f"處理頁面時出錯: {e}")
                continue

        return exam_documents


class ReadmeGenerator:
    """README.md 生成器，用於創建考古題目錄"""

    def __init__(self, base_folder):
        self.base_folder = base_folder
        self.readme_path = f"{base_folder}/README.md"

    def generate_readme(self):
        """生成README.md檔案作為考古題目錄"""
        print("正在生成README.md檔案...")

        # 檢查資料夾結構
        if not os.path.exists(self.base_folder):
            print(f"資料夾 {self.base_folder} 不存在，無法生成README")
            return False

        # 獲取所有科目資料夾
        subject_folders = [f for f in os.listdir(self.base_folder)
                           if os.path.isdir(os.path.join(self.base_folder, f))]

        # 開始寫入README
        with open(self.readme_path, 'w', encoding='utf-8') as readme:
            # 寫入標題
            readme.write("# 地政考古題資料庫\n\n")
            readme.write("本資料庫收集了地政相關考試的考古題，按科目分類整理。\n\n")
            readme.write(
                f"最後更新時間：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            # 寫入目錄
            readme.write("## 目錄\n\n")
            for subject in sorted(subject_folders):
                if subject != "README.md":
                    readme.write(
                        f"- [{subject}](#{subject.replace(' ', '-').replace('（', '').replace('）', '')})\n")

            readme.write("\n")

            # 寫入各科目的檔案列表
            for subject in sorted(subject_folders):
                if subject == "README.md":
                    continue

                readme.write(f"## {subject}\n\n")

                # 獲取該科目下的所有PDF檔案
                subject_path = os.path.join(self.base_folder, subject)
                pdf_files = [f for f in os.listdir(
                    subject_path) if f.endswith('.pdf')]

                # 按年份排序（從新到舊）
                pdf_files.sort(reverse=True)

                # 寫入檔案列表
                for pdf in pdf_files:
                    pdf_path = f"{subject}/{pdf}"
                    pdf_name = pdf.replace('.pdf', '')
                    readme.write(
                        f"- [{pdf_name}]({pdf_path.replace(' ', '%20')})\n")

                readme.write("\n")

        print(f"README.md 檔案已生成：{self.readme_path}")
        return True


class LandExamDownloader:
    """地政考古題下載器，管理整個下載流程"""

    def __init__(self):
        self.searcher = ExamSearcher()
        self.base_folder = "./地政考古題"
        self.readme_generator = ReadmeGenerator(self.base_folder)

        # 創建基礎資料夾
        if not os.path.exists(self.base_folder):
            os.makedirs(self.base_folder)

        # 地政相關關鍵字列表
        self.keywords = ["地政", "土地法", "土地登記", "不動產", "土地利用", "土地經濟", "民法物權"]

    def download_by_keyword(self, keyword, filter_type='A', year='', skip_existing=True):
        """下載特定關鍵字的考古題"""
        exam_docs = self.searcher.search_exams(keyword, filter_type, year)

        if not exam_docs:
            return 0

        download_count = 0
        print(f"找到 {len(exam_docs)} 份地政相關考古題，開始下載...")

        for doc in exam_docs:
            doc.display_info()
            if doc.download_and_unlock(self.base_folder, skip_existing):
                download_count += 1
            print('--------------------')

            # 短暫休息，避免過度頻繁請求
            time.sleep(random.uniform(0.5, 1.5))

        return download_count

    def download_recent_exams(self, years=10, skip_existing=True):
        """下載最近幾年的考古題"""
        current_year = datetime.datetime.now().year
        total_downloads = 0

        print(f"\n開始下載最近{years}年的地政考古題...")
        for year in range(current_year, current_year-years, -1):
            for keyword in self.keywords:
                # 搜尋考試類組
                downloads = self.download_by_keyword(
                    keyword, 'D', str(year), skip_existing)
                total_downloads += downloads

                # 搜尋考試科目
                downloads = self.download_by_keyword(
                    keyword, 'P', str(year), skip_existing)
                total_downloads += downloads

        return total_downloads

    def download_all_exams(self, skip_existing=True):
        """下載所有年份的考古題"""
        total_downloads = 0

        print("\n開始下載所有年份的地政考古題...")
        for keyword in self.keywords:
            # 搜尋考試類組
            downloads = self.download_by_keyword(
                keyword, 'D', skip_existing=skip_existing)
            total_downloads += downloads

            # 搜尋考試科目
            downloads = self.download_by_keyword(
                keyword, 'P', skip_existing=skip_existing)
            total_downloads += downloads

        return total_downloads

    def run(self, years=10, only_update=False, download_all=False):
        """執行下載流程"""
        print("=== 地政考古題自動下載與解鎖系統 ===")
        print("系統將自動下載地政相關考古題並解鎖PDF，使其可編輯、複製")
        print("檔案將依據考試科目分類存放")

        total_downloads = 0

        if download_all:
            print("設定下載所有年份的地政考古題")
            if only_update:
                print("僅更新模式：將只下載尚未存在的檔案")

            # 下載所有年份的考古題
            total_downloads = self.download_all_exams(
                skip_existing=only_update)
        else:
            print(f"設定下載最近 {years} 年的地政考古題")
            if only_update:
                print("僅更新模式：將只下載尚未存在的檔案")

            # 下載最近N年的考古題
            recent_downloads = self.download_recent_exams(
                years, skip_existing=only_update)

            # 下載其他年份的考古題（如果需要）
            other_downloads = 0
            if years <= 0:  # 如果years設為0或負數，也下載所有年份
                other_downloads = self.download_all_exams(
                    skip_existing=only_update)

            total_downloads = recent_downloads + other_downloads

        # 生成README.md檔案作為目錄
        self.readme_generator.generate_readme()

        print(f"\n所有地政考古題下載完成！共下載 {total_downloads} 份考古題")
        print("PDF檔案已解鎖，可以進行註解、複製和編輯")
        print("檔案已按考試科目分類儲存在「地政考古題」資料夾中")
        print("README.md檔案已生成，提供完整目錄索引")


# 執行程式
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='地政考古題下載系統')
    parser.add_argument('--years', type=int, default=10,
                        help='要下載的最近年數（預設：10年）')
    parser.add_argument('--update', action='store_true',
                        help='僅更新模式：只下載尚未存在的檔案')
    parser.add_argument('--all', action='store_true',
                        help='下載所有年份的考古題，不限於最近幾年')

    args = parser.parse_args()

    downloader = LandExamDownloader()
    downloader.run(years=args.years, only_update=args.update,
                   download_all=args.all)




# python download_exam.py


'''
指定下載年數：
python download_exam.py --years 5

僅更新模式（只下載未下載的部分）：
python download_exam.py --update

指定年數並使用更新模式：
python download_exam.py --years 10 --update

下載所有年份考古題
python download_exam.py --all

這個命令會下載所有年份的地政相關考古題，但只下載尚未存在的檔案，避免重複下載。
python download_exam.py --all --update



'''