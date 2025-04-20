import os
from pathlib import Path
import re
from typing import List, Dict
from fuzzywuzzy import fuzz
from datetime import datetime
import logging


class ArticleGrouper:
    def __init__(self, articles_dir: str = "real_estate_articles/articles", output_dir: str = "real_estate_articles"):
        """初始化分組器"""
        self.articles_dir = Path(articles_dir)
        self.output_dir = Path(output_dir)
        self.merged_dir = self.output_dir / "merged"
        self.image_dir = self.articles_dir / "images"
        self.similarity_threshold = 80
        self.articles = []
        self.logger = self.setup_logger()

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
        """讀取所有 Markdown 檔案並提取標題與元資料"""
        self.articles = []
        for md_file in self.articles_dir.glob("*.md"):
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 提取標題（第一行以 # 開頭）
                    title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
                    title = title_match.group(
                        1).strip() if title_match else md_file.stem
                    # 提取文章編號
                    article_no_match = re.search(r'文章編號：(\d+)', content)
                    article_no = article_no_match.group(
                        1) if article_no_match else md_file.stem.split('_')[0]
                    # 提取日期
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
                    self.articles.append({
                        'file_path': md_file,
                        'title': title,
                        'article_no': article_no,
                        'date': date,
                        'date_obj': date_obj,
                        'content': content
                    })
                    self.logger.info(
                        f"讀取檔案 {md_file.name}，標題：{title}，日期：{date}")
            except Exception as e:
                self.logger.error(f"讀取檔案 {md_file} 失敗：{str(e)}")
        self.logger.info(f"共讀取 {len(self.articles)} 篇文章")

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
        self.merged_dir.mkdir(parents=True, exist_ok=True)
        for i, group in enumerate(groups, 1):
            if len(group) == 1:
                self.logger.info(f"組 {i} 只有一篇文章，無需合併：{group[0]['title']}")
                continue
            group_title = group[0]['title']
            for keyword in [",許文昌老師", ",曾榮耀老師", "許文昌老師", "曾榮耀老師"]:
                group_title = group_title.replace(keyword, "").strip()
            safe_title = re.sub(r'[^\w\s-]', '', group_title).replace(' ', '_')
            merged_file = self.merged_dir / f"group_{i}_{safe_title}.md"
            merged_content = [f"# 合併文章：{group_title}", ""]
            for article in group:
                merged_content.append(f"## {article['title']}")
                merged_content.append(f"- 文章編號：{article['article_no']}")
                merged_content.append(f"- 發布日期：{article['date']}")
                merged_content.append("")
                content_lines = article['content'].split('\n')
                title_idx = 0
                for line in content_lines:
                    if line.startswith('# ') and title_idx == 0:
                        title_idx += 1
                        continue
                    line = re.sub(r'\./images/', '../articles/images/', line)
                    merged_content.append(line)
                merged_content.append("")
            try:
                with open(merged_file, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(merged_content))
                self.logger.info(f"已生成合併檔案：{merged_file}")
            except Exception as e:
                self.logger.error(f"合併組 {i} 失敗：{str(e)}")

    def generate_index(self, groups: List[List[Dict]]):
        """生成分組索引檔案"""
        index_path = self.output_dir / "README_grouped.md"
        content = ["# 文章分組目錄", "",
                   f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
        for i, group in enumerate(groups, 1):
            group_title = group[0]['title']
            content.append(f"## 組 {i}：{group_title}")
            if len(group) > 1:
                safe_title = re.sub(
                    r'[^\w\s-]', '', group_title).replace(' ', '_')
                merged_file = Path("merged") / f"group_{i}_{safe_title}.md"
                content.append(f"- [查看合併文章]({merged_file})")
            for article in group:
                relative_path = article['file_path'].relative_to(
                    self.output_dir)
                content.append(
                    f"- {article['date']} [{article['title']}]({relative_path}) "
                    f"(文章編號：{article['article_no']})"
                )
            content.append("")
        try:
            with open(index_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(content))
            self.logger.info(f"已生成分組索引：{index_path}")
        except Exception as e:
            self.logger.error(f"生成索引失敗：{str(e)}")

    def run(self):
        """執行分組流程"""
        self.logger.info("開始分組文章")
        self.read_markdown_files()
        if not self.articles:
            self.logger.warning("未找到任何 Markdown 檔案")
            return
        groups = self.group_articles()
        self.merge_group_articles(groups)
        self.generate_index(groups)
        self.logger.info("文章分組與合併完成")


if __name__ == "__main__":
    grouper = ArticleGrouper()
    grouper.run()


# python group_similar_titles.py
