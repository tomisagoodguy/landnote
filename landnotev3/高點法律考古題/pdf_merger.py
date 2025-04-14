import os
import re
import sys
import argparse
import logging
import warnings
from PyPDF2 import PdfMerger
import fitz  # PyMuPDF，用於驗證 PDF

# 禁用 PyPDF2 的警告輸出
logging.getLogger('PyPDF2').setLevel(logging.ERROR)

# 自定義警告過濾器


def custom_warning_filter(message, category, filename, lineno, file=None, line=None):
    if "Illegal character in Name Object" in str(message):
        return None  # 不顯示這類警告
    return warnings.defaultaction(message, category, filename, lineno, file, line)


# 設置警告過濾器
warnings.showwarning = custom_warning_filter


class PdfProcessor:
    def __init__(self, output_folder="合併後PDF檔案"):
        self._setup_logging()
        self.output_folder = output_folder

    def _setup_logging(self):
        """設置日誌系統"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('pdf_merge.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

        # 禁用 PyPDF2 的警告日誌
        for handler in self.logger.handlers:
            handler.addFilter(
                lambda record: "Illegal character in Name Object" not in record.getMessage())

    def extract_year(self, filename):
        """從檔名中提取年份數字，用於排序"""
        # 嘗試找出年份格式 (如 "2023年" 或 "112年")
        year_match = re.search(r'(\d{2,4})[\s_年]+', filename)
        if year_match:
            year = int(year_match.group(1))
            # 處理民國年轉西元年
            if year < 1911:
                year += 1911
            return year

        # 如果沒有明確的年份標記，嘗試提取任何數字
        numbers = re.findall(r'\d+', filename)
        if numbers:
            # 找出最可能是年份的數字 (大於1911且小於2100)
            for num in map(int, numbers):
                if 1911 <= num <= 2100:
                    return num
            # 如果沒有符合年份範圍的數字，返回最大的數字
            return max(map(int, numbers))
        return 0

    def verify_pdf(self, pdf_path):
        """驗證 PDF 文件是否可以正常打開"""
        try:
            doc = fitz.open(pdf_path)
            page_count = doc.page_count
            doc.close()
            return True, page_count
        except Exception as e:
            self.logger.error(
                f"PDF 驗證失敗 {os.path.basename(pdf_path)}: {str(e)}")
            return False, 0

    def add_bookmarks(self, merger, pdf_files):
        """為合併後的PDF添加書籤，指向每個原始PDF的開始位置"""
        page_count = 0
        for pdf_file in pdf_files:
            # 提取年份或其他識別信息
            year = self.extract_year(pdf_file)
            if year > 0:
                # 添加書籤，指向該PDF的第一頁
                title = f"{year}年考題"
            else:
                # 如果無法提取年份，使用檔名
                title = os.path.splitext(os.path.basename(pdf_file))[0]

            try:
                # 添加書籤
                merger.add_outline_item(title, page_count, parent=None)
            except:
                self.logger.warning(f"無法為 {pdf_file} 添加書籤")

            # 更新頁數計數
            try:
                doc = fitz.open(pdf_file)
                page_count += doc.page_count
                doc.close()
            except:
                self.logger.warning(f"無法獲取 {pdf_file} 的頁數")

    def merge_pdfs(self, folder_path, output_filename, output_dir):
        """合併PDF檔案"""
        merger = PdfMerger()
        pdf_count = 0
        total_pages = 0
        pdf_file_paths = []  # 存儲完整的文件路徑

        try:
            # 取得所有PDF檔案
            pdf_files = [f for f in os.listdir(folder_path)
                         if f.lower().endswith('.pdf')]

            # 按照檔名中的數字排序，數字大的在前（新的考古題在前）
            pdf_files.sort(key=self.extract_year, reverse=True)

            self.logger.info(f"排序後的檔案順序: {pdf_files}")

            if not pdf_files:
                self.logger.info(f"資料夾 {folder_path} 中沒有PDF檔案")
                return 0

            # 提取年份範圍
            years = [self.extract_year(f) for f in pdf_files]
            years = [y for y in years if y > 0]  # 過濾無效年份

            if years:
                min_year = min(years)
                max_year = max(years)
                # 更新輸出檔名，加入年份範圍
                base_name = output_filename.replace("_合併.pdf", "")
                output_filename = f"{base_name}_{min_year}至{max_year}年_合併.pdf"

            # 處理每個PDF檔案
            for pdf_file in pdf_files:
                file_path = os.path.join(folder_path, pdf_file)
                pdf_file_paths.append(file_path)  # 存儲完整路徑
                self.logger.info(f"處理檔案: {pdf_file}")

                try:
                    # 驗證 PDF 文件
                    is_valid, page_count = self.verify_pdf(file_path)
                    if not is_valid:
                        self.logger.warning(f"檔案 {pdf_file} 無法正常打開，跳過")
                        continue

                    total_pages += page_count

                    # 暫時重定向標準錯誤輸出以抑制警告
                    original_stderr = sys.stderr
                    sys.stderr = open(os.devnull, 'w')

                    # 添加PDF到合併器
                    merger.append(file_path)
                    pdf_count += 1

                    # 恢復標準錯誤輸出
                    sys.stderr.close()
                    sys.stderr = original_stderr

                except Exception as e:
                    # 恢復標準錯誤輸出（如果異常發生）
                    if 'original_stderr' in locals() and sys.stderr != original_stderr:
                        sys.stderr.close()
                        sys.stderr = original_stderr

                    self.logger.error(f"添加檔案 {pdf_file} 時發生錯誤: {str(e)}")
                    self.logger.error(f"跳過此檔案並繼續處理其他檔案")
                    continue

            if pdf_count == 0:
                self.logger.warning(f"沒有有效的PDF檔案可合併")
                return 0

            # 確保輸出目錄存在
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                self.logger.info(f"創建輸出資料夾: {output_dir}")

            # 儲存合併後的檔案
            output_path = os.path.join(output_dir, output_filename)

            # 嘗試添加書籤
            try:
                self.add_bookmarks(merger, pdf_file_paths)
            except Exception as e:
                self.logger.warning(f"添加書籤時發生錯誤: {str(e)}")

            # 暫時重定向標準錯誤輸出以抑制警告
            original_stderr = sys.stderr
            sys.stderr = open(os.devnull, 'w')

            merger.write(output_path)

            # 恢復標準錯誤輸出
            sys.stderr.close()
            sys.stderr = original_stderr

            # 驗證輸出 PDF
            is_valid, final_page_count = self.verify_pdf(output_path)
            status = "成功" if is_valid else "失敗，輸出檔案可能損壞"

            self.logger.info(
                f"合併完成 ({status}):\n"
                f"- 處理檔案數: {pdf_count}\n"
                f"- 輸入總頁數: {total_pages}\n"
                f"- 輸出總頁數: {final_page_count}\n"
                f"- 輸出檔案: {output_path}"
            )

        except Exception as e:
            # 確保標準錯誤輸出已恢復
            if 'original_stderr' in locals() and sys.stderr != original_stderr:
                sys.stderr.close()
                sys.stderr = original_stderr

            self.logger.error(f"合併過程發生錯誤: {str(e)}")
        finally:
            merger.close()

        return pdf_count

    def process_directory(self, root_path, subject_filter=None, exam_type_filter=None):
        """處理指定目錄下的所有考試類型和科目資料夾"""
        self.logger.info(f"開始處理路徑: {root_path}")

        if not os.path.exists(root_path):
            self.logger.error(f"路徑不存在: {root_path}")
            return

        # 創建輸出主資料夾
        output_main_dir = os.path.join(root_path, self.output_folder)
        if not os.path.exists(output_main_dir):
            os.makedirs(output_main_dir)
            self.logger.info(f"創建主輸出資料夾: {output_main_dir}")

        # 檢查目錄結構
        first_level_items = [item for item in os.listdir(root_path)
                             if os.path.isdir(os.path.join(root_path, item))
                             and item != self.output_folder]

        # 檢查第一層是否有PDF檔案
        has_pdf_first_level = any(f.lower().endswith('.pdf')
                                  for f in os.listdir(root_path))

        # 如果第一層只有PDF檔案，直接處理根目錄
        if has_pdf_first_level:
            self.logger.info("在根目錄發現PDF檔案，直接處理根目錄")
            output_filename = f"{os.path.basename(root_path)}_合併.pdf"
            self.merge_pdfs(root_path, output_filename, output_main_dir)
            return

        # 檢查每個第一層資料夾是否包含PDF檔案
        for item in first_level_items:
            item_path = os.path.join(root_path, item)
            if any(f.lower().endswith('.pdf') for f in os.listdir(item_path)):
                # 如果第一層資料夾直接包含PDF，則視為科目資料夾
                self.logger.info(f"資料夾 {item} 直接包含PDF檔案，視為科目資料夾")
                if subject_filter and item not in subject_filter:
                    continue

                output_filename = f"{item}_合併.pdf"
                self.merge_pdfs(item_path, output_filename, output_main_dir)
                continue

            # 否則視為考試類型資料夾
            if exam_type_filter and item not in exam_type_filter:
                continue

            self.logger.info(f"處理考試類型: {item}")

            # 創建考試類型輸出資料夾
            exam_type_output_dir = os.path.join(output_main_dir, item)
            if not os.path.exists(exam_type_output_dir):
                os.makedirs(exam_type_output_dir)

            # 處理該考試類型下的所有科目資料夾
            for subject in os.listdir(item_path):
                subject_path = os.path.join(item_path, subject)

                # 跳過非資料夾
                if not os.path.isdir(subject_path):
                    continue

                # 如果設置了科目過濾器，則只處理符合條件的科目
                if subject_filter and subject not in subject_filter:
                    continue

                try:
                    output_filename = f"{item}_{subject}_合併.pdf"
                    self.logger.info(f"處理科目: {subject}")
                    pdf_count = self.merge_pdfs(
                        subject_path,
                        output_filename,
                        exam_type_output_dir
                    )
                    if pdf_count > 0:
                        self.logger.info(
                            f"完成 {item}/{subject} 資料夾處理，合併了 {pdf_count} 個PDF檔案"
                        )
                except Exception as e:
                    self.logger.error(f"處理 {item}/{subject} 時發生錯誤: {str(e)}")


def main():
    # 解析命令列參數
    parser = argparse.ArgumentParser(description='PDF合併工具 - 專為高點法律考古題設計')
    parser.add_argument('--path', type=str,
                        default=r"C:\Users\tom89\Documents\GitHub\landnote\landnotev3\高點法律考古題",
                        help='指定要處理的根目錄路徑')
    parser.add_argument('--subjects', type=str, nargs='+',
                        help='指定要處理的科目列表，例如：民法 刑法')
    parser.add_argument('--exam-types', type=str, nargs='+',
                        help='指定要處理的考試類型列表')
    parser.add_argument('--output-folder', type=str, default='合併後PDF檔案',
                        help='指定輸出資料夾名稱')

    args = parser.parse_args()

    # 建立處理器實例並執行
    processor = PdfProcessor(output_folder=args.output_folder)
    processor.logger.info("=== 開始執行PDF合併程式 ===")
    processor.process_directory(args.path, args.subjects, args.exam_types)
    processor.logger.info("=== PDF合併程式執行完成 ===")


if __name__ == "__main__":
    main()




#  python pdf_merger.py
