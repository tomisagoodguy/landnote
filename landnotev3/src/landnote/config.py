from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Exam Crawler Config
EXAM_BASE_URL = "http://goldensun.get.com.tw/exam/List.aspx"
LAW_EXAM_BASE_URL = "https://lawyer.get.com.tw/exam/List.aspx"
# 考選部考畢試題查詢（年份頁 ?y=西元年，考試頁 &e=考試代碼）
MOEX_EXAM_URL = "https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx"
MOEX_FILE_URL = "https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx"

# Article Crawler Config
ARTICLE_BASE_URL = "https://real-estate.get.com.tw/Columns/"
ARTICLE_AUTHORS = ["曾榮耀", "許文昌", "蘇偉強"]

# Directories
ARTICLES_DIR = DATA_DIR / "real_estate_articles" / "articles"
OUTPUT_DIR = DATA_DIR / "real_estate_articles"
# Jasper 不動產（jasper-realestate.com）文章：jasper_crawler 寫入、site_generator 讀取
JASPER_DIR = OUTPUT_DIR / "jasper"
# 估價師考古題主題題庫：exam_bank 寫入、site_generator 讀取
EXAM_BANK_FILE = DATA_DIR / "exam_bank" / "appraiser.json"
# 土地法規考古題閱讀版（逐題＋詳解）：exam_reader 寫入、site_generator 讀取
LAND_LAW_READER_FILE = DATA_DIR / "exam_bank" / "land_law.json"
# 法規修法時間軸（全國法規資料庫沿革）：law_timeline 寫入、site_generator 與 exam_bank 讀取
LAW_TIMELINE_FILE = DATA_DIR / "law_timeline.json"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
