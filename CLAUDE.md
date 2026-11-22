# Landnote 不動產數位圖書館

## 專案本質

把「散在補習班網站的不動產專欄文章與考古題」變成「可搜尋、可連續閱讀、可下載 PDF 的備考資料庫」。本質是一條**全自動資料管線**：爬蟲 → 整理成 Markdown → 產生 MkDocs 網站 → 部署 GitHub Pages，全部由 GitHub Actions 排程執行，沒有後端、沒有資料庫。

- **為何用 MkDocs Material**：純靜態、免伺服器、內建 blog / 搜尋 / 標籤，GitHub Pages 直接託管，零成本。
- **為何資料進 git**：文章與 PDF 就是產品本身，git 歷史即更新紀錄，CI 每次跑完自動 commit。
- **目標讀者**：準備地政高普考、地方特考、不動產估價師的考生（手機與桌機閱讀）。

線上網址：https://tomisagoodguy.github.io/landnote/

## 技術堆疊

| 技術 | 版本 | 用途 |
|------|------|------|
| Python | **CI 用 3.10**（本機 3.14） | 爬蟲與網站產生器；**不可用 3.11+ 語法** |
| uv | 0.11 | 本機套件管理（`landnotev3/pyproject.toml`） |
| MkDocs | **`<2.0`**（目前 1.6） | 靜態網站產生 |
| mkdocs-material | 9.x | 主題與 blog 外掛（分頁、分類、摘要） |
| requests / BeautifulSoup4 | — | 爬取文章與考古題 |
| fuzzywuzzy | — | 文章相似度分組（`grouper.py`） |
| pikepdf / PyPDF2 | — | 考古題合併 PDF |
| Playwright（Chromium） | — | CI 中把建好的網頁轉成 PDF |
| ghp-import | — | 把 `site/` 推到 `gh-pages` 分支 |

## 目錄結構

```
landnote/
├── CLAUDE.md
├── README.md                         # 對外說明（收錄數量、下載連結）
├── .github/workflows/
│   ├── update_articles.yml           # 週二、四：爬文章 → 分組 → 產網站 → 部署
│   └── update_exams.yml              # 每月 1 日：下載地政＋法律考古題 → 合併 PDF
└── landnotev3/
    ├── pyproject.toml                # uv 專案設定、ruff 規則
    ├── src/landnote/
    │   ├── main.py                   # CLI 入口（articles / exams / group / site / serve）
    │   ├── config.py                 # 路徑常數（DATA_DIR、ARTICLES_DIR…）
    │   ├── core/scraper.py           # 爬蟲基底類別
    │   ├── crawlers/                 # article.py（專欄文章）、exam_land.py、exam_law.py、jasper_crawler.py
    │   ├── processors/
    │   │   ├── grouper.py            # 相似文章分組、關鍵字頁
    │   │   └── site_generator.py     # ★ 產生 site_src/docs 全部內容與 mkdocs.yml
    │   ├── templates/static/         # ★ 前端原始檔：js/study_tools.js、css/extra.css
    │   └── utils/                    # logger、PDF、文字處理
    ├── scripts/generate_pdfs.py      # mkdocs build 後把網頁轉 PDF
    ├── data/real_estate_articles/
    │   ├── articles/                 # 爬下來的原始文章 Markdown（產生器的輸入）
    │   ├── merged/ keywords/        # grouper 產出
    │   └── README_grouped.md
    ├── site_src/                     # ⚠ 全是產生器輸出，不進版控（.gitignore），CI 每次部署重建
    │   ├── mkdocs.yml                # 由 site_generator 產生
    │   ├── docs/                     # blog/posts、tags.md、review/、index.md、javascripts/、stylesheets/
    │   └── site/                     # mkdocs build 輸出（.gitignore）
    ├── 地政考古題/                    # 依科目分資料夾的 PDF、pdf_merger.py、合併後PDF檔案/
    └── 高點法律考古題/                # 依考試類組/科目分資料夾，每月隨 update_exams.yml 更新
```

架構模式：**單向資料管線**（crawlers → data/ → processors → site_src/ → gh-pages），每一段只讀上一段的輸出。

## 常用指令

所有指令在 **repo 根目錄**執行。

**資料更新**
```bash
uv run --project landnotev3 python landnotev3/src/landnote/main.py articles --update --auto-group   # 抓新文章並分組
uv run --project landnotev3 python landnotev3/src/landnote/main.py group                           # 只重跑分組（--threshold 預設 80）
uv run --project landnotev3 python landnotev3/src/landnote/main.py exams --type land --update      # 下載新地政考古題
```

**網站產生與預覽**
```bash
uv run --project landnotev3 python landnotev3/src/landnote/main.py site                            # 重產 site_src/docs 與 mkdocs.yml（約 10 秒）
cd landnotev3/site_src && NO_MKDOCS_2_WARNING=1 uv run --with "mkdocs<2.0" --with mkdocs-material mkdocs serve   # 本機預覽 http://127.0.0.1:8000/landnote/
cd landnotev3/site_src && uv run --with "mkdocs<2.0" --with mkdocs-material mkdocs build -d <暫存目錄>           # 建置到暫存目錄驗證
```

