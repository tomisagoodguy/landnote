# Landnote 不動產數位圖書館

自動收集不動產專欄文章與地政、不動產估價師考古題，整理成可線上閱讀、可下載 PDF 的備考資料庫。文章每週二、四更新，考古題每月更新，都由 GitHub Actions 自動執行。

**👉 [進入數位圖書館（線上閱讀）](https://tomisagoodguy.github.io/landnote/)**

---

## 收錄內容

| 內容 | 數量 | 位置 |
| :--- | :--- | :--- |
| 不動產專欄文章 | <!-- stats:articles -->996 篇<!-- /stats --> | [線上閱讀](https://tomisagoodguy.github.io/landnote/blog/)・[主題分組列表](landnotev3/data/real_estate_articles/README_grouped.md)・[原始 Markdown](landnotev3/data/real_estate_articles/articles/) |
| Jasper 不動產文章 | <!-- stats:jasper -->357 篇<!-- /stats --> | [線上閱讀](https://tomisagoodguy.github.io/landnote/jasper/)（法條逐條解說） |
| 文章分類總覽 | — | [依分類瀏覽](https://tomisagoodguy.github.io/landnote/blog/category/) |
| 文章年度合輯 PDF | 2014–2026 | [線上閱讀與下載](https://tomisagoodguy.github.io/landnote/tags/)（講義頁「年度合輯」） |
| 地政與估價師考古題 | <!-- stats:land_exams -->832 份<!-- /stats -->・<!-- stats:land_subjects -->74 科<!-- /stats --> | [科目目錄](landnotev3/地政考古題/README.md)・[整科合併 PDF](landnotev3/地政考古題/合併後PDF檔案/) |
| 法律考古題 | <!-- stats:law_exams -->2,626 份<!-- /stats --> | [線上目錄](https://tomisagoodguy.github.io/landnote/law-exams/)・[科目目錄](landnotev3/高點法律考古題/README.md)・[整科合併 PDF](landnotev3/高點法律考古題/合併後PDF檔案/)（每月自動更新） |

文章內文若引用的法條在發布後有修正，開頭會自動加上法規時效提醒（依全國法規資料庫的修正沿革）。文章與考古題雙向串連：文章底部列出「這篇文章考過哪些題目」，內文的法條連到站內的法條頁（現行條文、修正紀錄、歷屆考題、相關文章一次看）。

### 線上刷題

| 功能 | 內容 | 入口 |
| :--- | :--- | :--- |
| 逐題讀（附詳解） | 土地法規、土地登記、不動產估價、不動產投資、土地經濟與土地政策、土地利用與都市計畫、民法、稅法八科，逐題附老師擬答、可展開的相關專欄文章，並可依主題或依法條做跨年度比較 | [土地法規](https://tomisagoodguy.github.io/landnote/exam-reader/land-law/)・[土地登記](https://tomisagoodguy.github.io/landnote/exam-reader/registration/)・[估價](https://tomisagoodguy.github.io/landnote/exam-reader/appraisal/)・[投資](https://tomisagoodguy.github.io/landnote/exam-reader/investment/)・[土地經濟](https://tomisagoodguy.github.io/landnote/exam-reader/economics/)・[土地利用](https://tomisagoodguy.github.io/landnote/exam-reader/land-use/)・[民法](https://tomisagoodguy.github.io/landnote/exam-reader/civil-law/)・[稅法](https://tomisagoodguy.github.io/landnote/exam-reader/tax/) |
| 刷題計畫與隨機抽題 | 設定考試日期與科目，每天排好「到期複習＋新題」（最後一週只複習）；或跨科跨年隨機抽題，可只抽不熟／該複習的題目 | [開始刷題](https://tomisagoodguy.github.io/landnote/exam-reader/practice/) |
| 我的複習清單 | 題目可標記不熟／待複習／熟練，依間隔複習排下次複習日（1 天、3 天、7→14→30→60→120 天）；各題目頁可篩選只看不熟或該複習的題目；標記存在瀏覽器，可匯出／匯入搬到別台裝置 | [複習清單](https://tomisagoodguy.github.io/landnote/exam-reader/review/) |
| 法條頁 | 每條常考條文一頁：現行條文、修正日期、近 5 年出題熱度、老師相關文章、其他科目也考過、常一起考的條文 | 各科「依法條比較」，如[土地法第34條之1](https://tomisagoodguy.github.io/landnote/exam-reader/land-law/laws/D0060001-34-1/) |
| 近期修法考點 | 近三年每次修法中，歷屆考過與還沒考過的條文；舊題詳解可能已不適用 | [近期修法考點](https://tomisagoodguy.github.io/landnote/exam-reader/law-changes/) |
| 估價師專區 | 估價師專業科目依主題分類的題庫（附各主題出題年度統計）、合併 PDF 與延伸練習，手機優先版面 | [專區首頁](https://tomisagoodguy.github.io/landnote/appraiser/) |

### 用 Obsidian 讀考古題

逐題讀的八科考古題也能匯出成 [Obsidian](https://obsidian.md/) vault，適合想邊刷題邊寫自己筆記的人：

- **每題一則筆記**：題目、收合的答案與詳解、考點法條、歷屆相似題、老師相關文章連結、原卷 PDF。
- **法條筆記**：現行條文、修正日期，以及歷屆考過這一條的所有題目；出題後條文又修正過的會標出來。點開法條就能看到同一條歷年怎麼考。另有各科題數、近 5 年題數（frontmatter `近5年題數`，可用 Dataview 排序）、「常一起考的條文」連結與老師相關文章；近三年修正過的條文標有 `#近期修法`。首頁筆記列出近 5 年熱門法條與近期修法、而且考過的條文。
- **主題、考卷、科目筆記**：依主題或依考卷瀏覽。
- **複習追蹤**：每題有「狀態」欄位（未讀／不熟／待複習／熟練），搭配 Dataview 外掛，首頁會自動列出待複習清單。
**[下載 vault（zip，約 10 MB）](https://tomisagoodguy.github.io/landnote/downloads/landnote-obsidian.zip)**，解壓後在 Obsidian 選「開啟資料夾作為 vault」即可。每週二、四隨網站更新。

> 下載版更新時，解壓新版覆蓋舊版會清掉題目筆記裡的「狀態」與筆記。長篇心得建議另開資料夾寫，再用 `[[連結]]` 指向題目；或改用下方[開發者指南](#開發者指南)的 `obsidian` 指令在本機匯出，重新匯出時會保留「我的筆記」標記線以下的內容與「狀態」。

### 考古題範圍

| 考試 | 年度 | 來源 |
| :--- | :--- | :--- |
| 高考三級、普考（地政） | 民國 106–115 年 | 高點公職考古題 |
| 地方特考三、四、五等（地政） | 民國 106–114 年（五等至 112 年停辦） | 高點公職考古題 |
| 其他類科中含「估價／不動產／土地」的科目 | 依來源網站收錄 | 高點公職考古題 |
| **專技高考 不動產估價師**（7 科） | 民國 100–115 年 | 考選部題庫 |
| 專技普考 地政士、不動產經紀人 | 民國 106–115 年 | 考選部題庫 |

高點網站上失效或漏收的試題，已從[考選部題庫](https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx)補齊。

### 不動產估價師：整科刷題

每科歷屆試題合成一本 PDF，點擊即可下載：

| 科目 | 收錄 | 合併 PDF | 單份 |
| :--- | :--- | :--- | :--- |
| 不動產估價理論 | <!-- stats:subject=不動產估價理論 -->16 份<!-- /stats --> | [下載](landnotev3/地政考古題/%E5%90%88%E4%BD%B5%E5%BE%8CPDF%E6%AA%94%E6%A1%88/%E4%B8%8D%E5%8B%95%E7%94%A2%E4%BC%B0%E5%83%B9%E7%90%86%E8%AB%96_%E5%90%88%E4%BD%B5.pdf) | [瀏覽](landnotev3/地政考古題/%E4%B8%8D%E5%8B%95%E7%94%A2%E4%BC%B0%E5%83%B9%E7%90%86%E8%AB%96/) |
| 不動產估價實務 | <!-- stats:subject=不動產估價實務 -->16 份<!-- /stats --> | [下載](landnotev3/地政考古題/%E5%90%88%E4%BD%B5%E5%BE%8CPDF%E6%AA%94%E6%A1%88/%E4%B8%8D%E5%8B%95%E7%94%A2%E4%BC%B0%E5%83%B9%E5%AF%A6%E5%8B%99_%E5%90%88%E4%BD%B5.pdf) | [瀏覽](landnotev3/地政考古題/%E4%B8%8D%E5%8B%95%E7%94%A2%E4%BC%B0%E5%83%B9%E5%AF%A6%E5%8B%99/) |
| 不動產經濟學 | <!-- stats:subject=不動產經濟學 -->16 份<!-- /stats --> | [下載](landnotev3/地政考古題/%E5%90%88%E4%BD%B5%E5%BE%8CPDF%E6%AA%94%E6%A1%88/%E4%B8%8D%E5%8B%95%E7%94%A2%E7%B6%93%E6%BF%9F%E5%AD%B8_%E5%90%88%E4%BD%B5.pdf) | [瀏覽](landnotev3/地政考古題/%E4%B8%8D%E5%8B%95%E7%94%A2%E7%B6%93%E6%BF%9F%E5%AD%B8/) |
| 不動產投資分析 | <!-- stats:subject=不動產投資分析 -->22 份<!-- /stats -->（含高普考） | [下載](landnotev3/地政考古題/%E5%90%88%E4%BD%B5%E5%BE%8CPDF%E6%AA%94%E6%A1%88/%E4%B8%8D%E5%8B%95%E7%94%A2%E6%8A%95%E8%B3%87%E5%88%86%E6%9E%90_%E5%90%88%E4%BD%B5.pdf) | [瀏覽](landnotev3/地政考古題/%E4%B8%8D%E5%8B%95%E7%94%A2%E6%8A%95%E8%B3%87%E5%88%86%E6%9E%90/) |
| 民法物權與不動產法規 | <!-- stats:subject=民法物權與不動產法規 -->16 份<!-- /stats --> | [下載](landnotev3/地政考古題/%E5%90%88%E4%BD%B5%E5%BE%8CPDF%E6%AA%94%E6%A1%88/%E6%B0%91%E6%B3%95%E7%89%A9%E6%AC%8A%E8%88%87%E4%B8%8D%E5%8B%95%E7%94%A2%E6%B3%95%E8%A6%8F_%E5%90%88%E4%BD%B5.pdf) | [瀏覽](landnotev3/地政考古題/%E6%B0%91%E6%B3%95%E7%89%A9%E6%AC%8A%E8%88%87%E4%B8%8D%E5%8B%95%E7%94%A2%E6%B3%95%E8%A6%8F/) |
| 土地利用法規 | <!-- stats:subject=土地利用法規 -->16 份<!-- /stats --> | [下載](landnotev3/地政考古題/%E5%90%88%E4%BD%B5%E5%BE%8CPDF%E6%AA%94%E6%A1%88/%E5%9C%9F%E5%9C%B0%E5%88%A9%E7%94%A8%E6%B3%95%E8%A6%8F_%E5%90%88%E4%BD%B5.pdf) | [瀏覽](landnotev3/地政考古題/%E5%9C%9F%E5%9C%B0%E5%88%A9%E7%94%A8%E6%B3%95%E8%A6%8F/) |
| 國文（作文） | <!-- stats:subject=國文（作文） -->24 份<!-- /stats -->（108 年起，含地政士、經紀人） | [下載](landnotev3/地政考古題/%E5%90%88%E4%BD%B5%E5%BE%8CPDF%E6%AA%94%E6%A1%88/%E5%9C%8B%E6%96%87%EF%BC%88%E4%BD%9C%E6%96%87%EF%BC%89_%E5%90%88%E4%BD%B5.pdf) | [瀏覽](landnotev3/地政考古題/%E5%9C%8B%E6%96%87%EF%BC%88%E4%BD%9C%E6%96%87%EF%BC%89/) |

> 100–107 年的估價師國文科目名稱為「國文（作文與測驗）」，與其他考試同名科目放在同一資料夾。

---

## 自動更新

| 排程 | 內容 | Workflow |
| :--- | :--- | :--- |
| 每週二、四 20:00（台北） | 抓高點與 Jasper 新文章 → 主題分組 → 更新法規修正沿革 → 重建網站與年度 PDF → 部署 | [update_articles.yml](.github/workflows/update_articles.yml) |
| 每月 1 日 21:00（台北） | 下載新地政與法律考古題 → 重產有新題目科目的合併 PDF → 重建估價師題庫 | [update_exams.yml](.github/workflows/update_exams.yml) |

兩個排程跑完都會依實際資料重算本頁的收錄數字（[update_readme_stats.py](landnotev3/scripts/update_readme_stats.py)）。

兩者都可在 GitHub 的 **Actions** 頁面按 **Run workflow** 手動執行。考古題 workflow 只會補上來源網站有的新題目；來源網站若改版或漏題，需手動與考選部題庫核對。

---

## 版權與免責聲明

本專案為練習網路爬蟲技術而建立，文章與考古題解析的版權歸原作者及高點補習班所有，考試試題來源為考選部。如需相關教材，請向高點補習班購買正版課程與資料。本專案不作商業用途，僅供技術學習參考。

---

## 開發者指南

### 環境

需要 Python 3.10 以上與 [uv](https://docs.astral.sh/uv/)。所有指令在 `landnotev3/` 目錄下執行，依賴會依 [pyproject.toml](landnotev3/pyproject.toml) 與 `uv.lock` 自動安裝：

```bash
cd landnotev3
uv run python -m landnote.main --help
```

### 常用指令

```bash
# 抓取新文章並重新分組
uv run python -m landnote.main articles --update --auto-group

# 抓取新的 Jasper 文章
uv run python -m landnote.main jasper --update

# 只重新分組（產生 README_grouped.md、關鍵字頁、年度 PDF）
uv run python -m landnote.main group

# 下載法規修正沿革（文章的法規時效提醒用）
uv run python -m landnote.main laws

# 下載考古題（--years 為往回抓的年數，預設 10）
uv run python -m landnote.main exams --type land --update
uv run python -m landnote.main exams --type law --max-pages 5

# 重產有新考古題科目的合併 PDF（在 地政考古題/ 下執行）
cd 地政考古題 && uv run --with PyPDF2 --with pymupdf python pdf_merger.py --changed

# 從考古題 PDF 重建估價師主題題庫（data/exam_bank/*.json）
uv run --with pymupdf python -m landnote.main exambank

# 把逐題讀考古題匯出成 Obsidian vault（需先執行 site；預設輸出到 ~/Documents/Landnote考古題，可用 --out 指定）
uv run python -m landnote.main site
uv run python -m landnote.main obsidian

# 產生網站原始檔並在本機預覽（http://127.0.0.1:8000）
uv run --with "mkdocs<2.0" --with mkdocs-material python -m landnote.main serve
```

### 目錄結構

```text
landnote/
├── .github/workflows/          # 自動更新排程（文章、考古題）
└── landnotev3/
    ├── src/landnote/
    │   ├── main.py             # CLI 進入點
    │   ├── config.py           # 路徑與網址設定
    │   ├── crawlers/           # 文章、地政／估價師考古題、法律考古題爬蟲
    │   ├── processors/         # grouper（分組與 PDF）、site_generator（MkDocs 網站）、
    │   │                       # exam_bank（估價師題庫）、exam_reader（逐題讀）、law_timeline（法規時效提醒）、
    │   │                       # obsidian_vault（Obsidian vault 匯出）
    │   └── templates/          # 網站 CSS／JS
    ├── scripts/                # generate_pdfs（網頁轉 PDF）、update_readme_stats（README 數字）
    ├── data/
    │   ├── exam_bank/          # 估價師主題題庫 JSON
    │   └── real_estate_articles/
    │       ├── articles/       # 高點文章原始 Markdown 與圖片
    │       ├── jasper/         # Jasper 文章 Markdown
    │       ├── keywords/md/    # 各關鍵字的文章索引
    │       ├── merged/md/      # 相似標題自動分組的合併文章
    │       └── README_grouped.md  # 主題分組總目錄
    ├── 地政考古題/              # 依科目分資料夾，含 合併後PDF檔案/
    ├── 高點法律考古題/
    └── site_src/               # 由 site_generator 產生，不進版控，每次部署都會重建
```

網站樣式改在 `src/landnote/templates/static/css/extra.css`，頁面內容改在 `src/landnote/processors/site_generator.py`；`site_src/` 每次產生都會整個重建，不要直接修改。
