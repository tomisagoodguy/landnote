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
        
        # Create stylesheets directory
        styles_dir = self.docs_dir / "stylesheets"
        styles_dir.mkdir(exist_ok=True)
        self._write_extra_css(styles_dir / "extra.css")

        # Copy images if they exist
        src_images = self.source_dir / "images"
        dst_images = self.posts_dir / "images"
        if src_images.exists():
            try:
                shutil.copytree(src_images, dst_images, dirs_exist_ok=True)
            except:
                pass

    def _write_extra_css(self, path: Path):
        """Write professional CSS for that 'WOW' factor."""
        css = """
:root {
  --md-primary-fg-color: #0c111d;
  --md-primary-bg-color: #ffffff;
  --md-accent-fg-color: #7c3aed;
}

[data-md-color-scheme="slate"] {
  --md-primary-fg-color: #0c111d;
  --md-accent-fg-color: #a78bfa;
  --md-default-fg-color: #ffffff;
  --md-default-bg-color: #0c111d;
  --md-typeset-color: #ffffff;
  --md-typeset-a-color: #ffffff;
}

/* Force everything in typeset and nav to be white in dark mode */
[data-md-color-scheme="slate"] .md-typeset,
[data-md-color-scheme="slate"] .md-nav,
[data-md-color-scheme="slate"] .md-nav__link,
[data-md-color-scheme="slate"] .md-typeset a,
[data-md-color-scheme="slate"] .md-typeset h1,
[data-md-color-scheme="slate"] .md-typeset h2,
[data-md-color-scheme="slate"] .md-typeset h3,
[data-md-color-scheme="slate"] .md-typeset li,
[data-md-color-scheme="slate"] .md-typeset strong,
[data-md-color-scheme="slate"] .toclink,
[data-md-color-scheme="slate"] .headerlink,
[data-md-color-scheme="slate"] .md-meta__link,
[data-md-color-scheme="slate"] .md-post__title a {
  color: #ffffff !important;
}

[data-md-color-scheme="slate"] .md-typeset a:hover {
  color: #a78bfa !important;
}

/* Hide tag icons in blog and meta */
.md-post__tags::before,
.md-post__tag-icon,
.md-tag-icon,
[href*="category"]::before {
  display: none !important;
}

/* If the text :material-tag-outline: is visible, hide it. 
   Support both list style and blog tag style */
.md-typeset li a, 
.md-post__tags {
  display: inline-flex;
  align-items: center;
}

[href*="category"] {
  font-size: 0 !important; /* Hide parent text including :material-tag-outline: */
}

[href*="category"] strong,
[href*="category"] span {
  font-size: 0.9rem !important; /* Restore font size for the actual label */
  margin-left: 4px;
}

/* Typography upgrade */
body {
  font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

/* Glassmorphism Hero Section */
.hero-section {
  padding: 4rem 2rem;
  margin-bottom: 2rem;
  border-radius: 1.5rem;
  background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
  color: white;
  text-align: center;
  position: relative;
  overflow: hidden;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
}

.hero-section::before {
  content: "";
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 80%);
  animation: rotate 20s linear infinite;
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.hero-title {
  font-size: 3rem;
  font-weight: 800;
  margin-bottom: 1rem;
  letter-spacing: -0.025em;
  position: relative;
}

.hero-subtitle {
  font-size: 1.25rem;
  opacity: 0.9;
  max-width: 600px;
  margin: 0 auto;
  position: relative;
}

/* Feature Cards */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.5rem;
  margin-top: 3rem;
}

.feature-card {
  padding: 2rem;
  border-radius: 1rem;
  background: var(--md-card-bg-color);
  border: 1px solid rgba(0,0,0,0.05);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  text-decoration: none !important;
  color: inherit !important;
  display: block;
}

.feature-card:hover {
  transform: translateY(-8px);
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
  border-color: var(--md-accent-fg-color);
}

.feature-icon {
  font-size: 2.5rem;
  margin-bottom: 1rem;
  display: block;
}

.feature-card h3 {
  margin: 0 0 0.5rem 0 !important;
  font-weight: 700 !important;
  color: var(--md-typeset-color);
}

.feature-card p {
  margin: 0 !important;
  font-size: 0.95rem;
  color: var(--md-typeset-color);
  opacity: 0.8;
}

/* Custom Tag Cloud */
.tag-item {
  display: inline-flex;
  align-items: center;
  padding: 0.4rem 0.8rem;
  margin: 0.25rem;
  background: rgba(124, 58, 237, 0.1);
  color: #7c3aed;
  border-radius: 2rem;
  font-weight: 600;
  font-size: 0.85rem;
  transition: all 0.2s;
}

.tag-item:hover {
  background: #7c3aed;
  color: white;
}
"""
        path.write_text(css, encoding='utf-8')

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
                # Use ../ since tags.md is at /tags/ and blog is at /blog/
                url = f"../blog/category/{safe_tag}/"
                content.append(f"-   [🏷️ **{tag}**]({url}) ({count})")
        
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
            'plugins': [
                'search',
                {
                    'blog': {
                        'post_dir': 'blog/posts',
                        'blog_toc': True,
                        'post_url_format': '{date}/{slug}',
                        'archive': True,
                        'categories': True,
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
                {'主題索引': 'tags.md'},
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
        <h3>主題索引</h3>
        <p>利用專業標籤雲快速導航，深挖每一個專業不動產領域。</p>
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
