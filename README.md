# 🏠 Landnote 不動產數位圖書館

歡迎來到 Landnote！這是一個自動化收集不動產專欄文章與考古題的知識庫，致力於提供最優質的閱讀與學習體驗。

<div align="center">

## 🚀 **[點此進入數位圖書館 (線上閱讀版)](https://tomisagoodguy.github.io/landnote/)** 🚀

</div>

---

## 📚 資源導覽 (Resources)

我們提供多種方式讓您獲取知識：

### 1. 線上閱讀 (推薦)

| 內容 | 說明 |
| :--- | :--- |
| **👉 [數位圖書館](https://tomisagoodguy.github.io/landnote/)** | **(首選)** 像電子書一樣的閱讀體驗，支援全文檢索、主題標籤與深色模式。 |
| **👉 [分組文章列表](landnotev3/data/real_estate_articles/README_grouped.md)** | 根據相似度透過AI自動分組的文章列表。 |

### 2. 檔案下載 (離線閱讀)

所有資料位於 `landnotev3` 目錄下：

| 內容 | 說明 |
| :--- | :--- |
| **👉 [PDF 彙整報告](landnotev3/data/real_estate_articles/pdf/)** | 已按年份自動整理好的文章 PDF 檔。 |
| **👉 [地政考古題](landnotev3/地政考古題/)** | 歷年地政類科考試題目 (包含各科目與[合併後PDF](landnotev3/地政考古題/合併後PDF檔案/))。 |
| **👉 [法律考古題](landnotev3/高點法律考古題/)** | 歷年法律類科考試題目 (包含各類別與[合併後PDF](landnotev3/高點法律考古題/合併後PDF檔案/))。 |
| **👉 [原始文章檔](landnotev3/data/real_estate_articles/articles/)** | 每一篇單獨的 Markdown 原始檔。 |

---

## ⚡ 自動更新機制 (Automation)

**本專案全自動運作，無需人工介入！**

- **更新頻率**：每週二、週四 早上 (配合老師發文時間)
- **運作流程**：GitHub Actions 會自動抓取最新文章 -> 分類整理 -> 更新網站 -> 產生 PDF。
- **如何確認**：只要看到上方的 [PDF 連結](landnotev3/data/real_estate_articles/pdf/) 或 [網站](https://tomisagoodguy.github.io/landnote/) 有新內容，即代表更新完成。

---

## 📜 版權與免責聲明

<div align="center" style="margin: 20px 0; padding: 10px; background-color: #fff3cd; border-radius: 5px;">
<strong>本專案純粹為練習網路爬蟲技術所建立，所有內容版權歸高點補習班所有。</strong><br>
如有需要相關教材，請直接向高點補習班購買正版課程與資料。<br>
本專案不作為任何商業用途，僅供技術學習參考。
</div>

---

## 💻 開發者指南 (Developer Guide)

如果您是開發者，想在本地端執行或貢獻程式碼：

### 1. 安裝環境

```bash
cd landnotev3
pip install -r requirements.txt
```

### 2. 常用指令 (在 `landnotev3` 目錄下執行)

- **啟動本機預覽 (數位圖書館)**：

  ```bash
  python src/landnote/main.py serve
  ```

  *(打開瀏覽器輸入 `http://127.0.0.1:8000` 即可)*

- **手動抓取文章並整理**：

  ```bash
  python src/landnote/main.py articles --update --auto-group
  ```

- **下載考古題**：

  ```bash
  python src/landnote/main.py exams --type land --years 5 --update
  python src/landnote/main.py exams --type law --max-pages 5
  ```

### 3. 技術架構

- **Entry Point**: `landnotev3/src/landnote/main.py`
- **Site Generator**: `landnotev3/src/landnote/processors/site_generator.py` (MkDocs)
- **CI/CD**: `.github/workflows/update_articles.yml`
