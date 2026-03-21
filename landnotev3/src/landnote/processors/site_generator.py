import re
import shutil
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
import yaml
import json

from landnote.config import ARTICLES_DIR, DATA_DIR, LOGS_DIR
from landnote.utils.logger import Logger

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
            except Exception as e:
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
            "# 主題探索與講義下載",
            "",
            "本區彙整了所有的核心考點主題。您可以瀏覽各類別的文章、線上閱讀講義，或直接下載 PDF 離線複習。",
            "",
            "## 🎯 綜合大字典",
            '<div class="feature-grid" style="margin-top: 1rem; margin-bottom: 3rem;">',
            '    <div class="feature-card" style="background: linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(168, 85, 247, 0.1)); border: 2px solid rgba(168, 85, 247, 0.4); display: flex; flex-direction: column; justify-content: space-between; padding: 1.5rem; cursor: default;">',
            '        <div>',
            '            <span class="feature-icon">👑</span>',
            '            <h3 style="margin-bottom: 0.5rem;">不動產全科大補帖</h3>',
            '            <p style="margin-bottom: 1.5rem;">包含全站所有文章，無死角終極精華版。</p>',
            '        </div>',
            '        <div style="display: flex; gap: 0.5rem;">',
            '            <a href="../review/all/" class="md-button" style="flex: 1; text-align: center; padding: 0.4rem 0; font-size: 0.9rem; margin: 0;">📖 閱讀</a>',
            '            <a href="../assets/pdfs/all.pdf" class="md-button md-button--primary" style="flex: 1; text-align: center; padding: 0.4rem 0; font-size: 0.9rem; margin: 0;" download="不動產全科大補帖.pdf">📥 下載 PDF</a>',
            '        </div>',
            '    </div>',
            '</div>',
            "",
            "## 📚 分類主題 (依收錄文章數排序)",
            '<div class="feature-grid" style="margin-top: 1rem;">'
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

                content.append(f'    <div class="feature-card" style="display: flex; flex-direction: column; justify-content: space-between; padding: 1.5rem; cursor: default;">')
                content.append(f'        <div>')
                content.append(f'            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem;">')
                content.append(f'                <span class="feature-icon" style="font-size: 2rem; margin: 0;">{icon}</span>')
                content.append(f'                <span style="background: rgba(124, 58, 237, 0.1); color: #7c3aed; padding: 0.2rem 0.6rem; border-radius: 1rem; font-size: 0.8rem; font-weight: 600;">共 {count} 篇</span>')
                content.append(f'            </div>')
                content.append(f'            <h3 style="margin-top: 0; margin-bottom: 1.5rem;">{tag}</h3>')
                content.append(f'        </div>')
                content.append(f'        <div style="display: flex; gap: 0.5rem; margin-top: auto;">')
                content.append(f'            <a href="{blog_url}" class="md-button" style="flex: 1; text-align: center; padding: 0.4rem 0; font-size: 0.9rem; margin: 0;">👀 列表</a>')
                content.append(f'            <a href="{review_url}" class="md-button" style="flex: 1; text-align: center; padding: 0.4rem 0; font-size: 0.9rem; margin: 0;">📖 閱讀</a>')
                content.append(f'            <a href="{pdf_url}" class="md-button md-button--primary" style="flex: 1; text-align: center; padding: 0.4rem 0; font-size: 0.9rem; margin: 0;" download="{tag}.pdf">📥 PDF</a>')
                content.append(f'        </div>')
                content.append(f'    </div>')
                
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
                'font': {
                    'text': 'Outfit',
                    'code': 'Fira Code'
                },
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
                'palette': [
                    {
                        'scheme': 'slate', 
                        'primary': 'custom', 
                        'accent': 'indigo',
                        'toggle': {
                            'icon': 'material/brightness-4', 
                            'name': '切換至淺色模式'
                        }
                    },
                    {
                        'scheme': 'default', 
                        'primary': 'custom', 
                        'accent': 'indigo', 
                        'toggle': {
                            'icon': 'material/brightness-7', 
                            'name': '切換至深色模式'
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

    def _generate_homepage(self):
        """Create a minimalist landing page that redirects to blog if needed, 
        or shows a clean 3-button launcher."""
        content = """
<div class="feature-grid">
    <a href="blog/" class="feature-card">
        <span class="feature-icon">📰</span>
        <h3>最新文章</h3>
        <p>掌握不動產界最新動態、精闢法條解讀與市場脈動分析。</p>
    </a>
    <a href="tags/" class="feature-card">
        <span class="feature-icon">🏷️</span>
        <h3>主題探索與講義下載</h3>
        <p>將所有領域整理成分類卡片，支援一鍵打包成 <strong>考前衝刺 PDF 講義</strong>，專為備考而生。</p>
    </a>
    <a href="exams/" class="feature-card">
        <span class="feature-icon">📚</span>
        <h3>考古題下載</h3>
        <p>完整收錄歷屆精華，助您在專業考試中無往不利。</p>
    </a>
</div>
"""
        (self.docs_dir / 'index.md').write_text(content, encoding='utf-8')
        
        # Create a placeholder exams page
        repo_data_url = "https://github.com/tomisagoodguy/landnote/tree/main/landnotev3/data"
        (self.docs_dir / 'exams.md').write_text(f"# 考古題下載專區\n\n請至 GitHub Repository 的 [data 資料夾]({repo_data_url}) 下載 PDF 檔案。", encoding='utf-8')