**考古題合併 PDF**
```bash
cd landnotev3/地政考古題 && uv run --with PyPDF2 --with pymupdf python pdf_merger.py --changed     # 只重產有新題目的科目
```

**格式化 / Lint**
```bash
cd landnotev3 && uv run --with ruff ruff check --fix src && uv run --with ruff ruff format src
```

**測試**：`landnotev3/tests/` 目前是空的。前端改動用 Playwright 腳本對 `mkdocs build` 的輸出實測（以 `python -m http.server` 提供，`chromium.launch(channel="chrome")`）。

**部署**：不手動部署。推到 `main` 後等 `update_articles.yml` 排程，或到 GitHub Actions 頁面按 **Run workflow**。

## 開發流程

1. **改網站內容或版型** → 改 `landnotev3/src/landnote/processors/site_generator.py`（文章處理、摘要分隔、mkdocs.yml、首頁、標籤頁、考古題頁）。
2. **改前端行為或樣式** → 改 `landnotev3/src/landnote/templates/static/js/study_tools.js` 或 `templates/static/css/extra.css`，產生器會複製成 `site_src/docs/javascripts/extra.js`、`stylesheets/extra.css`。
3. **改爬蟲** → `landnotev3/src/landnote/crawlers/`；改分組 → `processors/grouper.py`。
4. 跑 `main.py site` 再 `mkdocs build` 到暫存目錄，用瀏覽器實測。
5. **只 commit 原始碼**（用 pathspec：`git commit -- <檔案>`）。`site_src/` 已不進版控；`data/` 的產出變動交給 CI 重產並自動 commit。
6. 推送前 `git pull --rebase`：CI 會自動 commit `docs: auto-update articles and reports [skip ci]`，常常比本機新。

各層邊界：crawlers 只寫 `data/`；grouper 只讀 `data/articles` 寫 `data/` 其他子目錄；site_generator 只讀 `data/articles` 寫 `site_src/`；前端 JS 只在瀏覽器端加功能，不改 Markdown。

## 重要文件索引

1. **MUST READ** `landnotev3/src/landnote/processors/site_generator.py`：網站一切的來源，`mkdocs.yml` 也由此產生。
2. **MUST READ** `.github/workflows/update_articles.yml`：正式環境實際執行的步驟與套件清單。
3. `landnotev3/src/landnote/templates/static/js/study_tools.js`：學習工具（PDF、熟記狀態、法條連結）與 blog 無限捲動。
4. `landnotev3/src/landnote/crawlers/article.py`：文章 Markdown 格式（`## 文章資訊` 區塊、`[圖片N]` 佔位、`## 文章圖片`）的源頭。
5. `landnotev3/src/landnote/config.py`：所有資料路徑。
6. `README.md`：對外收錄數量與下載連結，內容變動時要同步。

## 常見錯誤與原則

| ❌ 錯誤 | ✅ 正確 |
|--------|--------|
| 直接改 `site_src/mkdocs.yml`、`site_src/docs/**` | 改 `site_generator.py` 或 `templates/static/`；docs 下次產生就被覆蓋 |
| 改 `site_src/docs/javascripts/extra.js` | 改 `templates/static/js/study_tools.js`（兩者內容相同，後者才是原始檔） |
| 本機跑完 `main.py articles`／`group` 後 `git add .` | 只 commit 原始碼；`data/` 一次產生會動到上千個檔案 |
| 想把 `site_src/` 加回版控 | 它由 `site_generator` 每次整個刪除重建，CI 部署不讀 repo 裡的版本 |
| 新增 Python 依賴只改 `pyproject.toml` | `update_articles.yml` 用 **pip 寫死套件清單**，要一起加 |
| 用 `tomllib`、`except*`、`typing.Self` 等 3.11+ 功能 | CI 是 Python 3.10（`match`、`X \| Y` 型別可用） |
| 在 `landnotev3/` 根目錄留除錯腳本 | 一次性腳本放暫存目錄，正式工具放 `scripts/` |
| 腳本 `print` 中文或 emoji 直接跑 | Windows 主控台是 cp950，開頭加 `sys.stdout.reconfigure(encoding="utf-8")` |

核心原則：
1. **產生器是唯一事實來源**：任何會出現在網站上的東西，都從 `src/landnote` 改，不從輸出改。
2. **資料由 CI 擁有**：`data/` 與 `site_src/docs` 的日常變動由 Actions 產生並 commit，人工 commit 只放程式碼。
3. **可能有其他工作同時改這個 repo**：commit 前看 `git status`，只提交自己改的檔案，不要還原別人的變動。

## 網站行為備忘

- blog 每頁 10 篇（`pagination_per_page`），前端用無限捲動接下一頁；分頁列保留給無 JS 與搜尋引擎。
- 文章開頭的 `## 內文` 由產生器移除；**不插入 `<!-- more -->`**，blog 列表直接顯示全文、沒有「繼續閱讀」（使用者要求）。法規時效提醒放在內文開頭。
- `site_url` 有 `/landnote/` 子路徑，本機直接以 `site/` 為根目錄提供時，部分絕對路徑資源會 404，屬正常現象。
