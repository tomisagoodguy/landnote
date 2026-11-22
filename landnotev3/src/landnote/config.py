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

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
