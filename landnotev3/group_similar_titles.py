import os
from pathlib import Path
import re
from typing import List, Dict, Set
from fuzzywuzzy import fuzz
from datetime import datetime
import logging
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate
from reportlab.platypus.frames import Frame
from reportlab.pdfgen import canvas
from collections import defaultdict


# 自訂文件模板，用於添加頁碼
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        """添加頁碼到每一頁"""
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.setFont("Helvetica", 9)
            # 在頁面底部中間添加頁碼
            page_width = self._pagesize[0]
            self.drawCentredString(
                page_width / 2, 2*cm, f"{self._pageNumber}")
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)


class ArticleGrouper:
    def __init__(self, articles_dir: str = "real_estate_articles/articles", output_dir: str = "real_estate_articles"):
        """初始化分組器"""
        self.articles_dir = Path(articles_dir)
        self.output_dir = Path(output_dir)

        # 獨立資料夾設置
        self.merged_md_dir = self.output_dir / "merged/md"  # 合併的 MD 檔案
        self.merged_pdf_dir = self.output_dir / "merged/pdf"  # 合併的 PDF 檔案
        self.keyword_md_dir = self.output_dir / "keywords/md"  # 關鍵詞的 MD 檔案
        self.keyword_pdf_dir = self.output_dir / "keywords/pdf"  # 關鍵詞的 PDF 檔案
        self.pdf_dir = self.output_dir / "pdf"  # 年份分組的 PDF 檔案

        self.image_dir = self.articles_dir / "images"
        self.similarity_threshold = 80
        self.articles = []
        self.logger = self.setup_logger()
        self.chinese_font_name = 'Helvetica'  # 預設字型

        # 關鍵詞分類相關設定
        self.keyword_groups = defaultdict(list)  # 用於存儲按關鍵詞分類的文章
        self.keyword_counts = defaultdict(int)   # 用於統計各關鍵詞出現次數

        # 嘗試註冊中文字型，使用完整路徑
        self._setup_chinese_font()

    def _setup_chinese_font(self):
        """設置中文字型，嘗試多個可能的路徑"""
        # 常見的中文字型路徑
        possible_font_paths = [
            "C:/Windows/Fonts/msjh.ttf",  # Windows 微軟正黑體
            "C:/Windows/Fonts/msyh.ttf",  # Windows 微軟雅黑
            "C:/Windows/Fonts/SimSun.ttc",  # Windows 宋體
            "C:/Windows/Fonts/SimHei.ttf",  # Windows 黑體
            "/System/Library/Fonts/PingFang.ttc",  # macOS
            "/usr/share/fonts/truetype/arphic/uming.ttc",  # Linux
        ]

        for font_path in possible_font_paths:
            try:
                if os.path.exists(font_path):
                    font_name = os.path.basename(font_path).split('.')[0]
                    pdfmetrics.registerFont(TTFont(font_name, font_path))
                    self.chinese_font_name = font_name
                    self.logger.info(f"成功載入中文字型：{font_path}")
                    return
            except Exception as e:
                self.logger.warning(f"嘗試載入字型 {font_path} 失敗：{str(e)}")

        # 如果所有嘗試都失敗，使用 ReportLab 內建的字型
        try:
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
            self.chinese_font_name = 'STSong-Light'
            self.logger.info("使用 STSong-Light 作為中文字型")
        except Exception as e:
            self.logger.warning(f"無法載入 CID 字型：{str(e)}，將使用預設字型 Helvetica")

    def setup_logger(self):
        """設定日誌系統"""
        logger = logging.getLogger('ArticleGrouper')
        logger.handlers = []
        logger.setLevel(logging.INFO)
        log_dir = self.output_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / \
            f"grouper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        handlers = [
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s')
        for handler in handlers:
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def read_markdown_files(self):
        """讀取所有 Markdown 檔案並提取標題與元資料，包括關鍵詞"""
        self.articles = []
        for md_file in self.articles_dir.glob("*.md"):
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
                    title = title_match.group(
                        1).strip() if title_match else md_file.stem
                    article_no_match = re.search(r'文章編號：(\d+)', content)
                    article_no = article_no_match.group(
                        1) if article_no_match else md_file.stem.split('_')[0]
                    date = None
                    date_obj = None
                    date_patterns = [
                        (r'發布日期：(\d{4}/\d{2}/\d{2})', ['%Y/%m/%d']),
                        (r'發布日期：(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?)',
                         ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d']),
                        (r'發布日期：(\d{4}年\d{2}月\d{2}日)', ['%Y年%m月%d日']),
                        (r'發布日期：(\d{2}/\d{2}/\d{4})', ['%d/%m/%Y']),
                        (r'日期：(\d{4}/\d{2}/\d{2})', ['%Y/%m/%d']),
                        (r'日期：(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?)',
                         ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d']),
                        (r'日期：(\d{4}年\d{2}月\d{2}日)', ['%Y年%m月%d日']),
                    ]
                    for pattern, formats in date_patterns:
                        date_match = re.search(pattern, content)
                        if date_match:
                            date = date_match.group(1)
                            for fmt in formats:
                                try:
                                    date_obj = datetime.strptime(date, fmt)
                                    break
                                except ValueError:
                                    continue
                            if date_obj:
                                self.logger.info(
                                    f"檔案 {md_file.name} 日期匹配：{date}")
                                break
                    if not date_obj:
                        timestamp = md_file.stat().st_mtime
                        date_obj = datetime.fromtimestamp(timestamp)
                        date = date_obj.strftime('%Y-%m-%d')
                        self.logger.warning(
                            f"檔案 {md_file.name} 未找到有效日期，使用修改時間：{date}")

                    # 提取關鍵詞
                    keywords = []
                    keywords_match = re.search(r'- 關鍵詞：(.*?)(?:\n|$)', content)
                    if keywords_match:
                        keywords_text = keywords_match.group(1).strip()
                        # 處理不同的分隔符號
                        for separator in [',', '，', '、', ';', '；', ' ']:
                            if separator in keywords_text:
                                keywords = [k.strip() for k in keywords_text.split(
                                    separator) if k.strip()]
                                break
                        # 如果沒有找到分隔符號，將整個字串視為一個關鍵詞
                        if not keywords and keywords_text:
                            keywords = [keywords_text]

                        self.logger.info(f"檔案 {md_file.name} 關鍵詞：{keywords}")

                    article_data = {
                        'file_path': md_file,
                        'title': title,
                        'article_no': article_no,
                        'date': date,
                        'date_obj': date_obj,
                        'content': content,
                        'keywords': keywords
                    }

                    self.articles.append(article_data)

                    # 將文章按關鍵詞分類
                    if keywords:
                        for keyword in keywords:
                            self.keyword_groups[keyword].append(article_data)
                            self.keyword_counts[keyword] += 1
                    else:
                        # 沒有關鍵詞的文章放入特殊分類
                        self.keyword_groups['未分類'].append(article_data)

                    self.logger.info(
                        f"讀取檔案 {md_file.name}，標題：{title}，日期：{date}，關鍵詞：{keywords}")
            except Exception as e:
                self.logger.error(f"讀取檔案 {md_file} 失敗：{str(e)}")
        self.logger.info(f"共讀取 {len(self.articles)} 篇文章")

        # 按關鍵詞出現次數排序
        self.sorted_keywords = sorted(
            self.keyword_counts.items(), key=lambda x: x[1], reverse=True)
        self.logger.info(f"關鍵詞統計：{self.sorted_keywords}")

    def compute_similarity(self, title1: str, title2: str) -> int:
        """計算兩個標題的相似度，忽略特定關鍵字"""
        keywords_to_remove = [",許文昌老師", ",曾榮耀老師", "許文昌老師", "曾榮耀老師"]
        cleaned_title1 = title1
        cleaned_title2 = title2
        for keyword in keywords_to_remove:
            cleaned_title1 = cleaned_title1.replace(keyword, "").strip()
            cleaned_title2 = cleaned_title2.replace(keyword, "").strip()
        similarity = fuzz.token_sort_ratio(cleaned_title1, cleaned_title2)
        self.logger.info(
            f"比較標題 '{cleaned_title1}' 與 '{cleaned_title2}'，相似度：{similarity}")
        return similarity

    def group_articles(self) -> List[List[Dict]]:
        """根據標題相似度分組文章"""
        groups = []
        used_indices = set()
        for i, article in enumerate(self.articles):
            if i in used_indices:
                continue
            group = [article]
            used_indices.add(i)
            for j, other_article in enumerate(self.articles[i+1:], start=i+1):
                if j in used_indices:
                    continue
                similarity = self.compute_similarity(
                    article['title'], other_article['title'])
                if similarity >= self.similarity_threshold:
                    group.append(other_article)
                    used_indices.add(j)
                    self.logger.info(
                        f"標題 '{article['title']}' 與 '{other_article['title']}' "
                        f"相似度 {similarity}，加入同一組"
                    )
            group = sorted(group, key=lambda x: x['date_obj'], reverse=True)
            groups.append(group)
        groups = sorted(groups, key=lambda g: g[0]['date_obj'], reverse=True)
        self.logger.info(f"生成 {len(groups)} 個標題相似組，按最新文章日期排序")
        return groups

    def merge_group_articles(self, groups: List[List[Dict]]):
        """合併每組文章到單個 Markdown 檔案"""
        self.merged_md_dir.mkdir(parents=True, exist_ok=True)
        for i, group in enumerate(groups, 1):
            if len(group) == 1:
                self.logger.info(f"組 {i} 只有一篇文章，無需合併：{group[0]['title']}")
                continue
            group_title = group[0]['title']
            for keyword in [",許文昌老師", ",曾榮耀老師", "許文昌老師", "曾榮耀老師"]:
                group_title = group_title.replace(keyword, "").strip()
            safe_title = re.sub(r'[^\w\s-]', '', group_title).replace(' ', '_')
            merged_file = self.merged_md_dir / f"group_{i}_{safe_title}.md"
            merged_content = [f"# 合併文章：{group_title}", ""]

            # 收集此組所有文章的關鍵詞
            all_keywords = set()
            for article in group:
                if article.get('keywords'):
                    all_keywords.update(article['keywords'])

            if all_keywords:
                merged_content.append(f"## 相關關鍵詞")
                merged_content.append(f"- {', '.join(sorted(all_keywords))}")
                merged_content.append("")

            for article in group:
                merged_content.append(f"## {article['title']}")
                merged_content.append(f"- 文章編號：{article['article_no']}")
                merged_content.append(f"- 發布日期：{article['date']}")
                if article.get('keywords'):
                    merged_content.append(
                        f"- 關鍵詞：{', '.join(article['keywords'])}")
                merged_content.append("")
                content_lines = article['content'].split('\n')
                title_idx = 0
                for line in content_lines:
                    if line.startswith('# ') and title_idx == 0:
                        title_idx += 1
                        continue
                    # 修正：確保圖片路徑使用正斜線
                    line = re.sub(
                        r'\./images/', '../articles/images/', line).replace('\\', '/')
                    merged_content.append(line)
                merged_content.append("")
            try:
                with open(merged_file, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(merged_content))
                self.logger.info(f"已生成合併檔案：{merged_file}")
            except Exception as e:
                self.logger.error(f"合併組 {i} 失敗：{str(e)}")

    def generate_keyword_collections(self):
        """根據關鍵詞生成文章集合"""
        self.keyword_md_dir.mkdir(parents=True, exist_ok=True)

        # 生成關鍵詞索引文件
        index_path = self.keyword_md_dir / "README_keywords.md"
        index_content = ["# 關鍵詞分類索引", "",
                         f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
                         "## 關鍵詞統計", ""]

        # 添加關鍵詞統計表格
        index_content.append("| 關鍵詞 | 文章數量 |")
        index_content.append("| --- | --- |")
        for keyword, count in self.sorted_keywords:
            safe_keyword = keyword.replace('|', '\\|')  # 轉義表格中的豎線
            keyword_file = self._get_safe_filename(keyword)
            index_content.append(
                f"| [{safe_keyword}](keyword_{keyword_file}.md) | {count} |")

        index_content.append("")

        # 生成索引文件
        try:
            with open(index_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(index_content))
            self.logger.info(f"已生成關鍵詞索引：{index_path}")
        except Exception as e:
            self.logger.error(f"生成關鍵詞索引失敗：{str(e)}")

        # 為每個關鍵詞生成文章集合
        for keyword, articles in self.keyword_groups.items():
            # 跳過文章數量太少的關鍵詞
            if len(articles) < 1:
                continue

            safe_keyword = self._get_safe_filename(keyword)
            keyword_file = self.keyword_md_dir / f"keyword_{safe_keyword}.md"

            # 按日期排序文章（從新到舊）
            articles = sorted(
                articles, key=lambda x: x['date_obj'] if x['date_obj'] else datetime.now(), reverse=True)

            content = [f"# 關鍵詞：{keyword}", "",
                       f"包含 {len(articles)} 篇文章", "",
                       "## 文章列表", ""]

            for article in articles:
                # 確保使用正斜線作為路徑分隔符，並處理特殊字符
                relative_path = str(article['file_path'].relative_to(
                    self.output_dir)).replace('\\', '/')
                relative_path = self._github_safe_path(relative_path)

                content.append(
                    f"### {article['date']} [{article['title']}](../../{relative_path})")
                content.append(f"- 文章編號：{article['article_no']}")
                if article.get('keywords'):
                    other_keywords = [
                        k for k in article['keywords'] if k != keyword]
                    if other_keywords:
                        content.append(f"- 其他關鍵詞：{', '.join(other_keywords)}")
                content.append("")

                # 添加文章摘要（前100個字符）
                article_text = re.sub(
                    # 移除標題和圖片
                    r'#.*?\n|!\[.*?\]\(.*?\)', '', article['content'])
                article_text = re.sub(r'- .*?：.*?\n', '',
                                      article_text)  # 移除元數據行
                article_text = re.sub(
                    r'\n+', ' ', article_text).strip()  # 移除多餘換行

                if article_text:
                    summary = article_text[:150] + \
                        ('...' if len(article_text) > 150 else '')
                    content.append(f"{summary}")
                    content.append("")

            try:
                with open(keyword_file, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(content))
                self.logger.info(f"已生成關鍵詞文章集合：{keyword_file}")
            except Exception as e:
                self.logger.error(f"生成關鍵詞 '{keyword}' 文章集合失敗：{str(e)}")

    def _get_safe_filename(self, s):
        """將字符串轉換為安全的文件名"""
        # 移除非法字符，並將空格替換為下劃線
        s = re.sub(r'[^\w\s-]', '', s).strip().replace(' ', '_')
        return s

    def generate_index(self, groups: List[List[Dict]]):
        """生成分組索引檔案"""
        index_path = self.output_dir / "README_grouped.md"
        content = ["# 文章分組目錄", "",
                   f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
                   "## 按關鍵詞分類", "",
                   f"[查看關鍵詞分類](keywords/md/README_keywords.md)", "",
                   "## 按標題相似度分組", ""]

        for i, group in enumerate(groups, 1):
            group_title = group[0]['title']
            content.append(f"## 組 {i}：{group_title}")

            # 收集此組所有文章的關鍵詞
            all_keywords = set()
            for article in group:
                if article.get('keywords'):
                    all_keywords.update(article['keywords'])

            if all_keywords:
                content.append(f"- 相關關鍵詞：{', '.join(sorted(all_keywords))}")

            if len(group) > 1:
                safe_title = re.sub(
                    r'[^\w\s-]', '', group_title).replace(' ', '_')
                # 修正：確保使用正斜線作為路徑分隔符
                merged_file = str(
                    Path("merged/md") / f"group_{i}_{safe_title}.md").replace('\\', '/')
                content.append(f"- [查看合併文章 (MD)]({merged_file})")

                # 添加 PDF 版本的連結（如果存在）
                merged_pdf = str(
                    Path("merged/pdf") / f"group_{i}_{safe_title}.pdf").replace('\\', '/')
                content.append(f"- [查看合併文章 (PDF)]({merged_pdf})")

            for article in group:
                # 修正：確保使用正斜線作為路徑分隔符，並處理特殊字符
                relative_path = str(article['file_path'].relative_to(
                    self.output_dir)).replace('\\', '/')
                # 將逗號和其他特殊字符進行URL編碼
                relative_path = self._github_safe_path(relative_path)

                article_line = f"- {article['date']} [{article['title']}]({relative_path}) (文章編號：{article['article_no']})"
                if article.get('keywords'):
                    article_line += f" 關鍵詞：{', '.join(article['keywords'])}"
                content.append(article_line)

            content.append("")

        try:
            with open(index_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(content))
            self.logger.info(f"已生成分組索引：{index_path}")
        except Exception as e:
            self.logger.error(f"生成索引失敗：{str(e)}")

    def _github_safe_path(self, path: str) -> str:
        """處理路徑使其在GitHub上安全顯示"""
        # 將逗號和其他特殊字符替換為URL編碼形式
        import urllib.parse
        # 將路徑分割為目錄和文件名
        parts = path.split('/')
        # 只對最後一部分（文件名）進行編碼
        if len(parts) > 0:
            filename = parts[-1]
            # 使用百分比編碼替換特殊字符
            encoded_filename = urllib.parse.quote(filename)
            parts[-1] = encoded_filename
            return '/'.join(parts)
        return path

    def _group_by_year(self, groups: List[List[Dict]]) -> Dict[str, List[List[Dict]]]:
        """將文章按年份分組"""
        year_groups = {}
        for group in groups:
            # 使用第一篇文章的年份作為分組依據
            if group and group[0]['date_obj']:
                year = str(group[0]['date_obj'].year)
                if year not in year_groups:
                    year_groups[year] = []
                year_groups[year].append(group)

        # 按年份排序（從新到舊）
        return dict(sorted(year_groups.items(), key=lambda x: x[0], reverse=True))

    def generate_pdf(self, groups: List[List[Dict]]):
        """按年份生成包含文章內容的PDF檔案，每組使用新頁面，並添加頁碼"""
        # 創建 PDF 目錄
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.merged_pdf_dir.mkdir(parents=True, exist_ok=True)
        self.keyword_pdf_dir.mkdir(parents=True, exist_ok=True)

        # 按年份分組
        year_groups = self._group_by_year(groups)
        self.logger.info(f"將文章按年份分組：共{len(year_groups)}個年份")

        # 為每個年份生成PDF
        for year, year_groups in year_groups.items():
            pdf_path = self.pdf_dir / f"articles_{year}.pdf"
            self._generate_pdf_for_year(year, year_groups, pdf_path)

        # 生成按關鍵詞分類的PDF
        self._generate_keyword_pdfs()

        # 生成合併文章的PDF
        self._generate_merged_pdfs(groups)

    def _generate_merged_pdfs(self, groups: List[List[Dict]]):
        """為合併的文章組生成PDF檔案"""
        for i, group in enumerate(groups, 1):
            if len(group) <= 1:
                continue  # 跳過只有一篇文章的組

            group_title = group[0]['title']
            for keyword in [",許文昌老師", ",曾榮耀老師", "許文昌老師", "曾榮耀老師"]:
                group_title = group_title.replace(keyword, "").strip()

            safe_title = re.sub(r'[^\w\s-]', '', group_title).replace(' ', '_')
            pdf_path = self.merged_pdf_dir / f"group_{i}_{safe_title}.pdf"

            try:
                # 使用自訂文件模板來添加頁碼
                doc = BaseDocTemplate(str(pdf_path), pagesize=A4,
                                      rightMargin=72, leftMargin=72,
                                      topMargin=72, bottomMargin=72)

                # 創建頁面模板
                frame = Frame(doc.leftMargin, doc.bottomMargin,
                              doc.width, doc.height - 2*cm,
                              id='normal')
                template = PageTemplate(id='normal', frames=[frame])
                doc.addPageTemplates([template])

                styles = getSampleStyleSheet()

                # 使用已註冊的中文字型
                styles.add(ParagraphStyle(name='ChineseTitle',
                                          fontName=self.chinese_font_name, fontSize=16, leading=20, spaceAfter=12))
                styles.add(ParagraphStyle(name='ChineseSubtitle',
                                          fontName=self.chinese_font_name, fontSize=14, leading=18, spaceAfter=10))
                styles.add(ParagraphStyle(name='ChineseBody',
                                          fontName=self.chinese_font_name, fontSize=12, leading=15, spaceAfter=8))
                styles.add(ParagraphStyle(name='ChineseHeading1',
                                          fontName=self.chinese_font_name, fontSize=18, leading=22, spaceAfter=12,
                                          keepWithNext=True))

                story = []
                story.append(
                    Paragraph(f"合併文章：{group_title}", styles['ChineseHeading1']))
                story.append(Spacer(1, 0.2 * inch))
                story.append(Paragraph(
                    f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['ChineseBody']))
                story.append(Spacer(1, 0.3 * inch))

                # 收集此組所有文章的關鍵詞
                all_keywords = set()
                for article in group:
                    if article.get('keywords'):
                        all_keywords.update(article['keywords'])

                if all_keywords:
                    story.append(
                        Paragraph(f"相關關鍵詞：{', '.join(sorted(all_keywords))}", styles['ChineseBody']))
                    story.append(Spacer(1, 0.2 * inch))

                # 為每篇文章創建內容
                for j, article in enumerate(group, 1):
                    # 除了第一篇外，其他文章前添加分頁符
                    if j > 1:
                        story.append(PageBreak())

                    story.append(
                        Paragraph(article['title'], styles['ChineseHeading1']))
                    story.append(
                        Paragraph(f"文章編號：{article['article_no']}", styles['ChineseBody']))
                    story.append(
                        Paragraph(f"發布日期：{article['date']}", styles['ChineseBody']))
                    if article.get('keywords'):
                        story.append(
                            Paragraph(f"關鍵詞：{', '.join(article['keywords'])}", styles['ChineseBody']))
                    story.append(Spacer(1, 0.2 * inch))

                    content_lines = article['content'].split('\n')
                    title_idx = 0
                    for line in content_lines:
                        if line.startswith('# ') and title_idx == 0:
                            title_idx += 1
                            continue

                        # 處理圖片
                        try:
                            img_match = re.match(r'!\[.*?\]\((.*?)\)', line)
                            if img_match:
                                img_path = img_match.group(1)
                                # 確保圖片路徑使用正斜線
                                img_path = img_path.replace(
                                    './images/', str(self.image_dir) + '/').replace('\\', '/')
                                if Path(img_path).exists():
                                    try:
                                        img = Image(
                                            img_path, width=4 * inch, height=3*inch)
                                        story.append(img)
                                        story.append(Spacer(1, 0.1 * inch))
                                    except Exception as e:
                                        self.logger.warning(
                                            f"無法處理圖片 {img_path}：{str(e)}")
                                else:
                                    self.logger.warning(
                                        f"圖片 {img_path} 不存在，跳過嵌入")
                                continue

                            # 處理文字
                            if line.strip():
                                # 處理特殊字符，避免 ReportLab 解析錯誤
                                clean_line = line.replace(
                                    '\\', '\\\\')  # 雙重轉義反斜線
                                story.append(
                                    Paragraph(clean_line, styles['ChineseBody']))
                        except Exception as e:
                            self.logger.warning(
                                f"處理行時出錯：{str(e)}，原始行：{line[:30]}...")
                            # 嘗試使用更安全的方式添加
                            try:
                                safe_line = ''.join(
                                    # 只保留 ASCII 字符
                                    c for c in line if ord(c) < 128)
                                if safe_line.strip():
                                    story.append(
                                        Paragraph(safe_line, styles['ChineseBody']))
                            except:
                                pass

                    story.append(Spacer(1, 0.2 * inch))

                doc.build(story, canvasmaker=NumberedCanvas)
                self.logger.info(f"已生成合併文章 PDF：{pdf_path}")
            except Exception as e:
                self.logger.error(f"生成合併文章 PDF 失敗：{str(e)}")

    def _generate_keyword_pdfs(self):
        """生成按關鍵詞分類的PDF檔案"""
        # 只處理包含至少3篇文章的關鍵詞
        for keyword, articles in self.keyword_groups.items():
            if len(articles) < 3:
                continue

            safe_keyword = self._get_safe_filename(keyword)
            pdf_path = self.keyword_pdf_dir / f"keyword_{safe_keyword}.pdf"

            try:
                # 使用自訂文件模板來添加頁碼
                doc = BaseDocTemplate(str(pdf_path), pagesize=A4,
                                      rightMargin=72, leftMargin=72,
                                      topMargin=72, bottomMargin=72)

                # 創建頁面模板
                frame = Frame(doc.leftMargin, doc.bottomMargin,
                              doc.width, doc.height - 2*cm,
                              id='normal')
                template = PageTemplate(id='normal', frames=[frame])
                doc.addPageTemplates([template])

                styles = getSampleStyleSheet()

                # 使用已註冊的中文字型
                styles.add(ParagraphStyle(name='ChineseTitle',
                                          fontName=self.chinese_font_name, fontSize=16, leading=20, spaceAfter=12))
                styles.add(ParagraphStyle(name='ChineseSubtitle',
                                          fontName=self.chinese_font_name, fontSize=14, leading=18, spaceAfter=10))
                styles.add(ParagraphStyle(name='ChineseBody',
                                          fontName=self.chinese_font_name, fontSize=12, leading=15, spaceAfter=8))
                styles.add(ParagraphStyle(name='ChineseHeading1',
                                          fontName=self.chinese_font_name, fontSize=18, leading=22, spaceAfter=12,
                                          keepWithNext=True))

                story = []
                story.append(
                    Paragraph(f"關鍵詞：{keyword} (共{len(articles)}篇文章)", styles['ChineseHeading1']))
                story.append(Spacer(1, 0.2 * inch))
                story.append(Paragraph(
                    f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['ChineseBody']))
                story.append(Spacer(1, 0.3 * inch))

                # 按日期排序文章（從新到舊）
                articles = sorted(
                    articles, key=lambda x: x['date_obj'] if x['date_obj'] else datetime.now(), reverse=True)

                # 為每篇文章創建內容
                for i, article in enumerate(articles, 1):
                    # 除了第一篇外，其他文章前添加分頁符
                    if i > 1:
                        story.append(PageBreak())

                    # 使用 keepWithNext 確保文章標題不會單獨出現在頁面底部
                    article_title = Paragraph(
                        article['title'], styles['ChineseHeading1'])
                    story.append(article_title)
                    story.append(
                        Paragraph(f"文章編號：{article['article_no']}", styles['ChineseBody']))
                    story.append(
                        Paragraph(f"發布日期：{article['date']}", styles['ChineseBody']))

                    if article.get('keywords'):
                        other_keywords = [
                            k for k in article['keywords'] if k != keyword]
                        if other_keywords:
                            story.append(
                                Paragraph(f"其他關鍵詞：{', '.join(other_keywords)}", styles['ChineseBody']))

                    story.append(Spacer(1, 0.2 * inch))

                    content_lines = article['content'].split('\n')
                    title_idx = 0
                    for line in content_lines:
                        if line.startswith('# ') and title_idx == 0:
                            title_idx += 1
                            continue

                        # 處理圖片
                        try:
                            img_match = re.match(r'!\[.*?\]\((.*?)\)', line)
                            if img_match:
                                img_path = img_match.group(1)
                                # 修正：確保圖片路徑使用正斜線
                                img_path = img_path.replace(
                                    './images/', str(self.image_dir) + '/').replace('\\', '/')
                                if Path(img_path).exists():
                                    try:
                                        img = Image(
                                            img_path, width=4 * inch, height=3*inch)
                                        story.append(img)
                                        story.append(Spacer(1, 0.1 * inch))
                                    except Exception as e:
                                        self.logger.warning(
                                            f"無法處理圖片 {img_path}：{str(e)}")
                                else:
                                    self.logger.warning(
                                        f"圖片 {img_path} 不存在，跳過嵌入")
                                continue

                            # 處理文字
                            if line.strip():
                                # 處理特殊字符，避免 ReportLab 解析錯誤
                                clean_line = line.replace(
                                    '\\', '\\\\')  # 雙重轉義反斜線
                                story.append(
                                    Paragraph(clean_line, styles['ChineseBody']))
                        except Exception as e:
                            self.logger.warning(
                                f"處理行時出錯：{str(e)}，原始行：{line[:30]}...")
                            # 嘗試使用更安全的方式添加
                            try:
                                safe_line = ''.join(
                                    # 只保留 ASCII 字符
                                    c for c in line if ord(c) < 128)
                                if safe_line.strip():
                                    story.append(
                                        Paragraph(safe_line, styles['ChineseBody']))
                            except:
                                pass

                    story.append(Spacer(1, 0.2 * inch))

                doc.build(story, canvasmaker=NumberedCanvas)
                self.logger.info(f"已生成關鍵詞 '{keyword}' 的PDF檔案：{pdf_path}")
            except Exception as e:
                self.logger.error(f"生成關鍵詞 '{keyword}' PDF失敗：{str(e)}")

    def _generate_pdf_for_year(self, year: str, groups: List[List[Dict]], pdf_path: Path):
        """為特定年份生成PDF檔案"""
        self.logger.info(f"開始生成{year}年的PDF檔案：{pdf_path}")

        # 使用自訂文件模板來添加頁碼
        doc = BaseDocTemplate(str(pdf_path), pagesize=A4,
                              rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=72)

        # 創建頁面模板
        frame = Frame(doc.leftMargin, doc.bottomMargin,
                      doc.width, doc.height - 2*cm,
                      id='normal')
        template = PageTemplate(id='normal', frames=[frame])
        doc.addPageTemplates([template])

        styles = getSampleStyleSheet()

        # 使用已註冊的中文字型
        # 自訂樣式
        styles.add(ParagraphStyle(name='ChineseTitle',
                                  fontName=self.chinese_font_name, fontSize=16, leading=20, spaceAfter=12))
        styles.add(ParagraphStyle(name='ChineseSubtitle',
                                  fontName=self.chinese_font_name, fontSize=14, leading=18, spaceAfter=10))
        styles.add(ParagraphStyle(name='ChineseBody',
                                  fontName=self.chinese_font_name, fontSize=12, leading=15, spaceAfter=8))
        styles.add(ParagraphStyle(name='ChineseHeading1',
                                  fontName=self.chinese_font_name, fontSize=18, leading=22, spaceAfter=12,
                                  keepWithNext=True))  # keepWithNext 確保標題不會單獨出現在頁面底部

        story = []
        story.append(Paragraph(f"{year}年文章合集", styles['ChineseHeading1']))
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph(
            f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['ChineseBody']))
        story.append(Spacer(1, 0.3 * inch))

        # 為每個組別創建內容
        for i, group in enumerate(groups, 1):
            # 除了第一組外，其他組別前添加分頁符
            if i > 1:
                story.append(PageBreak())

            group_title = group[0]['title']
            for keyword in [",許文昌老師", ",曾榮耀老師", "許文昌老師", "曾榮耀老師"]:
                group_title = group_title.replace(keyword, "").strip()

            # 使用 keepWithNext 確保組標題不會單獨出現在頁面底部
            group_heading = Paragraph(
                f"組 {i}：{group_title}", styles['ChineseHeading1'])
            story.append(group_heading)
            story.append(Spacer(1, 0.2 * inch))

            # 顯示此組的關鍵詞
            all_keywords = set()
            for article in group:
                if article.get('keywords'):
                    all_keywords.update(article['keywords'])

            if all_keywords:
                story.append(
                    Paragraph(f"相關關鍵詞：{', '.join(sorted(all_keywords))}", styles['ChineseBody']))
                story.append(Spacer(1, 0.1 * inch))

            for article in group:
                # 使用 keepWithNext 確保文章標題不會單獨出現在頁面底部
                article_title = Paragraph(
                    article['title'], styles['ChineseSubtitle'])
                story.append(article_title)
                story.append(
                    Paragraph(f"文章編號：{article['article_no']}", styles['ChineseBody']))
                story.append(
                    Paragraph(f"發布日期：{article['date']}", styles['ChineseBody']))
                if article.get('keywords'):
                    story.append(
                        Paragraph(f"關鍵詞：{', '.join(article['keywords'])}", styles['ChineseBody']))
                story.append(Spacer(1, 0.1 * inch))

                content_lines = article['content'].split('\n')
                title_idx = 0
                for line in content_lines:
                    if line.startswith('# ') and title_idx == 0:
                        title_idx += 1
                        continue

                    # 處理圖片
                    try:
                        img_match = re.match(r'!\[.*?\]\((.*?)\)', line)
                        if img_match:
                            img_path = img_match.group(1)
                            # 修正：確保圖片路徑使用正斜線
                            img_path = img_path.replace(
                                './images/', str(self.image_dir) + '/').replace('\\', '/')
                            if Path(img_path).exists():
                                try:
                                    img = Image(img_path, width=4 *
                                                inch, height=3*inch)
                                    story.append(img)
                                    story.append(Spacer(1, 0.1 * inch))
                                except Exception as e:
                                    self.logger.warning(
                                        f"無法處理圖片 {img_path}：{str(e)}")
                            else:
                                self.logger.warning(f"圖片 {img_path} 不存在，跳過嵌入")
                            continue

                        # 處理文字
                        if line.strip():
                            # 處理特殊字符，避免 ReportLab 解析錯誤
                            clean_line = line.replace('\\', '\\\\')  # 雙重轉義反斜線
                            story.append(
                                Paragraph(clean_line, styles['ChineseBody']))
                    except Exception as e:
                        self.logger.warning(
                            f"處理行時出錯：{str(e)}，原始行：{line[:30]}...")
                        # 嘗試使用更安全的方式添加
                        try:
                            safe_line = ''.join(
                                # 只保留 ASCII 字符
                                c for c in line if ord(c) < 128)
                            if safe_line.strip():
                                story.append(
                                    Paragraph(safe_line, styles['ChineseBody']))
                        except:
                            pass

                story.append(Spacer(1, 0.2 * inch))

        try:
            doc.build(story, canvasmaker=NumberedCanvas)
            self.logger.info(f"已生成 {year}年 PDF 檔案：{pdf_path}")
        except Exception as e:
            self.logger.error(f"生成 {year}年 PDF 失敗：{str(e)}")
            # 嘗試使用更簡單的方式生成 PDF
            self._generate_simple_pdf_for_year(year, groups, pdf_path)

    def _generate_simple_pdf_for_year(self, year: str, groups: List[List[Dict]], pdf_path: Path):
        """使用更簡單的方式為特定年份生成PDF，作為備選方案"""
        try:
            self.logger.info(f"嘗試使用簡化方式生成 {year}年 PDF...")
            from reportlab.lib import colors

            # 使用自訂文件模板來添加頁碼
            doc = BaseDocTemplate(str(pdf_path), pagesize=A4)

            # 創建頁面模板
            frame = Frame(doc.leftMargin, doc.bottomMargin,
                          doc.width, doc.height - 2*cm,
                          id='normal')
            template = PageTemplate(id='normal', frames=[frame])
            doc.addPageTemplates([template])

            styles = getSampleStyleSheet()
            story = []

            # 使用預設字型
            story.append(Paragraph(f"{year}年文章合集", styles['Title']))
            story.append(Spacer(1, 0.2 * inch))
            story.append(Paragraph(
                f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
            story.append(Spacer(1, 0.3 * inch))

            for i, group in enumerate(groups, 1):
                # 除了第一組外，其他組別前添加分頁符
                if i > 1:
                    story.append(PageBreak())

                group_title = group[0]['title']
                for keyword in [",許文昌老師", ",曾榮耀老師", "許文昌老師", "曾榮耀老師"]:
                    group_title = group_title.replace(keyword, "").strip()

                story.append(
                    Paragraph(f"組 {i}：{group_title}", styles['Heading1']))

                # 顯示此組的關鍵詞
                all_keywords = set()
                for article in group:
                    if article.get('keywords'):
                        all_keywords.update(article['keywords'])

                if all_keywords:
                    story.append(
                        Paragraph(f"相關關鍵詞：{', '.join(sorted(all_keywords))}", styles['Normal']))

                for article in group:
                    story.append(
                        Paragraph(article['title'], styles['Heading2']))
                    story.append(
                        Paragraph(f"文章編號：{article['article_no']}", styles['Normal']))
                    story.append(
                        Paragraph(f"發布日期：{article['date']}", styles['Normal']))
                    if article.get('keywords'):
                        story.append(
                            Paragraph(f"關鍵詞：{', '.join(article['keywords'])}", styles['Normal']))
                    story.append(Spacer(1, 0.1 * inch))

            doc.build(story, canvasmaker=NumberedCanvas)
            self.logger.info(f"已使用簡化方式生成 {year}年 PDF 檔案：{pdf_path}")
        except Exception as e:
            self.logger.error(f"{year}年 簡化 PDF 生成也失敗：{str(e)}")
            self.logger.info("建議使用其他工具如 Pandoc 將 Markdown 轉換為 PDF")

    def run(self):
        """執行分組流程"""
        self.logger.info("開始分組文章")

        # 創建所有必要的目錄
        self.merged_md_dir.mkdir(parents=True, exist_ok=True)
        self.merged_pdf_dir.mkdir(parents=True, exist_ok=True)
        self.keyword_md_dir.mkdir(parents=True, exist_ok=True)
        self.keyword_pdf_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

        self.read_markdown_files()
        if not self.articles:
            self.logger.warning("未找到任何 Markdown 檔案")
            return

        # 生成關鍵詞分類
        self.generate_keyword_collections()

        # 根據標題相似度分組
        groups = self.group_articles()
        self.merge_group_articles(groups)
        self.generate_index(groups)

        try:
            self.generate_pdf(groups)
        except Exception as e:
            self.logger.error(f"PDF 生成失敗，但不影響其他功能：{str(e)}")

        self.logger.info("文章分組、關鍵詞分類、合併與索引生成完成")


if __name__ == "__main__":
    grouper = ArticleGrouper()
    grouper.run()






# python group_similar_titles.py
