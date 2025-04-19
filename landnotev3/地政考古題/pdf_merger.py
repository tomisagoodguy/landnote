import os
import re
import sys
import logging
import warnings
from PyPDF2 import PdfMerger
import fitz  # PyMuPDF，用於驗證 PDF

# 設置 PyPDF2 日誌和警告過濾
logging.getLogger('PyPDF2').setLevel(logging.ERROR)


def custom_warning_filter(message, category, filename, lineno, file=None, line=None):
    if "Illegal character in Name Object" in str(message):
        return None
    return warnings.defaultaction(message, category, filename, lineno, file, line)


warnings.showwarning = custom_warning_filter


class PdfMergerProcessor:
    def __init__(self, base_folder="."):
        self.base_folder = base_folder
        self.output_folder = os.path.join(base_folder, "合併後PDF檔案")
        self._setup_logging()

    def _setup_logging(self):
        """設置日誌系統"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(
                    self.base_folder, 'pdf_merge.log'), encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        for handler in self.logger.handlers:
            handler.addFilter(
                lambda record: "Illegal character in Name Object" not in record.getMessage())

    def extract_year(self, filename):
        """從檔名中提取年份數字，用於排序"""
        numbers = re.findall(r'\d+', filename)
        if numbers:
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

    def merge_pdfs(self, folder_path, output_filename, output_dir):
        """合併PDF檔案"""
        merger = PdfMerger()
        pdf_count = 0
        total_pages = 0

        try:
            # 取得所有PDF檔案
            pdf_files = [f for f in os.listdir(
                folder_path) if f.lower().endswith('.pdf')]
            pdf_files.sort(key=self.extract_year, reverse=True)
            self.logger.info(f"排序後的檔案順序: {pdf_files}")

            if not pdf_files:
                self.logger.info(f"資料夾 {folder_path} 中沒有PDF檔案")
                return 0

            # 處理每個PDF檔案
            for pdf_file in pdf_files:
                file_path = os.path.join(folder_path, pdf_file)
                self.logger.info(f"處理檔案: {pdf_file}")

                try:
                    is_valid, page_count = self.verify_pdf(file_path)
                    if not is_valid:
                        self.logger.warning(f"檔案 {pdf_file} 無法正常打開，跳過")
                        continue

                    total_pages += page_count
                    original_stderr = sys.stderr
                    sys.stderr = open(os.devnull, 'w')
                    merger.append(file_path)
                    pdf_count += 1
                    sys.stderr.close()
                    sys.stderr = original_stderr

                except Exception as e:
                    if 'original_stderr' in locals() and sys.stderr != original_stderr:
                        sys.stderr.close()
                        sys.stderr = original_stderr
                    self.logger.error(f"添加檔案 {pdf_file} 時發生錯誤: {str(e)}")
                    continue

            # 確保輸出目錄存在
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                self.logger.info(f"創建輸出資料夾: {output_dir}")

            # 儲存合併後的檔案
            output_path = os.path.join(output_dir, output_filename)
            original_stderr = sys.stderr
            sys.stderr = open(os.devnull, 'w')
            merger.write(output_path)
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
            if 'original_stderr' in locals() and sys.stderr != original_stderr:
                sys.stderr.close()
                sys.stderr = original_stderr
            self.logger.error(f"合併過程發生錯誤: {str(e)}")
        finally:
            merger.close()

        return pdf_count

    def process_directory(self):
        """處理指定目錄下的所有資料夾"""
        self.logger.info(f"開始處理路徑: {self.base_folder}")

        if not os.path.exists(self.base_folder):
            self.logger.error(f"路徑不存在: {self.base_folder}")
            return

        for folder_name in os.listdir(self.base_folder):
            folder_path = os.path.join(self.base_folder, folder_name)
            if os.path.isdir(folder_path) and folder_name != "合併後PDF檔案":
                try:
                    output_filename = f"{folder_name}_合併.pdf"
                    self.logger.info(f"處理資料夾: {folder_name}")
                    pdf_count = self.merge_pdfs(
                        folder_path, output_filename, self.output_folder)
                    if pdf_count > 0:
                        self.logger.info(
                            f"完成 {folder_name} 資料夾處理，合併了 {pdf_count} 個PDF檔案")
                except Exception as e:
                    self.logger.error(f"處理 {folder_name} 時發生錯誤: {str(e)}")


def main():
    """主函數，執行PDF合併"""
    processor = PdfMergerProcessor()
    processor.logger.info("=== 開始執行PDF合併程式 ===")
    processor.process_directory()
    processor.logger.info("=== PDF合併程式執行完成 ===")


if __name__ == "__main__":
    main()



#  python pdf_merger.py
