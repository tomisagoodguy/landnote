# Landnote Unified Crawler

A modular and unified crawler system for archiving land registration articles and exam papers.

## Project Structure

```bash
landnote/src/landnote
├── config.py         # Central configuration
├── core/             # Base scraper and core logic
├── crawlers/         # Specific crawler implementations
│   ├── article.py    # Real estate article crawler
│   ├── exam_land.py  # Land exam paper crawler
│   └── exam_law.py   # Law exam paper crawler
├── processors/       # Data processing and analysis
│   └── grouper.py    # Article grouping and PDF generation
└── utils/            # Helper utilities (PDF, Text, Logger, etc.)
```

## Setup

1. **Install Dependencies**:
   Ensure you have Python 3.10+ installed.
   ```bash
   pip install -r requirements.txt
   # OR use the project dependencies directly
   pip install requests pandas beautifulsoup4 pikepdf tqdm openpyxl Pillow fake-useragent urllib3 python-dotenv fuzzywuzzy python-Levenshtein reportlab
   ```

2. **Environment Variables**:
   Create a `.env` file in the root if needed (see `config.py` for variables).

## Usage

The project uses a unified CLI `src/landnote/main.py`.

### 1. Crawl Real Estate Articles
Fetch articles from configured authors.
```bash
# Update new articles only
python src/landnote/main.py articles --update

# Crawl all articles (full scan)
python src/landnote/main.py articles

# Crawl and auto-group results
python src/landnote/main.py articles --update --auto-group
```

### 2. Crawl Exam Papers
Download exam PDFs for Land Administration (地政) or Law (法律).

**Land Exams:**
```bash
# Download last 10 years of exams, skip existing
python src/landnote/main.py exams --type land --years 10 --update
```

**Law Exams:**
```bash
# Download law exams up to page 5
python src/landnote/main.py exams --type law --max-pages 5
```

### 3. Group Articles (Post-processing)
Group downloaded articles by title similarity and generate PDF reports.
```bash
python src/landnote/main.py group --threshold 80
```

## Development

- **Add New Crawler**: Create a new file in `crawlers/`, inherit from `BaseScraper`, and register it in `main.py`.
- **Utils**: reusable logic for PDF unlocking, text processing, etc., is in `utils/`.
