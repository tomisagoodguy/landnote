import re
import shutil
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
        
        # Copy images if they exist
        src_images = self.source_dir / "images"
        dst_images = self.posts_dir / "images"
        if src_images.exists():
            try:
                shutil.copytree(src_images, dst_images, dirs_exist_ok=True)
            except:
                pass

    def _process_articles(self):
        """Transform raw markdown files into Hugo/MkDocs compatible files."""
        files = list(self.source_dir.glob("*.md"))
        self.logger.info(f"Processing {len(files)} articles...")

        for file_path in files:
            try:
                content = file_path.read_text(encoding='utf-8')
                metadata, body = self._parse_article(content)
                
                # Construct new filename: YYYY-MM-DD-Title.md to help with sorting
                date_str = str(metadata.get('date', '1970-01-01'))
                
                # Collect author for Site Authors
                author = metadata.get('author')
                if author:
                    self.authors.add(author)

                # Sanitize title for filename
                raw_title = metadata.get('title', 'Untitled')
                safe_title = re.sub(r'[\\/*?:"<>|]', '', raw_title).strip()
                new_filename = f"{date_str}-{safe_title}.md"
                
                # Combine categories and tags into categories to ensure indexing by blog plugin
                categories = ['Real Estate']
                tags = metadata.get('tags', [])
                categories.extend(tags)
                
                # Yamaha Frontmatter
                frontmatter = {
                    'title': raw_title,
                    'date': metadata.get('date'), 
                    # 'authors': [author] if author else [], # Disable to avoid build errors
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
                    clean_line = line.strip()[2:]
                    if '作者：' in clean_line:
                        metadata['author'] = clean_line.split('：')[1].strip()
                    elif '發布日期：' in clean_line:
                        date_str = clean_line.split('：')[1].strip()
                        # Normalize date
                        try:
                            if '/' in date_str:
                                dt = datetime.strptime(date_str, "%Y/%m/%d").date()
                            elif '-' in date_str:
                                dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                            elif '年' in date_str: # 2024年05月07日
                                dt = datetime.strptime(date_str, "%Y年%m月%d日").date()
                            else:
                                dt = datetime.now().date() # Fallback
                            metadata['date'] = dt
                        except:
                            metadata['date'] = date_str # Fallback to string if parsing fails
                    elif '關鍵詞：' in clean_line:
                        kws_part = clean_line.split('：')[1].strip()
                        # Split by common separators
                        kws = re.split(r'[,、]', kws_part)
                        metadata['tags'] = [k.strip() for k in kws if k.strip()]
            
            # Decide what to keep in body
            # Skip the initial title line as it's now in frontmatter
            if line.startswith('# ') and not body_started and not in_info_block:
                continue 
                
            if not in_info_block:
                # Fix image paths in body (./images/ -> images/)
                line = line.replace('(./images/', '(images/')
                body_lines.append(line)

        return metadata, '\n'.join(body_lines).strip()

    def _collect_all_tags(self) -> Dict[str, int]:
        """Scan all processed articles to collect unique tags and their counts."""
        tag_counts = defaultdict(int)
        for file in self.posts_dir.glob("*.md"):
            try:
                content = file.read_text(encoding='utf-8')
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        meta = yaml.safe_load(parts[1])
                        tags = meta.get('tags', [])
                        for t in tags:
                            tag_counts[t] += 1
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
        """Generate tags.md with a manual tag cloud link list."""
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        
        content = [
            "# 文章主題索引",
            "",
            "這裡彙整了所有的關鍵字，您可以點擊進入特定主題查看相關文章：",
            "",
            "---",
            ""
        ]
        
        if not sorted_tags:
            content.append("*(目前尚無標籤資料)*")
        else:
            # Generate a nice list with counts
            # In MkDocs Material blog, tags are indexed at /blog/tags/tag-name/
            for tag, count in sorted_tags:
                safe_tag = tag.lower().replace(' ', '-')
                # MkDocs Material Blog default category URL pattern
                url = f"../blog/category/{safe_tag}/"
                content.append(f"-   [:material-tag-outline: **{tag}**]({url}) ({count})")
        
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
                'features': [
                    'navigation.tabs',
                    'navigation.sections',
                    'navigation.expand',
                    'navigation.tracking', # 捲動時自動追蹤標題
                    'navigation.indexes',
                    'search.suggest',
                    'search.highlight',
                    'content.code.copy',
                    'navigation.top', # 回到頂部按鈕
                ],
                'palette': [
                    {
                        'scheme': 'default', 
                        'primary': 'indigo', 
                        'accent': 'indigo', 
                        'toggle': {
                            'icon': 'material/brightness-7', 
                            'name': '切換至深色模式'
                        }
                    },
                    {
                        'scheme': 'slate', 
                        'primary': 'indigo', 
                        'accent': 'indigo',
                        'toggle': {
                            'icon': 'material/brightness-4', 
                            'name': '切換至淺色模式'
                        }
                    }
                ]
            },
            'plugins': [
                'search',
                {
                    'blog': {
                        'post_dir': 'blog/posts',
                        'blog_toc': True,
                        'post_url_format': '{date}/{slug}',
                        'archive': True, # 顯示月份封存
                        'categories': True, # 顯示分類
                        'recent_posts': 5, # 顯示最近 5 篇文章
                    }
                }
            ],
            'markdown_extensions': [
                'admonition',
                'pymdownx.details',
                'pymdownx.superfences',
                'pymdownx.highlight',
                'attr_list',
                'md_in_html',
                {
                    'toc': {
                        'permalink': True, # 標題旁增加連結圖示
                        'toc_depth': 3
                    }
                }
            ],
            'nav': [
                {'首頁': 'index.md'},
                {'最新文章': 'blog/'},
                {'主題索引': 'tags.md'}, # Direct link to tags page
                {'考古題下載': 'exams.md'},
            ]
        }
        
        with open(self.site_src_dir / 'mkdocs.yml', 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)

    def _generate_homepage(self):
        """Create a nice landing page."""
        content = """# 歡迎來到 Landnote 數位圖書館



## 🚀 開始學習

- **[👉 瀏覽最新文章](blog/)**：按時間排序，掌握最新動態。
- **[👉 搜尋特定主題](tags.md)**：利用標籤雲進行專題研讀。

---
*Created with :heart: by Landnote AI*
"""
        (self.docs_dir / 'index.md').write_text(content, encoding='utf-8')
        
        # Create a placeholder exams page
        (self.docs_dir / 'exams.md').write_text("# 考古題下載專區\n\n請至 GitHub Repository 的 [data 資料夾](../data) 下載 PDF 檔案。", encoding='utf-8')
