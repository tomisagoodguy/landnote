# 🏠 Landnote 不動產文章與考古題小幫手

歡迎使用 Landnote！這是一個自動化收集不動產專欄文章與考古題的工具。

<div align="center">

## 🚀 **[點此查看最新文章整理 (PDF)](data/real_estate_articles/merged/pdf/)** 🚀

</div>

---

## 🎯 快速傳送門 (點擊直接進入)

這裡已經幫您整理好所有檔案，點擊下方的連結即可直接查看：

### 📚 不動產專欄文章

| 內容 | 說明 |
| :--- | :--- |
| **👉 [自動整理好的 PDF 報告](data/real_estate_articles/merged/pdf/)** | **(推薦)** 包含曾榮耀、許文昌等老師的文章，已按主題合併 |
| **👉 [原始 Markdown 文章](data/real_estate_articles/articles/)** | 每一篇單獨的文章原始檔 |
| **👉 [按關鍵字分類](data/real_estate_articles/keywords/md/)** | 依照主題關鍵字分類的文章列表 |

### 📝 考古題下載

| 內容 | 說明 |
| :--- | :--- |
| **👉 [地政考古題](data/地政考古題/)** | 歷年地政類科考試題目 (PDF) |
| **👉 [法律考古題](data/高點法律考古題/)** | 歷年法律類科考試題目 (PDF) |

---

## ⚡ 自動更新機制

**您不需要手動操作！**

本專案已設定 **GitHub Actions 自動排程**：

- **更新時間**：每週二、週四 早上 (配合老師發文時間)
- **運作流程**：
  1. 系統自動抓取最新文章
  2. 自動分類、製作 PDF
  3. 自動上傳回這裡
- **如何確認**：只要看到上方的 [PDF 連結](data/real_estate_articles/merged/pdf/) 有新檔案，就是更新完成了！

---

## 💻 進階：手動執行 (工程師專用)

如果您想在自己的電腦上手動跑程式，請參考以下指令：

### 1. 安裝環境

```bash
pip install -r requirements.txt
```

### 2. 常用指令

- **抓取最新文章並整理**：

  ```bash
  python src/landnote/main.py articles --update --auto-group
  ```

- **下載地政考古題**：

  ```bash
  python src/landnote/main.py exams --type land --years 5 --update
  ```

- **下載法律考古題**：

  ```bash
  python src/landnote/main.py exams --type law --max-pages 5
  ```

---

## 🛠 技術資訊 (Technical Details)

- **Entry Point**: `src/landnote/main.py`
- **Modules**: `core` (Base scraper), `crawlers` (Specific logic), `processors` (PDF gen)
- **CI/CD**: `.github/workflows/update_articles.yml`
