import logging
import sys
from pathlib import Path
from datetime import datetime

class Logger:
    @staticmethod
    def setup_logger(name: str, log_dir: Path, level=logging.INFO):
        """設定日誌系統"""
        logger = logging.getLogger(name)
        if logger.hasHandlers():
            return logger
            
        logger.setLevel(level)

        file_path = log_dir / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        # 確保日誌目錄存在
        log_dir.mkdir(parents=True, exist_ok=True)

        handlers = [
            logging.FileHandler(file_path, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        for handler in handlers:
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            
        return logger
