import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple
from collections import defaultdict
import yaml

from landnote.config import ARTICLES_DIR, DATA_DIR, LOGS_DIR
from landnote.utils.logger import Logger

# 卡片頁不需要左側導覽與右側目錄，隱藏後內容區才夠寬排三欄
HIDE_SIDEBARS = "---\nhide:\n  - navigation\n  - toc\n---\n"

class SiteGenerator:
    def __init__(self, source_dir: Path = None):
        self.source_dir = source_dir if source_dir else ARTICLES_DIR
        self.base_dir = DATA_DIR.parent  # landnotev3 root
        # We'll use 'mkdocs' folder to keep source clean for mkdocs
        self.site_src_dir = self.base_dir / "site_src" 
        self.docs_dir = self.site_src_dir / "docs"
        self.posts_dir = self.docs_dir / "blog" / "posts"
        self.logger = Logger.setup_logger("SiteGenerator", LOGS_DIR)
        self.authors = set()

    def run(self):
        """Main execution method to generate the MkDocs site structure."""
        self.logger.info("Starting Static Site Generation...")
        
        # 1. Prepare directories
        self._prepare_directories()
        
        # 2. Process articles and move to docs/posts with YAML frontmatter
        self._process_articles()
        
        # 4. Generate tags and authors statistics
        all_tags = self._collect_all_tags()
        
        # 5. Generate tags page
        self._generate_tags_page(all_tags)
        
        # 6. Generate authors file
        self._generate_authors_file()

        # Generate Review Materials (Bulk PDFs per tag and full)
        self._generate_review_materials()

        # 7. Generate mkdocs.yml
        self._generate_mkdocs_config()
        
        # 8. Generate Homepage
        self._generate_homepage()
        
        self.logger.info("Site generation structure completed.")

    def _prepare_directories(self):
        """Clean and create necessary directories. Handles Windows file lock issues."""
        try:
            if self.site_src_dir.exists():
                shutil.rmtree(self.site_src_dir)
        except PermissionError:
            self.logger.warning(f"Could not remove {self.site_src_dir}, cleaning contents instead.")
            for item in self.site_src_dir.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except:
                    pass

        self.site_src_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.posts_dir.mkdir(parents=True, exist_ok=True)
        # 不先建立的話 Material blog 外掛會自動產生英文標題「# Blog」
        (self.docs_dir / "blog" / "index.md").write_text("# 最新文章\n", encoding="utf-8")

        # Create stylesheets directory
        styles_dir = self.docs_dir / "stylesheets"
        styles_dir.mkdir(exist_ok=True)
        # Copy external CSS
        source_css = Path(__file__).parent.parent / "templates" / "static" / "css" / "extra.css"
        if source_css.exists():
            shutil.copy2(source_css, styles_dir / "extra.css")

        # Create javascripts directory
        scripts_dir = self.docs_dir / "javascripts"
        scripts_dir.mkdir(exist_ok=True)
        # Copy external JS
        source_js = Path(__file__).parent.parent / "templates" / "static" / "js" / "study_tools.js"
        if source_js.exists():
            shutil.copy2(source_js, scripts_dir / "extra.js")

        # Copy images if they exist
        src_images = self.source_dir / "images"
        dst_images = self.posts_dir / "images"
        if src_images.exists():
            try:
                shutil.copytree(src_images, dst_images, dirs_exist_ok=True)
            except:
                pass

             # JS function _write_extra_js has been moved to external static files.

    def _generate_review_materials(self):
        """Generate combined markdown files for each tag and for all articles for easy downloading/printing."""
        self.logger.info("Generating Review Materials (Combined PDFs)...")
        review_dir = self.docs_dir / "review"
        review_dir.mkdir(exist_ok=True)
        
        tag_articles = defaultdict(list)
        all_articles = []
        
        for file in self.posts_dir.glob("*.md"):
            try:
                content = file.read_text(encoding='utf-8')
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    meta = yaml.safe_load(parts[1])
                    body = parts[2]
                    
                    # Fix image paths for the review dir context
                    body = body.replace('(images/', '(../blog/posts/images/')
                    
                    item = {
                        'title': meta.get('title', ''),
                        'date': meta.get('date', ''),
                        'body': body,
                        'categories': meta.get('categories', [])
                    }
                    all_articles.append(item)
                    for c in item['categories']:
                        if c != 'Real Estate':
                            tag_articles[c].append(item)
            except Exception:
                pass
                
        # Sort articles by date descending
        all_articles.sort(key=lambda x: str(x['date']), reverse=True)
        for tag in tag_articles:
            tag_articles[tag].sort(key=lambda x: str(x['date']), reverse=True)
            
        def create_merged_doc(title, articles, path_obj):
            doc_lines = [f"# {title}", "", f"共收錄 {len(articles)} 篇文章。", ""]
            for idx, a in enumerate(articles, 1):
                doc_lines.append(f"## {idx}. {a['title']}")
                doc_lines.append(f"*發布日期: {a['date']}* \n")
                doc_lines.append(a['body'].strip())
                doc_lines.append("\n<div style=\"page-break-before: always;\"></div>\n")
            path_obj.write_text('\n'.join(doc_lines), encoding='utf-8')

        # Generate ALL
        create_merged_doc("不動產全科大補帖", all_articles, review_dir / "all.md")
        
        # Generate per tag
        for tag, articles in tag_articles.items():
            safe_tag = tag.replace(' ', '_').replace('/', '_')
            create_merged_doc(f"主題精選：{tag}", articles, review_dir / f"{safe_tag}.md")
            
        # No index page needed here anymore, it is integrated into tags.md (主題探索與講義下載)

    def _process_articles(self):
        """Transform raw markdown files into Hugo/MkDocs compatible files."""
        files = list(self.source_dir.glob("*.md"))
        self.logger.info(f"Processing {len(files)} articles...")

        for file_path in files:
            try:
                content = file_path.read_text(encoding='utf-8')
                metadata, body = self._parse_article(content)
                
                # Construct new filename: YYYY-MM-DD-ID-Title.md to help with sorting and ensure uniqueness
                date_str = str(metadata.get('date', '1970-01-01'))
                article_id = metadata.get('id', '000000')
                
                # Collect author for Site Authors
                author = metadata.get('author')
                if author:
                    self.authors.add(author)

                # Sanitize title for filename
                raw_title = metadata.get('title', 'Untitled')
                safe_title = re.sub(r'[\\/*?:"<>|]', '', raw_title).strip()
                # Limit title length in filename
                safe_title = safe_title[:50]
                new_filename = f"{date_str}-{article_id}-{safe_title}.md"
                
                # Combine categories and tags into categories to ensure indexing by blog plugin
                categories = ['Real Estate']
                tags = metadata.get('tags', [])
                categories.extend(tags)
                
                # Yamaha Frontmatter
                frontmatter = {
                    'title': raw_title,
                    'date': metadata.get('date'), 
                    'slug': article_id, # Use ID as slug for cleaner URLs
                    'categories': categories,
                    'tags': tags
                }
                
                # 爬蟲固定在開頭產生「## 內文」，對讀者無資訊量，列表卡片與目錄都多一行
                body = re.sub(r"\A\s*##\s*內文\s*\n", "", body)
                body = self._insert_excerpt_separator(body)

                # Write new file
                new_content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n\n" + body
                
                # Fix image paths in body (./images/ -> images/)
                new_content = new_content.replace('(./images/', '(images/')
                
                (self.posts_dir / new_filename).write_text(new_content, encoding='utf-8')
                
            except Exception as e:
                self.logger.error(f"Failed to process {file_path.name}: {e}")

    def _parse_article(self, content: str) -> Tuple[Dict, str]:
        """Extract metadata from the custom format."""
        lines = content.split('\n')
        metadata = {}
        body_lines = []
        
        # Extract Title (First line usually)
        if lines and lines[0].startswith('# '):
            # Remove trailing author if present roughly (e.g. ",曾榮耀老師")
            raw_title = lines[0][2:].split(',')[0] 
            metadata['title'] = raw_title.strip()
        
        in_info_block = False
        body_started = False
        
        for line in lines:
            if line.strip().startswith('## 文章資訊'):
                in_info_block = True
                continue
            
            if in_info_block:
                if line.startswith('## '): # Next section
                    in_info_block = False
                    body_started = True
                elif line.strip().startswith('- '):
                    # Parse info fields
                    # Handle both half-width ':' and full-width '：'
                    clean_line = line.strip()[2:]
                    if '作者' in clean_line and (':' in clean_line or '：' in clean_line):
                        metadata['author'] = re.split(r'[:：]', clean_line, 1)[1].strip()
                    elif '文章編號' in clean_line and (':' in clean_line or '：' in clean_line):
                        metadata['id'] = re.split(r'[:：]', clean_line, 1)[1].strip()
                    elif '發布日期' in clean_line and (':' in clean_line or '：' in clean_line):
                        date_part = re.split(r'[:：]', clean_line, 1)[1].strip()
                        # Normalize date
                        try:
                            # Match YYYY/MM/DD or YYYY-MM-DD
                            date_match = re.search(r'(\d{4})[/年-](\d{1,2})[/月-](\d{1,2})', date_part)
                            if date_match:
                                y, m, d = date_match.groups()
                                metadata['date'] = datetime(int(y), int(m), int(d)).date()
                            else:
                                metadata['date'] = datetime.now().date() # Fallback
                        except:
                            metadata['date'] = date_part # Fallback to string if parsing fails
                    elif '關鍵詞' in clean_line and (':' in clean_line or '：' in clean_line):
                        kws_part = re.split(r'[:：]', clean_line, 1)[1].strip()
                        # Split by common separators
                        kws = re.split(r'[,、，]', kws_part)
                        metadata['tags'] = [k.strip() for k in kws if k.strip()]
            
            # Decide what to keep in body
            # Skip the initial title line as it's now in frontmatter
            if line.startswith('# ') and not body_started and not in_info_block:
                continue 
                
            if not in_info_block:
                # Fix image paths in body (./images/ -> images/)
                line = line.replace('(./images/', '(images/')
                body_lines.append(line)
        # 清理重複的「文章圖片」區塊：只保留不重複的圖片引用
        body = '\n'.join(body_lines).strip()
        body = self._deduplicate_image_sections(body)
        return metadata, body

    EXCERPT_SEPARATOR = "<!-- more -->"
    EXCERPT_MIN_CHARS = 150
    EXCERPT_MAX_BLOCKS = 6

    @classmethod
    def _insert_excerpt_separator(cls, body: str) -> str:
        """在內文前段插入 MkDocs Material 部落格的摘要分隔標記。

        以空行切段，累積可見文字達 EXCERPT_MIN_CHARS 字後於段落邊界插入；
        不在清單項目、表格、程式碼區塊中間切斷，後面沒有內容時不插入。

        Args:
            body: 文章內文（不含 frontmatter）。

        Returns:
            插入分隔標記後的內文；已有標記或文章太短則原樣回傳。
        """
        if cls.EXCERPT_SEPARATOR in body:
            return body

        blocks = re.split(r"\n\s*\n", body.strip())
        list_re = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
        text_len = 0
        text_blocks = 0
        in_fence = False

        for i, block in enumerate(blocks[:-1]):
            if block.count("```") % 2 == 1:
                in_fence = not in_fence
            stripped = block.strip()
            if stripped.startswith("## 文章圖片"):
                # 圖片區佔版面，未湊滿字數也在它前面切
                if text_blocks and not in_fence:
                    return "\n\n".join(blocks[:i] + [cls.EXCERPT_SEPARATOR] + blocks[i:])
                break
            if not in_fence and not stripped.startswith("#") and not re.fullmatch(r"\[圖片\d+\]", stripped):
                visible = re.sub(r"!\[[^\]]*\]\([^)]*\)|\[圖片\d+\]|[\s#>*_`|•-]", "", stripped)
                if visible:
                    text_len += len(visible)
                    text_blocks += 1
            if in_fence or text_blocks == 0:
                continue
            nxt = blocks[i + 1].lstrip()
            if list_re.match(nxt) or nxt.startswith("|") or stripped.startswith("|"):
                if text_blocks < cls.EXCERPT_MAX_BLOCKS:
                    continue
            if text_len >= cls.EXCERPT_MIN_CHARS or text_blocks >= cls.EXCERPT_MAX_BLOCKS:
                return "\n\n".join(blocks[: i + 1] + [cls.EXCERPT_SEPARATOR] + blocks[i + 1 :])
        return body

    def _deduplicate_image_sections(self, body: str) -> str:
        """清理重複的「## 文章圖片」區塊，合併為單一區塊並去重圖片引用。"""
        # 用 regex 找出所有 ## 文章圖片 區塊及其後續的圖片引用
        pattern = r'##\s*文章圖片\s*\n'
        sections = list(re.finditer(pattern, body))
        
        if len(sections) <= 1:
            return body  # 無重複，不需處理
        
        # 收集所有圖片引用（去重）
        seen_images: set = set()
        unique_images: list = []
        
        # 從第一個 ## 文章圖片 開始到文末，提取所有 ![...](...)
        first_pos = sections[0].start()
        image_section_text = body[first_pos:]
        
        for match in re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', image_section_text):
            img_path = match.group(2)  # 圖片路徑
            if img_path not in seen_images:
                seen_images.add(img_path)
                unique_images.append(f"![{match.group(1)}]({img_path})")
        
        # 重建：移除所有文章圖片區塊，在文末附加去重後的單一區塊
        clean_body = body[:first_pos].rstrip()
        
        if unique_images:
            clean_body += "\n\n## 文章圖片\n\n" + "\n\n".join(unique_images) + "\n"
        
        return clean_body

    def _collect_all_tags(self) -> Dict[str, int]:
        """Scan all processed articles to collect unique tags and their counts.
        
        讀取 categories 欄位（排除 'Real Estate'），因為 MkDocs Material Blog
        plugin 的分類頁面是依 categories 索引，計數必須與之一致。
        """
        tag_counts = defaultdict(int)
        for file in self.posts_dir.glob("*.md"):
            try:
                content = file.read_text(encoding='utf-8')
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        meta = yaml.safe_load(parts[1])
                        categories = meta.get('categories', [])
                        for c in categories:
                            if c != 'Real Estate':
                                tag_counts[c] += 1
            except:
                continue
        return dict(tag_counts)

    def _generate_authors_file(self):
        """Generate .authors.yml file for mkdocs."""
        authors_map = {}
        for author in self.authors:
            if not author: continue
            authors_map[author] = {
                'name': author,
                'description': 'Real Estate Expert'
            }
        
        # Also add a default or bot author
        authors_map['Landnote AI'] = {
            'name': 'Landnote AI',
            'description': 'Auto-generated Content',
            'avatar': 'https://avatars.githubusercontent.com/u/10137?s=200&v=4' # GitHub icon placeholder
        }

        with open(self.base_dir / 'site_src' / '.authors.yml', 'w', encoding='utf-8') as f:
            yaml.dump(authors_map, f, allow_unicode=True, sort_keys=False)

    def _generate_tags_page(self, tag_counts: Dict[str, int]):
        """Generate tags.md combining both thematic exploration and PDF downloading."""
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        
        content = [
            HIDE_SIDEBARS,
            "# 主題探索與講義下載",
            "",
            "本區彙整了所有的核心考點主題。您可以瀏覽各類別的文章、線上閱讀講義，或直接下載 PDF 離線複習。",
            "",
            "## 綜合大字典",
            '<div class="feature-grid">',
            '    <div class="feature-card c3 is-wide">',
            '        <div class="feature-card__head"><span class="feature-icon">👑</span>'
            f'<span class="pb-count">共 {len(list(self.posts_dir.glob("*.md")))} 篇</span></div>',
            '        <h3>不動產全科大補帖</h3>',
            '        <p>包含全站所有文章，無死角終極精華版。</p>',
            '        <div class="feature-actions">',
            '            <a href="../review/all/" class="md-button">📖 線上閱讀</a>',
            '            <a href="../assets/pdfs/all.pdf" class="md-button md-button--primary" '
            'download="不動產全科大補帖.pdf">📥 下載 PDF</a>',
            '        </div>',
            '    </div>',
            '</div>',
            "",
            "## 分類主題（依收錄文章數排序）",
            '<div class="feature-grid">'
        ]

        if not sorted_tags:
            content.append("*(目前尚無標籤資料)*")
        else:
            import urllib.parse
            icons = ["📘", "📙", "📗", "📕", "📔", "📒", "📓", "📚", "📖", "📜"]
            for idx, (tag, count) in enumerate(sorted_tags):
                safe_tag_slug = tag.lower().replace(' ', '-')
                encoded_tag = urllib.parse.quote(safe_tag_slug)
                blog_url = f"../blog/category/{encoded_tag}/"
                safe_tag_review = tag.replace(' ', '_').replace('/', '_')
                encoded_review = urllib.parse.quote(safe_tag_review)
                review_url = f"../review/{encoded_review}/"
                pdf_url = f"../assets/pdfs/{encoded_review}.pdf"
                icon = icons[idx % len(icons)]

                content.extend([
                    f'    <div class="feature-card c{idx % 4}">',
                    f'        <div class="feature-card__head"><span class="feature-icon">{icon}</span>'
                    f'<span class="pb-count">共 {count} 篇</span></div>',
                    f'        <h3>{tag}</h3>',
                    '        <div class="feature-actions">',
                    f'            <a href="{blog_url}" class="md-button">列表</a>',
                    f'            <a href="{review_url}" class="md-button">閱讀</a>',
                    f'            <a href="{pdf_url}" class="md-button md-button--primary" download="{tag}.pdf">PDF</a>',
                    '        </div>',
                    '    </div>',
                ])
                
        content.append('</div>')
        (self.docs_dir / "tags.md").write_text('\n'.join(content), encoding='utf-8')

    def _generate_mkdocs_config(self):
        """Create mkdocs.yml"""
        config = {
            'site_name': 'Landnote 數位圖書館',
            'site_url': 'https://tomisagoodguy.github.io/landnote/',
            'site_author': 'Landnote AI',
            'repo_url': 'https://github.com/tomisagoodguy/landnote',
            'theme': {
                'name': 'material',
                'language': 'zh-TW',
                # 字型由 extra.css 載入 Huninn（Material 內建 Google Fonts 不含）
                'font': False,
                'features': [
                    'navigation.tabs',
                    'navigation.sections',
                    'navigation.expand',
                    'navigation.tracking',
                    'navigation.indexes',
                    'navigation.top',
                    'navigation.instant',
                    'search.suggest',
                    'search.highlight',
                    'search.share',
                    'content.code.copy',
                    'header.autohide'
                ],
                # 預設跟隨系統；繪本日間在前，夜晚模式為深靛底
                'palette': [
                    {
                        'media': '(prefers-color-scheme: light)',
                        'scheme': 'default',
                        'primary': 'custom',
                        'accent': 'custom',
                        'toggle': {
                            'icon': 'material/weather-night',
                            'name': '切換至夜晚模式'
                        }
                    },
                    {
                        'media': '(prefers-color-scheme: dark)',
                        'scheme': 'slate',
                        'primary': 'custom',
                        'accent': 'custom',
                        'toggle': {
                            'icon': 'material/weather-sunny',
                            'name': '切換至日間模式'
                        }
                    }
                ]
            },
            'extra_css': [
                'stylesheets/extra.css'
            ],
            'extra_javascript': [
                'javascripts/extra.js'
            ],
            'plugins': [
                'search',
                {
                    'blog': {
                        'post_dir': 'blog/posts',
                        'blog_toc': True,
                        'post_url_format': '{date}/{slug}',
                        'archive': True,
                        'categories': True,
                        'tags': True, # Enable native tags too
                        'recent_posts': 5,
                        'pagination_per_page': 10
                    }
                }
            ],
            'markdown_extensions': [
                'admonition',
                'pymdownx.details',
                'pymdownx.superfences',
                'pymdownx.highlight',
                'pymdownx.tabbed',
                'pymdownx.emoji',
                'attr_list',
                'md_in_html',
                {
                    'toc': {
                        'permalink': True,
                        'toc_depth': 3
                    }
                }
            ],
            'nav': [
                {'最新文章': 'blog/'},
                {'主題探索與講義下載': 'tags.md'},
                {'考古題下載': 'exams.md'},
            ]
        }
        
        with open(self.site_src_dir / 'mkdocs.yml', 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)

    def _exam_subjects(self) -> list:
        """掃描地政考古題資料夾，回傳 [(科目, 份數, 最新民國年)]，依份數排序。"""
        exam_dir = self.base_dir / "地政考古題"
        if not exam_dir.exists():
            return []
        subjects = []
        for folder in exam_dir.iterdir():
            if not folder.is_dir() or folder.name == "合併後PDF檔案":
                continue
            years = [int(m.group(1)) for p in folder.glob("*.pdf") if (m := re.match(r"\[(\d+)\]", p.name))]
            if years:
                subjects.append((folder.name, len(years), max(years)))
        return sorted(subjects, key=lambda s: (-s[1], -s[2], s[0]))

    def _generate_homepage(self):
        """首頁：繪本風 hero + 收錄統計 + 三張入口卡；並產生考古題頁。"""
        article_count = len(list(self.posts_dir.glob("*.md"))) if self.posts_dir.exists() else 0
        topic_count = len(self._collect_all_tags())
        exam_subjects = self._exam_subjects()
        exam_count = sum(s[1] for s in exam_subjects)
        latest_year = max((s[2] for s in exam_subjects), default=0)

        content = f"""{HIDE_SIDEBARS}
# Landnote 數位圖書館

<div class="pb-hero">
<h1>Landnote 數位圖書館</h1>
<p>地政、不動產與土地法規的備考筆記，整理成能讀、能印、能帶著走的講義。</p>
<p class="pb-stats">
<span class="pb-stat"><b>{article_count}</b> 篇文章</span>
<span class="pb-stat"><b>{topic_count}</b> 個主題</span>
<span class="pb-stat"><b>{exam_count}</b> 份考古題・更新至 {latest_year} 年</span>
</p>
</div>

<div class="feature-grid">
    <a href="blog/" class="feature-card c0">
        <span class="feature-icon">📰</span>
        <h3>最新文章</h3>
        <p>掌握不動產界最新動態、精闢法條解讀與市場脈動分析。</p>
    </a>
    <a href="tags/" class="feature-card c1">
        <span class="feature-icon">🏷️</span>
        <h3>主題探索與講義下載</h3>
        <p>依主題整理成分類卡片，可一鍵下載<strong>考前衝刺 PDF 講義</strong>。</p>
    </a>
    <a href="exams/" class="feature-card c2">
        <span class="feature-icon">📚</span>
        <h3>地政與估價師考古題</h3>
        <p>高普考、地方特考、不動產估價師歷屆試題，依科目合併成一本，方便整科刷題。</p>
    </a>
</div>
"""
        (self.docs_dir / 'index.md').write_text(content, encoding='utf-8')
        self._generate_exams_page(exam_subjects, exam_count, latest_year)

    def _generate_exams_page(self, subjects: list, total: int, latest_year: int):
        """考古題頁：每科一張卡，可下載整科合併 PDF 或到 GitHub 看單份。"""
        from urllib.parse import quote
        repo = "https://github.com/tomisagoodguy/landnote"
        root = "landnotev3/地政考古題"
        lines = [
            HIDE_SIDEBARS,
            "# 地政與估價師考古題",
            "",
            f"收錄 **{total}** 份地政、不動產估價相關考古題（更新至民國 {latest_year} 年），按科目分類，"
            "來源為高點公職考古題與考選部題庫（專技高考不動產估價師）。"
            "「整科合併」把該科歷屆試題合成一本 PDF，最適合考前整科刷題；"
            "「單份瀏覽」可在 GitHub 逐年下載。每月自動更新。",
            "",
            '<div class="feature-grid">',
        ]
        for idx, (name, count, newest) in enumerate(subjects):
            merged = f"{repo}/raw/main/" + quote(f"{root}/合併後PDF檔案/{name}_合併.pdf")
            folder = f"{repo}/tree/main/" + quote(f"{root}/{name}")
            lines.extend([
                f'    <div class="feature-card c{idx % 4}">',
                f'        <div class="feature-card__head"><span class="pb-count">{count} 份</span>'
                f'<span class="pb-count">最新 {newest} 年</span></div>',
                f'        <h3>{name}</h3>',
                '        <div class="feature-actions">',
                f'            <a href="{merged}" class="md-button md-button--primary">整科合併 PDF</a>',
                f'            <a href="{folder}" class="md-button" target="_blank" rel="noopener">單份瀏覽</a>',
                '        </div>',
                '    </div>',
            ])
        if not subjects:
            lines.append("*(目前尚無考古題資料)*")
        lines.append('</div>')
        (self.docs_dir / 'exams.md').write_text('\n'.join(lines), encoding='utf-8')
