import os
import pikepdf
import logging

logger = logging.getLogger("PDFProcessor")

class PDFProcessor:
    """PDF處理類，負責PDF檔案的解鎖和儲存"""

    @staticmethod
    def unlock_pdf(input_path: str, output_path: str) -> bool:
        """解除PDF檔案的保護，使其可編輯、複製等"""
        try:
            with pikepdf.open(input_path) as pdf:
                pdf.save(output_path)
            logger.info(f"已解鎖: {os.path.basename(output_path)}")
            return True
        except Exception as e:
            logger.error(f"解鎖失敗: {e}")
            return False
