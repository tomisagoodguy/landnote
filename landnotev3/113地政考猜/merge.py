import os
from PyPDF2 import PdfMerger


def merge_pdfs_in_folder(folder_path, output_filename):
    # 創建一個PdfMerger物件
    merger = PdfMerger()

    # 獲取資料夾中所有的PDF檔案
    pdf_files = [f for f in os.listdir(
        folder_path) if f.lower().endswith('.pdf')]

    # 排序檔案名稱（可選）
    pdf_files.sort()

    # 如果沒有找到PDF檔案
    if not pdf_files:
        print("在指定資料夾中未找到PDF檔案")
        return

    # 合併所有PDF檔案
    for pdf in pdf_files:
        file_path = os.path.join(folder_path, pdf)
        merger.append(file_path)
        print(f"已添加: {pdf}")

    # 將合併後的PDF寫入到輸出檔案
    output_path = os.path.join(folder_path, output_filename)
    merger.write(output_path)
    merger.close()

    print(f"所有PDF檔案已成功合併到: {output_filename}")


# 使用當前目錄作為資料夾路徑
folder_path = "."  # 使用當前目錄
# 或者使用絕對路徑
# folder_path = r"C:\Users\tom89\Documents\GitHub\landnote\landnotev3\113地政考猜"
output_filename = "113地政考猜.pdf"  # 合併後的檔案名稱

merge_pdfs_in_folder(folder_path, output_filename)
