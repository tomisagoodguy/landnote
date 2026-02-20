import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
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
        
        # 3. Generate authors file
        self._generate_authors_file()

        # 4. Generate mkdocs.yml
        self._generate_mkdocs_config()
        
        # 5. Generate Homepage
        self._generate_homepage()
        
        self.logger.info("Site generation structure completed.")

    def _prepare_directories(self):
        """Clean and create necessary directories."""
        if self.site_src_dir.exists():
            shutil.rmtree(self.site_src_dir)
        self.site_src_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.posts_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy images if they exist
        src_images = self.source_dir / "images"
        dst_images = self.posts_dir / "images"
        if src_images.exists():
            shutil.copytree(src_images, dst_images)

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
                
                # Yamaha Frontmatter
                frontmatter = {
                    'title': raw_title,
                    'date': metadata.get('date'), 
                    # 'authors': [author] if author else [], # Disable to avoid build errors
                    'categories': ['Real Estate'],
                    'tags': metadata.get('tags', [])
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
                body_lines.append(line)

        return metadata, '\n'.join(body_lines).strip()

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

    def _generate_mkdocs_config(self):
        """Create mkdocs.yml"""
        config = {
            'site_name': 'Landnote 數位圖書館',
            'site_url': 'https://your-username.github.io/landnote/',
            'site_author': 'Landnote AI',
            'repo_url': 'https://github.com/your-username/landnote',
            'theme': {
                'name': 'material',
                'language': 'zh-TW',
                'features': [
                    'navigation.tabs',
                    'navigation.sections',
                    'toc.integrate',
                    'search.suggest',
                    'search.highlight',
                    'content.code.copy',
                    'navigation.top',
                ],
                'palette': [
                    {
                        'scheme': 'default', 
                        'primary': 'indigo', 
                        'accent': 'indigo', 
                        'toggle': {
                            'icon': 'material/brightness-7', 
                            'name': 'Switch to dark mode'
                        }
                    },
                    {
                        'scheme': 'slate', 
                        'primary': 'indigo', 
                        'accent': 'indigo',
                        'toggle': {
                            'icon': 'material/brightness-4', 
                            'name': 'Switch to light mode'
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
                    }
                }
            ],
            'markdown_extensions': [
                'admonition',
                'pymdownx.details',
                'pymdownx.superfences',
                'pymdownx.highlight',
                'attr_list',
                'md_in_html'
            ],
            'nav': [
                {'首頁': 'index.md'},
                {'最新文章': 'blog/'},
                {'考古題下載': 'exams.md'},
            ]
        }
        
        with open(self.site_src_dir / 'mkdocs.yml', 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)

    def _generate_homepage(self):
        """Create a nice landing page."""
        content = """# 歡迎來到 Landnote 數位圖書館

這裡匯集了所有不動產相關的專欄文章與考古題，致力於為考生提供最優質的閱讀體驗。

## 📚 特色功能

<div class="grid cards" markdown>

-   :material-book-open-page-variant: **像小說一樣閱讀**
    ---
    所有文章重新排版，支持深色模式，保護您的眼睛。
    
-   :material-tag-multiple: **主題式學習**
    ---
    透過關鍵字標籤，一次將相關主題（如房地合一稅、土地法）學透。

-   :material-clock-time-four-outline: **時間軸瀏覽**
    ---
    掌握最新修法動態與老師見解，不錯過任何重要資訊。

-   :material-magnify: **全文檢索**
    ---
    輸入關鍵字，立即找到您需要的知識點。

</div>

## 🚀 開始學習

- **[👉 瀏覽最新文章](blog/index.md)**：按時間排序，掌握最新動態。
- **[👉 搜尋特定主題](blog/tags.md)**：利用標籤雲進行專題研讀。

---
*Created with :heart: by Landnote AI*
"""
        (self.docs_dir / 'index.md').write_text(content, encoding='utf-8')
        
        # Create a placeholder exams page
        (self.docs_dir / 'exams.md').write_text("# 考古題下載專區\n\n請至 GitHub Repository 的 [data 資料夾](../data) 下載 PDF 檔案。", encoding='utf-8')
