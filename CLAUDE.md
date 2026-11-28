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
    │   ├── main.py                   # CLI 入口（articles / jasper / exams / group / exambank / laws / obsidian / site / serve）
    │   ├── config.py                 # 路徑常數（DATA_DIR、ARTICLES_DIR…）
    │   ├── core/scraper.py           # 爬蟲基底類別
    │   ├── crawlers/                 # article.py（專欄文章）、exam_land.py、exam_law.py、jasper_crawler.py
    │   ├── processors/
    │   │   ├── grouper.py            # 相似文章分組、關鍵字頁
    │   │   ├── site_generator.py     # ★ 產生 site_src/docs 全部內容與 mkdocs.yml
    │   │   ├── exam_bank.py          # 估價師主題題庫（exambank 指令建 JSON；產生器寫 exam-bank/ 頁）
    │   │   ├── exam_reader.py        # 逐題讀各科頁面（exam-reader/<科目>/，科目清單見 READERS）與總覽頁，附擬答與相關文章
    │   │   ├── interpretation.py     # 釋字／憲判字字號擷取與正規化（解釋頁由 exam_reader 產生）
    │   │   ├── obsidian_vault.py     # obsidian 指令：逐題讀考古題 → Obsidian vault（題目／法條／主題互連）
    │   │   ├── mindmap.py            # 考點心智圖（各科：法規編章節／主題；跨科目概念），exam-reader/mindmap/
    │   │   ├── law_timeline.py       # 法規修正沿革、現行條文與編章節（chapters）→ 法規時效提醒、心智圖骨架
    │   │   └── my_notes.py           # 我的法條筆記（data/my_notes）→ notes/ 各法規頁，並掛到逐題讀法條頁
    │   ├── templates/static/         # ★ 前端原始檔：js/study_tools.js、css/extra.css
    │   └── utils/                    # logger、PDF、文字處理
    ├── scripts/
    │   ├── generate_pdfs.py          # mkdocs build 後把網頁轉 PDF
    │   └── update_readme_stats.py    # 重算 README 的 <!-- stats:key --> 數字（兩個 workflow 都跑）
    ├── data/
    │   ├── exam_bank/                # 估價師題庫 JSON（update_exams.yml 每月重建）
    │   ├── my_notes/                 # ★ 人工維護：使用者手整的地政士／經紀人重點（notes.json＋images/），CI 不改
    │   └── real_estate_articles/
    │       ├── articles/             # 爬下來的高點文章 Markdown（產生器的輸入）
    │       ├── jasper/               # Jasper 不動產文章 Markdown
    │       ├── merged/ keywords/     # grouper 產出
    │       └── README_grouped.md
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
uv run --project landnotev3 python landnotev3/src/landnote/main.py articles --refetch 902606 916696 # 修正解析錯誤後強制重抓指定文章（覆寫原檔，CI 不會自己重抓）
uv run --project landnotev3 python landnotev3/src/landnote/main.py exams --type land --update      # 下載新地政考古題
uv run --project landnotev3 python landnotev3/src/landnote/main.py jasper --update                 # 抓新 Jasper 文章
uv run --project landnotev3 python landnotev3/src/landnote/main.py laws                            # 下載法規修正沿革（時效提醒用）
uv run --project landnotev3 --with pymupdf python landnotev3/src/landnote/main.py exambank         # 重建估價師題庫 JSON
uv run --no-project python landnotev3/scripts/update_readme_stats.py --check                       # 檢查 README 數字是否過期
```

**網站產生與預覽**
```bash
uv run --project landnotev3 python landnotev3/src/landnote/main.py site                            # 重產 site_src/docs 與 mkdocs.yml（約 10 秒）
cd landnotev3/site_src && NO_MKDOCS_2_WARNING=1 uv run --with "mkdocs<2.0" --with mkdocs-material mkdocs serve   # 本機預覽 http://127.0.0.1:8000/landnote/
cd landnotev3/site_src && uv run --with "mkdocs<2.0" --with mkdocs-material mkdocs build -d <暫存目錄>           # 建置到暫存目錄驗證
```

**Obsidian 考古題 vault**
```bash
uv run --project landnotev3 python landnotev3/src/landnote/main.py obsidian                        # 匯出到 ~/Documents/Landnote考古題（約 50 秒；需先跑 site，可加 --out <目錄>）
```
vault 在 repo 外、不進版控；重新匯出只覆寫自動產生的部分，保留每則筆記的 `狀態` 欄位與「我的筆記」標記線以下的內容。CI（`update_articles.yml`）在 `mkdocs build` 前以 `obsidian --zip site_src/docs/downloads/landnote-obsidian.zip` 產生下載檔，逐題讀總覽頁連到它（路徑常數 `exam_reader.OBSIDIAN_ZIP`）。

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

各層邊界：crawlers 只寫 `data/`；grouper 只讀 `data/articles` 寫 `data/` 其他子目錄；site_generator 只讀 `data/`（articles、jasper、exam_bank、法規沿革）與考古題資料夾，寫 `site_src/`；前端 JS 只在瀏覽器端加功能，不改 Markdown。

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
| 直接改 `site_src/**`（`mkdocs.yml`、`docs/javascripts/extra.js`…） | 改 `site_generator.py` 或 `templates/static/`（如 `js/study_tools.js`）；輸出下次產生就被覆蓋 |
| 想把 `site_src/` 加回版控 | 它由 `site_generator` 每次整個刪除重建，CI 部署不讀 repo 裡的版本 |
| README 加新的 `<!-- stats:xxx -->` 標記卻沒改腳本 | `update_readme_stats.py` 遇到未知標記直接報錯，CI 會失敗；要在 `collect_stats()` 一起加 |
| 新增 Python 依賴只改 `pyproject.toml` | `update_articles.yml` 用 **pip 寫死套件清單**，要一起加 |
| 用 `tomllib`、`except*`、`typing.Self` 等 3.11+ 功能 | CI 是 Python 3.10（`match`、`X \| Y` 型別可用） |
| 在 `landnotev3/` 根目錄留除錯腳本 | 一次性腳本放暫存目錄，正式工具放 `scripts/` |
| 爬蟲佔位字用英文開頭（如 `TABLE_PLACEHOLDER_1`） | `TextUtils.format_content` 會把英文字母開頭的行當成「A. 」列表改寫；佔位字用全形括號包住（`〔表格1〕`） |
| 心智圖 JSON 的節點少了 `children` 就直接交給 markmap | 葉節點為省空間不寫 `children`，前端 `mmColorize` 會補空陣列；沒補時「全部展開」會拋 `reading 'map'` |
| Playwright 用 `a[href='#x']` 找站內連結 | Material instant navigation 會把 href 改成絕對網址，改用 `a[href$='#x']` |

核心原則：
1. **產生器是唯一事實來源**：任何會出現在網站上的東西，都從 `src/landnote` 改，不從輸出改。
2. **資料由 CI 擁有**：`data/` 與 `site_src/docs` 的日常變動由 Actions 產生並 commit，人工 commit 只放程式碼。
3. **可能有其他工作同時改這個 repo**：commit 前看 `git status`，只提交自己改的檔案，不要還原別人的變動。

## 網站行為備忘

- blog 每頁 10 篇（`pagination_per_page`），前端用無限捲動接下一頁；分頁列保留給無 JS 與搜尋引擎。
- 文章開頭的 `## 內文` 由產生器移除；**不插入 `<!-- more -->`**，所有列表（blog 首頁、分類頁、最新文章、Jasper）都直接顯示全文、沒有「繼續閱讀」（使用者要求過三次）。法規時效提醒放在內文開頭。
- 高點專欄與 Jasper 是**兩個獨立 blog**（`blog/`、`jasper/`），任何列表都不要混排。
- Jasper 文章：標題含「上榜心得」不收；文末「免費諮詢｜Line 官方帳號｜Facebook 粉絲專頁」推廣區塊要移除（`site_generator.py` 的 Jasper 處理段）。
- 逐題讀的熟練度標記（不熟／待複習／熟練）存在瀏覽器 localStorage `qmark_v1`，以題目卡的 `data-q`（考卷 id-題號）為鍵，各頁共用；彙整在 `exam-reader/review/`。改題目卡 HTML 時要保留 `_mark_attrs()` 產生的屬性。
  - 每筆 `{s, t, h, d, n}`：`d` 標記日（本地日期）、`n` 連續熟練次數；下次複習日由 `study_tools.js` 的 `QM_INTERVALS` 推算（不熟 1、待複習 3、熟練 7→14→30→60→120 天）。到期再按同鈕＝記錄複習，未到期再按＝取消。
  - 題目 5 題以上的頁面有篩選列（`initMarkFilter`）；`exam-reader/practice/`（`initPractice`）讀 `exam-reader/questions.json` 抽題，再到考卷頁抓題目卡就地顯示，計畫設定存 `qm_plan_v1`、當天題目存 `qm_today_v1`。
- 知識串連都在 `exam_reader.write_pages` 寫完各科之後做：`_link_articles` 改寫文章（文末 `<!-- exam-backlinks -->` 區塊列歷屆考題、內文法條改連站內法條頁；`ArticleIndex` 讀文章時會剔除該區塊）、`_link_law_families` 把法條頁的 `<!-- other-families -->` 換成「其他科目也考過」、`_write_law_changes` 產生近期修法考點頁。法條頁要等考卷頁寫完才寫（相關文章用到題目→文章的推薦結果）。
  - 大法官解釋：`_write_interpretations` 把題目／詳解／文章提到的釋字、憲判字寫成 `exam-reader/interpretations/<j400|c112-20>/`（文章摘句、同題引用的法條、歷屆考題）；題目卡加字號標籤、文章內字號改連解釋頁、法條頁的 `<!-- interpretations -->` 換成「相關大法官解釋」。憲判字網址無法由字號推得，只連判決列表。
- 考古題以**網頁逐題閱讀、可跨年度比較**為主（逐題讀、主題題庫），合併 PDF 是輔助；題目與擬答抽取用規則式解析，不用 LLM。
- 考點心智圖（`mindmap.py`，site_generator 在逐題讀之後呼叫）：頁面只放 `.lm-mindmap` 容器（`data-src` JSON、`data-level` 預設顯示層數**含根節點**），`study_tools.js` 的 `initMindmaps` 只在有容器的頁面從 jsDelivr 載入 d3 與 markmap-view（版本寫死在 `MM_SCRIPTS`）。
  - 法規骨架來自 `data/law_articles.json` 的 `chapters`（`laws` 指令寫入）；舊檔沒有時條文直接掛在法規下，不會壞。
  - 跨科目概念 = `CONCEPTS` 關鍵詞（只比對題目與選項）＋兩科以上考過且 ≥ 4 題的法條，只收兩科以上出現的；概念 id（`k<序號>`）依清單順序，**新概念加在清單最後**，網址才不會變。
  - 題目節點帶 `data-q`，依 `qmark_v1` 熟練度上色；各科題目總覽頁的心智圖入口由 `_link_family_indexes` 插在「跨年度比較」那行之前。
- 我的法條筆記（`my_notes.py`，在逐題讀之後呼叫）：`data/my_notes/notes.json` 每則筆記是 `article`（條號、重要度、口訣 memo、整理當時抄的條文 text）或 `topic`（Markdown body、refs、exams）。
  - 條文卡每次產生都跟 `law_articles.json` **逐段嚴格比對**（只忽略標點），不同就標「條文已修正」——一兩字的修正（如「百分之二之罰鍰」→「百分之二以下之罰鍰」）正是考點，不要改回模糊比對。
  - 主題卡無法比對，引用條文在 `NOTES_AS_OF`（原檔考題最晚 109 年 → 2021-01-01）之後修正的標橘色。
  - 法條頁的 `<!-- my-notes -->`（`exam_reader.MY_NOTES_MARK`）由這裡換成「我的筆記」區塊。
- `site_url` 有 `/landnote/` 子路徑，本機直接以 `site/` 為根目錄提供時，部分絕對路徑資源會 404，屬正常現象。
