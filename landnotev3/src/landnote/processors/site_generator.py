import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
from collections import defaultdict
import yaml

from landnote.config import ARTICLES_DIR, DATA_DIR, JASPER_DIR, LOGS_DIR
from landnote.processors import exam_bank, exam_reader
from landnote.processors.law_timeline import LawTimeline
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
        # Jasper 文章另成一個 blog 實例，「最新文章」不與高點專欄混在一起
        self.jasper_posts_dir = self.docs_dir / "jasper" / "posts"
        self.logger = Logger.setup_logger("SiteGenerator", LOGS_DIR)
        self.authors = set()
        self.exam_bank_nav = []
        self.exam_reader_nav = []
        self.law_timeline = LawTimeline()
        self.law_notice_count = 0

    def run(self):
        """Main execution method to generate the MkDocs site structure."""
        self.logger.info("Starting Static Site Generation...")
        
        # 1. Prepare directories
        self._prepare_directories()
        
        # 2. Process articles and move to docs/posts with YAML frontmatter
        self._process_articles()
        self._process_jasper_articles()
        if not self.law_timeline:
            self.logger.warning("找不到 law_timeline.json，文章不加法規時效提醒（先跑 main.py laws）")
        self.logger.info(f"Law-change notices added to {self.law_notice_count} articles")

        # 4. Generate tags and authors statistics
        all_tags = self._collect_all_tags()
        
        # 5. Generate tags page
        self._generate_tags_page(all_tags)
        
        # 6. Generate authors file
        self._generate_authors_file()

        # Generate Review Materials (Bulk PDFs per tag and full)
        self._generate_review_materials()

        # 估價師主題題庫（讀 data/exam_bank，nav 要在產生 mkdocs.yml 前得知）
        self.exam_bank_nav = exam_bank.write_pages(
            self.docs_dir, posts_dir=[self.posts_dir, self.jasper_posts_dir], practice=self._practice_readers())
        # 考古題逐題閱讀（需在文章處理後執行，才能比對相關文章）
        self.exam_reader_nav = exam_reader.write_pages(
            self.docs_dir, [self.posts_dir, self.jasper_posts_dir])

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
        (self.docs_dir / "blog" / "index.md").write_text("# 高點不動產專欄\n", encoding="utf-8")
        self.jasper_posts_dir.mkdir(parents=True, exist_ok=True)
        (self.docs_dir / "jasper" / "index.md").write_text("# Jasper 不動產文章\n", encoding="utf-8")

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
        
        for file in self._all_post_files():
            try:
                content = file.read_text(encoding='utf-8')
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    meta = yaml.safe_load(parts[1])
                    body = parts[2]

                    # Fix image paths for the review dir context
                    blog_dir = file.parent.parent.name
                    body = body.replace('(images/', f'(../{blog_dir}/posts/images/')

                    item = {
                        'title': meta.get('title', ''),
                        'date': meta.get('date', ''),
                        'body': body,
                        'categories': meta.get('categories', [])
                    }
                    all_articles.append(item)
                    # 主題講義對應 blog/category 分類頁，只收高點專欄
                    if file.parent == self.posts_dir:
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
        
        # 年度合輯：同一年依發布日期由舊到新，適合按時間順讀
        year_articles = defaultdict(list)
        for a in all_articles:
            year_articles[str(a['date'])[:4]].append(a)
        for year, articles in year_articles.items():
            if year.isdigit():
                articles.sort(key=lambda x: str(x['date']))
                create_merged_doc(f"年度合輯：{year} 年", articles, review_dir / f"year-{year}.md")

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
                body = self._add_law_notice(body, date_str)

                # Write new file
                new_content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n\n" + body
                
                # Fix image paths in body (./images/ -> images/)
                new_content = new_content.replace('(./images/', '(images/')
                
                (self.posts_dir / new_filename).write_text(new_content, encoding='utf-8')
                
            except Exception as e:
                self.logger.error(f"Failed to process {file_path.name}: {e}")

    # WordPress 頁面殘留，整個移除
    JASPER_DROP_TAGS = ("script", "style", "meta", "link", "svg", "form", "button", "iframe")
    # 只保留語意屬性，class／style／data-* 會與網站樣式衝突
    JASPER_KEEP_ATTRS = {"a": {"href"}, "img": {"src", "alt"}, "td": {"colspan", "rowspan"},
                         "th": {"colspan", "rowspan"}}

    def _process_jasper_articles(self):
        """把 jasper_crawler 存的文章（JSON frontmatter + WordPress HTML）轉成部落格文章。

        slug 以來源網址雜湊產生（jasper-xxxxxxxx），網址穩定不受標題變動影響；
        寫入獨立的 jasper/ blog；標籤取「法條依據：民法§179」冒號後的部分；上榜心得不收。
        """
        import hashlib
        import json

        if not JASPER_DIR.exists():
            return
        files = sorted(JASPER_DIR.glob("*.md"))
        self.logger.info(f"Processing {len(files)} Jasper articles...")

        images = JASPER_DIR / "images"
        if images.exists():
            shutil.copytree(images, self.jasper_posts_dir / "images", dirs_exist_ok=True)

        for file_path in files:
            try:
                parts = file_path.read_text(encoding="utf-8").split("---", 2)
                if len(parts) < 3:
                    continue
                meta = json.loads(parts[1])
                title = meta.get("title", "").strip() or file_path.stem
                if "上榜心得" in title:
                    continue
                date = datetime.strptime(meta["date"], "%Y-%m-%d").date()
                source = meta.get("source_url", file_path.name)
                slug = "jasper-" + hashlib.md5(source.encode("utf-8")).hexdigest()[:8]
                # 原站標籤偶有換行夾帶多個條文，先拆行；標籤會成為講義檔名，不可含換行
                pieces = [p for t in meta.get("tags", []) for p in str(t).splitlines()]
                tags = [re.sub(r"\s+", " ", re.split(r"[:：]", p, maxsplit=1)[-1]).strip() for p in pieces]
                tags = [t for t in dict.fromkeys(tags) if t]
                self.authors.add("Jasper")

                body = self._clean_jasper_html(parts[2])
                body = self._add_law_notice(body, str(date))
                if source.startswith("http"):
                    body += f"\n\n---\n\n*原文出處：[Jasper 不動產]({source})*\n"

                frontmatter = {
                    "title": title,
                    "date": date,
                    "slug": slug,
                    "categories": tags,
                    "tags": tags,
                }
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:50]
                out = self.jasper_posts_dir / f"{date}-{slug}-{safe_title}.md"
                out.write_text(
                    "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)
                    + "---\n\n" + body, encoding="utf-8")
            except Exception as e:
                self.logger.error(f"Failed to process Jasper article {file_path.name}: {e}")

    def _clean_jasper_html(self, html: str) -> str:
        """清掉 WordPress 版面雜訊，只留內容結構，讓文章套用網站樣式。"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(self.JASPER_DROP_TAGS):
            tag.decompose()
        for img in soup.find_all("img"):
            # 延遲載入的重複圖（外連網址）移除，保留爬蟲已下載到 images/ 的本機圖
            if not (img.get("src") or "").startswith("images/"):
                img.decompose()
        # WordPress 延遲載入：本機圖（src="images/..."）放在 <noscript> 裡，保留內容只拆外殼
        for tag in soup.find_all(["div", "span", "section", "article", "figure", "font", "noscript"]):
            tag.unwrap()
        # 文末「免費諮詢｜Line 官方帳號｜Facebook 粉絲專頁」推廣區塊
        for tag in soup.find_all(["p", "h2", "h3", "h4", "h5", "h6"]):
            text = tag.get_text(strip=True)
            if "免費諮詢" in text or "Line 官方帳號" in text or "粉絲專頁" in text:
                tag.decompose()
        for tag in soup.find_all("h1"):
            tag.name = "h2"  # 頁面標題已是 h1
        for tag in soup.find_all(True):
            keep = self.JASPER_KEEP_ATTRS.get(tag.name, set())
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in keep}
        for tag in soup.find_all(["p", "h2", "h3", "h4", "h5", "h6", "li", "strong"]):
            if not tag.get_text(strip=True) and not tag.find("img"):
                tag.decompose()

        # 頂層元素各自成段（空行分隔），Markdown 才會把每段 HTML 原樣輸出、摘要分隔也能落在段落邊界。
        # 圖片抽出改成 Markdown 語法另成一段：MkDocs 只會依頁面深度改寫 ![]() 的路徑，
        # 不會改 HTML <img src>，否則文章頁（blog/日期/slug/）與列表頁的相對路徑都會錯。
        blocks = []
        for node in list(soup.contents):
            imgs = [node] if getattr(node, "name", None) == "img" else (
                node.find_all("img") if hasattr(node, "find_all") else [])
            md_imgs = [f"![{img.get('alt', '')}]({img['src']})" for img in imgs]
            for img in imgs:
                img.extract()
            text = str(node).strip()
            if text and (getattr(node, "name", None) is None or node.get_text(strip=True)):
                blocks.append(text)
            blocks.extend(md_imgs)
        return re.sub(r"\n{3,}", "\n\n", "\n\n".join(blocks))

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

    def _add_law_notice(self, body: str, date_str: str) -> str:
        """文中引用的條文在發布日後有修正時，於內文開頭插入提醒。"""
        from datetime import date as _date

        if not self.law_timeline:
            return body
        try:
            published = _date.fromisoformat(date_str[:10])
        except ValueError:
            return body
        notice = self.law_timeline.notice(body, published, f"本文發布（{published}）後，文中引用的")
        if not notice:
            return body
        self.law_notice_count += 1
        block = "\n".join(notice).rstrip()
        return f"{block}\n\n{body}"

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

    def _all_post_files(self) -> List[Path]:
        """兩個 blog（高點專欄、Jasper）的全部文章檔。"""
        return [f for d in (self.posts_dir, self.jasper_posts_dir) for f in sorted(d.glob("*.md"))]

    def _year_counts(self) -> Dict[str, int]:
        """各年度文章數（讀 posts 的 front matter date）。"""
        counts: Dict[str, int] = defaultdict(int)
        for file in self._all_post_files():
            m = re.search(r"^date:\s*'?(\d{4})", file.read_text(encoding='utf-8')[:500], re.M)
            if m:
                counts[m.group(1)] += 1
        return dict(counts)

    def _year_cards(self) -> list:
        """講義頁的年度合輯卡片（對應 review/year-YYYY 與 assets/pdfs/year-YYYY.pdf）。"""
        counts = self._year_counts()
        if not counts:
            return []
        lines = ["## 年度合輯（依發布日期排序）", "",
                 "每年的文章依發布順序合成一本，適合追蹤當年修法與時事考點。", "",
                 '<div class="feature-grid">']
        for idx, year in enumerate(sorted(counts, reverse=True)):
            lines.extend([
                f'    <div class="feature-card c{idx % 4}">',
                f'        <div class="feature-card__head"><span class="feature-icon">🗓️</span>'
                f'<span class="pb-count">共 {counts[year]} 篇</span></div>',
                f'        <h3>{year} 年</h3>',
                '        <div class="feature-actions">',
                f'            <a href="../review/year-{year}/" class="md-button">閱讀</a>',
                f'            <a href="../assets/pdfs/year-{year}.pdf" class="md-button md-button--primary" '
                f'download="Landnote_{year}年合輯.pdf">PDF</a>',
                '        </div>',
                '    </div>',
            ])
        lines.extend(['</div>', ""])
        return lines

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
            f'<span class="pb-count">共 {len(self._all_post_files())} 篇</span></div>',
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
            *self._year_cards(),
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
        self._generate_category_index(sorted_tags)

    def _generate_category_index(self, sorted_tags: List[Tuple[str, int]]):
        """產生 blog/category/ 分類總覽頁；Material blog 只產生各分類頁，總覽路徑原本是 404。"""
        from urllib.parse import quote
        chips = [f'<a class="ap-chip" href="{quote(tag.lower().replace(" ", "-"))}/">{tag}<i>{count}</i></a>'
                 for tag, count in sorted_tags]
        lines = [
            HIDE_SIDEBARS,
            "# 文章分類總覽",
            "",
            f"高點不動產專欄共 {len(sorted_tags)} 個分類，依文章數排序；"
            "要線上閱讀整理好的講義或下載 PDF，請到[主題探索與講義下載](../../tags.md)。",
            "",
            f'<div class="ap-chips">{"".join(chips) or "（目前尚無分類）"}</div>',
        ]
        category_dir = self.docs_dir / "blog" / "category"
        category_dir.mkdir(parents=True, exist_ok=True)
        (category_dir / "index.md").write_text('\n'.join(lines), encoding='utf-8')

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
                *({
                    'blog': {
                        'blog_dir': blog_dir,
                        'post_dir': f'{blog_dir}/posts',
                        'blog_toc': True,
                        'post_url_format': '{date}/{slug}',
                        'archive': True,
                        'categories': True,
                        'tags': True, # Enable native tags too
                        'recent_posts': 5,
                        'pagination_per_page': 10
                    }
                } for blog_dir in ('blog', 'jasper'))
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
                {'最新文章': [{'高點不動產專欄': 'blog/'}, {'Jasper 不動產': 'jasper/'}]},
                {'主題探索與講義下載': 'tags.md'},
                {'考古題下載': [{'地政與估價師': 'exams.md'}, {'法律考古題': 'law-exams.md'}]},
            ]
        }
        if self.exam_reader_nav:
            config['nav'].append({'逐題讀（附詳解）': [{t: p} for t, p in self.exam_reader_nav]})
        if self.exam_bank_nav:
            config['nav'].append({'估價師專區': [{'專區首頁': 'appraiser.md'},
                                              *({t: p} for t, p in self.exam_bank_nav)]})
        else:
            config['nav'].append({'估價師專區': 'appraiser.md'})
        
        with open(self.site_src_dir / 'mkdocs.yml', 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)

    # 考試別：(顯示名稱, 報考資格與等級說明)；順序即頁面與卡片上的排列順序
    EXAM_GROUPS = {
        "高考三級": "公務人員高等考試三級，大學以上畢業可報考，錄取後以薦任第六職等任用。",
        "普考": "公務人員普通考試，高中職以上畢業可報考，錄取後以委任第三職等任用。",
        "地方特考三等": "地方政府公務人員特考，等級比照高考三級，分發至各縣市政府與地政事務所。",
        "地方特考四等": "地方政府公務人員特考，等級比照普考。",
        "地方特考五等": "地方政府公務人員特考，等級比照初考，不限學歷。",
        "初考": "公務人員初等考試，年滿 18 歲即可報考，不限學歷。",
        "專技高考（不動產估價師）": "專門職業及技術人員高等考試，及格取得不動產估價師證書。",
        "國營事業": "台電、台水、台糖、中華郵政、臺灣菸酒、農田水利等事業機構的新進人員甄試。",
    }

    @staticmethod
    def _exam_group(exam: str) -> str:
        """把檔名中的考試別（如「地方政府特考三等-地政」）歸到 EXAM_GROUPS 的分類。"""
        head = exam.split("-", 1)[0]
        if head.startswith("高考三級"):
            return "高考三級"
        if head.startswith("普考"):
            return "普考"
        if head.startswith("地方政府特考"):
            return head.replace("地方政府特考", "地方特考")
        if head.startswith("初考"):
            return "初考"
        if head.startswith("專技高考"):
            return "專技高考（不動產估價師）"
        return "國營事業"

    APPRAISER_GROUP = "專技高考（不動產估價師）"

    # 科目家族：各考試對同一科的名稱不同（土地法規／土地法規概要／土地法大意…），依家族分區呈現。
    # (家族名, 網頁錨點, 比對資料夾名的 regex)；由上而下取第一個命中，順序也是頁面排列順序。
    # 新出現的科目名稱若都沒命中會落到「其他科目」，不會漏列。
    SUBJECT_FAMILIES = [
        ("營建與工程估價", "construction", r"施工|營建|建築營造|建築結構|建管|測量"),  # 須在估價之前
        ("不動產估價", "appraisal", r"估價(理論|實務)?$|^土地估價"),
        ("不動產投資", "investment", r"不動產投資"),
        ("土地經濟與土地政策", "economics", r"經濟學|土地政策"),
        ("土地登記", "registration", r"^土地登記"),
        ("民法", "civil-law", r"民法"),
        ("土地法規與土地行政", "land-law", r"土地法|土地行政"),
        ("土地利用與都市計畫", "land-use", r"利用|使用|開發|都市|環境規劃|產業園區"),
        ("稅法與政府採購", "tax", r"稅|採購"),
        ("國文", "chinese", r"國文"),
        ("共同科目", "common", r"法學|英文|公民|數學|共同科目"),
    ]
    OTHER_FAMILY = ("其他科目", "others")

    # 估價師各科可延伸練習的科目家族（高普考同家族題目可當估價師的額外題量）
    APPRAISER_PRACTICE = {
        "不動產估價理論": ["不動產估價"],
        "不動產估價實務": ["不動產估價"],
        "不動產投資分析": ["不動產投資"],
        "不動產經濟學": ["土地經濟與土地政策"],
        "土地利用法規": ["土地利用與都市計畫"],
        "民法物權與不動產法規": ["民法", "土地法規與土地行政"],
    }
    # 估價師各科的相關文章分類；只列出網站上實際存在的分類
    APPRAISER_TAGS = {
        "不動產估價理論": ["不動產估價", "不動產估價師", "地價", "公告地價", "公告土地現值", "區段地價", "實價登錄"],
        "不動產估價實務": ["不動產估價", "容積移轉", "都市更新", "徵收補償", "公共設施保留地"],
        "不動產投資分析": ["不動產投資分析", "不動產市場", "房價", "信託"],
        "不動產經濟學": ["土地利用與土地政策", "土地政策", "市場失靈", "房價高漲", "通貨膨脹", "囤房稅"],
        "土地利用法規": ["都市計畫", "國土計畫法", "區域計畫法", "非都市土地", "都市更新", "容積移轉",
                     "市地重劃", "區段徵收"],
        "民法物權與不動產法規": ["地上權", "共有物", "典權", "抵押權", "土地法", "平均地權條例",
                         "公寓大廈管理條例", "不動產經紀業管理條例"],
    }
    def _practice_readers(self) -> Dict[str, List[Tuple[str, str]]]:
        """估價師各科 → 延伸練習家族中已有逐題閱讀版的 [(頁面名稱, slug)]。"""
        readers = exam_reader.available()
        return {subject: [(name, slug) for fam in fams for f, slug, name in readers if f == fam]
                for subject, fams in self.APPRAISER_PRACTICE.items()}

    APPRAISER_PRACTICE_SHOWN = 4  # 每科延伸練習最多列幾科，其餘到考古題頁看

    @classmethod
    def _subject_family(cls, subject: str) -> Tuple[str, str]:
        """回傳科目所屬的 (家族名, 錨點)。"""
        for name, anchor, pattern in cls.SUBJECT_FAMILIES:
            if re.search(pattern, subject):
                return name, anchor
        return cls.OTHER_FAMILY

    def _exam_subjects(self) -> list:
        """掃描地政考古題資料夾，回傳 [(科目, 份數, 最新民國年, {考試分類: 份數})]，依份數排序。

        檔名格式為「[民國年][考試-類科][科目].pdf」。
        """
        exam_dir = self.base_dir / "地政考古題"
        if not exam_dir.exists():
            return []
        subjects = []
        for folder in exam_dir.iterdir():
            if not folder.is_dir() or folder.name == "合併後PDF檔案":
                continue
            years, groups = [], defaultdict(int)
            for p in folder.glob("*.pdf"):
                m = re.match(r"\[(\d+)\](?:\[([^\]]+)\])?", p.name)
                if not m:
                    continue
                years.append(int(m.group(1)))
                if m.group(2):
                    groups[self._exam_group(m.group(2))] += 1
            if years:
                subjects.append((folder.name, len(years), max(years), dict(groups)))
        return sorted(subjects, key=lambda s: (-s[1], -s[2], s[0]))

    def _generate_homepage(self):
        """首頁：繪本風 hero + 收錄統計 + 三張入口卡；並產生考古題頁。"""
        article_count = len(self._all_post_files())
        tag_counts = self._collect_all_tags()
        topic_count = len(tag_counts)
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
    <a href="appraiser/" class="feature-card c3">
        <span class="feature-icon">📐</span>
        <h3>不動產估價師專區</h3>
        <p>估價師各科主題題庫、歷屆合併 PDF、高普考延伸練習與相關文章，一頁備齊。</p>
    </a>
</div>
"""
        (self.docs_dir / 'index.md').write_text(content, encoding='utf-8')
        self._generate_exams_page(exam_subjects, exam_count, latest_year)
        self._generate_appraiser_page(exam_subjects, tag_counts)

    def _generate_exams_page(self, subjects: list, total: int, latest_year: int):
        """考古題頁：依科目家族分區，每科一張卡，可下載整科合併 PDF 或到 GitHub 看單份。"""
        lines = [
            HIDE_SIDEBARS,
            "# 地政與估價師考古題",
            "",
            f"收錄 **{total}** 份地政、不動產估價相關考古題（更新至民國 {latest_year} 年），按科目分類，"
            "來源為高點公職考古題與考選部題庫（專技高考不動產估價師）。"
            "「整科合併」把該科歷屆試題合成一本 PDF，最適合考前整科刷題；"
            "「單份瀏覽」可在 GitHub 逐年下載，檔名開頭標有年度與考試別"
            "（如 `[113][高考三級-地政][土地法規]`）。每月自動更新。",
            "",
            *(["想依主題刷題？到 **[估價師主題題庫](exam-bank/index.md)** ——六科專業科目逐題分類，"
               "附各主題出題年度統計。", ""] if self.exam_bank_nav else []),
            "## 收錄考試",
            "",
            "| 考試 | 份數 | 說明 |",
            "|------|-----:|------|",
        ]
        group_totals = defaultdict(int)
        for *_, groups in subjects:
            for group, n in groups.items():
                group_totals[group] += n
        for group, desc in self.EXAM_GROUPS.items():
            if group_totals.get(group):
                lines.append(f"| **{group}** | {group_totals[group]} | {desc} |")
        families = self._group_by_family(subjects)
        lines.extend([
            "",
            "同一科目在不同考試的名稱常有差異（例如高考考「土地法規」、普考考「土地法規概要」），"
            "下方依**科目家族**分區，同家族的題目觀念相通，可以互相當練習題；"
            "每張卡片會標出試題出自哪些考試。",
            "",
            "準備不動產估價師？到 **[估價師專區](appraiser.md)**，六科專業科目的題庫、合併 PDF 與延伸練習都整理在一頁。",
            "",
            "需要民法、行政法等法律科目？到 **[法律考古題](law-exams.md)**，收錄高點法律網 40 多種考試的歷屆試題。",
            "",
            "**科目家族**：" + "・".join(
                f"[{fam}](#{anchor})" for fam, anchor, _ in families),
            "",
        ])
        order = list(self.EXAM_GROUPS)
        for fam, anchor, members in families:
            total_fam = sum(s[1] for s in members)
            lines.extend([
                f"## {fam} {{#{anchor}}}",
                "",
                f"{len(members)} 個科目名稱、共 {total_fam} 份。",
                "",
                '<div class="feature-grid">',
            ])
            for idx, (name, count, newest, groups) in enumerate(members):
                scope = "、".join(f"{g} {groups[g]}" for g in sorted(groups, key=order.index))
                lines.extend([
                    f'    <div class="feature-card c{idx % 4}">',
                    f'        <div class="feature-card__head"><span class="pb-count">{count} 份</span>'
                    f'<span class="pb-count">最新 {newest} 年</span></div>',
                    f'        <h3>{name}</h3>',
                    f'        <p>出自：{scope or "未標示考試別"}</p>',
                    '        <div class="feature-actions">',
                    f'            <a href="{self._merged_pdf_url(name)}" class="md-button md-button--primary">'
                    '整科合併 PDF</a>',
                    f'            <a href="{self._exam_folder_url(name)}" class="md-button" target="_blank" '
                    'rel="noopener">單份瀏覽</a>',
                    '        </div>',
                    '    </div>',
                ])
            lines.extend(['</div>', ""])
        if not subjects:
            lines.append("*(目前尚無考古題資料)*")
        (self.docs_dir / 'exams.md').write_text('\n'.join(lines), encoding='utf-8')
        self._generate_law_exams_page()

    LAW_ROOT = "landnotev3/高點法律考古題"

    def _law_exams(self) -> list:
        """掃描 高點法律考古題/<考試>/<科目>/*.pdf。

        回傳 [(考試, [(科目, 份數, 最早年, 最新年, 合併 PDF 檔名或 None)])]，考試依名稱排序。
        檔名格式為「[民國年]年_[考試]_[科目].pdf」；合併檔在 合併後PDF檔案/<考試>/<考試>_<科目>_*_合併.pdf。
        """
        root = self.base_dir / "高點法律考古題"
        merged_root = root / "合併後PDF檔案"
        if not root.exists():
            return []
        exams = []
        for exam in sorted(p for p in root.iterdir() if p.is_dir() and p != merged_root
                           and not p.name.startswith(('_', '.'))):
            merged = {f.name: f for f in (merged_root / exam.name).glob("*_合併.pdf")}
            rows = []
            for subject in exam.iterdir():
                if not subject.is_dir():
                    continue
                years = [int(m.group(1)) for f in subject.glob("*.pdf")
                         if (m := re.match(r"(\d+)年_", f.name))]
                if not years:
                    continue
                prefix = f"{exam.name}_{subject.name}_"
                merged_name = next((n for n in merged if n.startswith(prefix)), None)
                rows.append((subject.name, len(years), min(years), max(years), merged_name))
            if rows:
                exams.append((exam.name, sorted(rows, key=lambda r: (-r[1], r[0]))))
        return exams

    def _generate_law_exams_page(self):
        """法律考古題頁：依考試分區，每科一列，可下載整科合併 PDF 或到 GitHub 看單份。"""
        from urllib.parse import quote
        exams = self._law_exams()
        total = sum(r[1] for _, rows in exams for r in rows)
        base = f"{self.EXAM_REPO}"
        lines = [
            "---\nhide:\n  - navigation\n---\n",
            "# 法律考古題",
            "",
            f"收錄高點法律網 **{len(exams)}** 種考試、**{total}** 份法律科目考古題，"
            "涵蓋地方特考法制／法律廉政、中華郵政、國營事業法務等。",
            "",
            '!!! note "資料更新狀態"',
            "    來源網站改版後，本區自 **2025 年 4 月** 起未再更新；地政相關考古題請到 "
            "**[地政與估價師考古題](exams.md)**，該區每月自動更新。",
            "",
            "「合併 PDF」把該科歷屆試題合成一本，「單份」可在 GitHub 逐年下載（檔名開頭為民國年）。",
            "",
            "**考試列表**：" + "・".join(f"[{name}](#law-{i})" for i, (name, _) in enumerate(exams)),
            "",
        ]
        for i, (name, rows) in enumerate(exams):
            lines.extend([
                f"## {name} {{#law-{i}}}",
                "",
                "| 科目 | 份數 | 年度（民國） | 下載 |",
                "|------|-----:|------|------|",
            ])
            for subject, count, first, last, merged_name in rows:
                folder = f"{base}/tree/main/" + quote(f"{self.LAW_ROOT}/{name}/{subject}")
                links = [f"[單份]({folder})"]
                if merged_name:
                    pdf = f"{base}/raw/main/" + quote(f"{self.LAW_ROOT}/合併後PDF檔案/{name}/{merged_name}")
                    links.insert(0, f"[**合併 PDF**]({pdf})")
                years = f"{first}" if first == last else f"{first}–{last}"
                cell = subject.replace("|", "／")
                lines.append(f"| {cell} | {count} | {years} | {'・'.join(links)} |")
            lines.append("")
        if not exams:
            lines.append("*(目前尚無法律考古題資料)*")
        (self.docs_dir / 'law-exams.md').write_text('\n'.join(lines), encoding='utf-8')

    EXAM_REPO = "https://github.com/tomisagoodguy/landnote"
    EXAM_ROOT = "landnotev3/地政考古題"

    @classmethod
    def _merged_pdf_url(cls, subject: str) -> str:
        from urllib.parse import quote
        return f"{cls.EXAM_REPO}/raw/main/" + quote(f"{cls.EXAM_ROOT}/合併後PDF檔案/{subject}_合併.pdf")

    @classmethod
    def _exam_folder_url(cls, subject: str) -> str:
        from urllib.parse import quote
        return f"{cls.EXAM_REPO}/tree/main/" + quote(f"{cls.EXAM_ROOT}/{subject}")

    def _group_by_family(self, subjects: list) -> list:
        """把 _exam_subjects 的結果依科目家族分組，回傳 [(家族名, 錨點, [科目…])]。

        家族依總份數排序、「其他科目」殿後；家族內維持原本的份數排序。
        """
        grouped: Dict[Tuple[str, str], list] = defaultdict(list)
        for s in subjects:
            grouped[self._subject_family(s[0])].append(s)
        keys = sorted(grouped, key=lambda k: (k == self.OTHER_FAMILY, -sum(s[1] for s in grouped[k])))
        return [(name, anchor, grouped[(name, anchor)]) for name, anchor in keys]

    def _generate_appraiser_page(self, subjects: list, tag_counts: Dict[str, int]):
        """估價師專區：每科一張卡，集中估價師歷屆、主題題庫、同家族延伸練習與相關文章。"""
        from urllib.parse import quote

        bank_slugs = {subject: slug for subject, slug, _ in exam_bank.SUBJECT_PAGES}
        bank_ready = {p for _, p in self.exam_bank_nav}
        own = [s for s in subjects if s[3].get(self.APPRAISER_GROUP)]
        if not own:  # nav 固定有此頁，沒資料也要產生，避免連結失效
            (self.docs_dir / 'appraiser.md').write_text(
                f"{HIDE_SIDEBARS}\n# 不動產估價師專區\n\n*(目前尚無估價師考古題資料)*\n", encoding='utf-8')
            return
        # 專業科目照題庫順序，國文等其他科殿後
        rank = {subject: i for i, (subject, _, _) in enumerate(exam_bank.SUBJECT_PAGES)}
        own.sort(key=lambda s: (rank.get(s[0], len(rank)), s[0]))
        family_members = {fam: members for fam, _, members in self._group_by_family(subjects)}
        anchors = {fam: anchor for fam, anchor, _ in self.SUBJECT_FAMILIES}
        own_names = {s[0] for s in own}
        appraiser_total = sum(s[3][self.APPRAISER_GROUP] for s in own)
        newest = max(s[2] for s in own)

        # 卡片單位：有題庫的專業科目一科一張；其餘（國文歷年改名成兩個資料夾）依家族合成一張
        cards: list = []
        for s in own:
            if s[0] in rank:
                cards.append((s[0], s[0], [s]))
            else:
                fam = self._subject_family(s[0])[0]
                unit = next((c for c in cards if c[0] == fam), None)
                if unit:
                    unit[2].append(s)
                else:
                    cards.append((fam, fam, [s]))

        n_core = sum(1 for c in cards if c[1] in rank)
        lines = [
            HIDE_SIDEBARS,
            "# 不動產估價師專區",
            "",
            '<p class="ap-lead">專技高考不動產估價師歷屆試題，依科目整理成主題題庫與整科 PDF，'
            '並連到同觀念的高普考題目與老師專欄。</p>',
            '<div class="ap-stats">'
            f'<span class="pb-stat"><b>{appraiser_total}</b> 份試題</span>'
            f'<span class="pb-stat"><b>{n_core}</b> 專業科目</span>'
            f'<span class="pb-stat">更新至 <b>{newest}</b> 年</span>'
            '</div>',
            "",
            '<div class="ap-grid">',
        ]
        for idx, (title, key, members) in enumerate(cards):
            n_own = sum(s[3][self.APPRAISER_GROUP] for s in members)
            latest = max(s[2] for s in members)
            buttons = []
            slug = bank_slugs.get(key)
            if slug and f"{exam_bank.BANK_DIR}/{slug}.md" in bank_ready:
                buttons.append(f'<a href="../{exam_bank.BANK_DIR}/{slug}/" class="md-button md-button--primary">'
                               '主題題庫</a>')
            for name, r_slug in self._practice_readers().get(key, []):
                buttons.append(f'<a href="../{exam_reader.READER_ROOT}/{r_slug}/" class="md-button">'
                               f'{name}逐題讀</a>')
            for s in members:
                if len(members) == 1:
                    label = "整科 PDF"
                else:  # 國文（作文與測驗）→「作文與測驗 PDF」，避免按鈕在手機上折行
                    m = re.search(r"[（(]\s*(.+?)\s*[）)]", s[0])
                    label = f"{m.group(1) if m else s[0]} PDF"
                buttons.append(f'<a href="{self._merged_pdf_url(s[0])}" class="md-button">{label}</a>')
            # 資料夾內也有其他考試的同名科目時，提醒合併 PDF 不只估價師題目
            mixed = any(s[1] > s[3][self.APPRAISER_GROUP] for s in members)

            fams = self.APPRAISER_PRACTICE.get(key) or [self._subject_family(key)[0]]
            practice = [s for fam in fams for s in family_members.get(fam, []) if s[0] not in own_names]
            practice.sort(key=lambda s: -s[1])
            chips = [f'<a class="ap-chip" href="{self._merged_pdf_url(s[0])}">{s[0]}<i>{s[1]}</i></a>'
                     for s in practice[:self.APPRAISER_PRACTICE_SHOWN]]
            if len(practice) > self.APPRAISER_PRACTICE_SHOWN:
                more = practice[self.APPRAISER_PRACTICE_SHOWN:]
                fam_link = next((anchors[f] for f in fams if f in anchors), None)
                if fam_link:
                    chips.append(f'<a class="ap-chip ap-chip--more" href="../exams/#{fam_link}">'
                                 f'另 {len(more)} 科 {sum(s[1] for s in more)} 份 →</a>')
            tags = [t for t in self.APPRAISER_TAGS.get(key, []) if tag_counts.get(t)]
            tag_chips = [f'<a class="ap-chip" href="../blog/category/{quote(t.lower().replace(" ", "-"))}/">'
                         f'{t}<i>{tag_counts[t]}</i></a>' for t in tags]

            meta = [f"估價師 {n_own} 份", f"最新 {latest} 年"]
            if len(members) > 1:
                meta.append(f"歷年名稱：{'、'.join(s[0] for s in members)}")
            summary = [f"延伸練習 {len(practice)} 科"] if practice else []
            if tags:
                summary.append(f"相關文章 {len(tags)} 主題")

            lines.extend([
                f'<div class="ap-card c{idx % 4}" id="ap-{slug or idx}">',
                f'<h3>{title}</h3>',
                f'<p class="ap-meta">{"・".join(meta)}</p>',
                '<div class="ap-actions">', *buttons, '</div>',
            ])
            if mixed:
                lines.append('<p class="ap-note">合併 PDF 也收錄其他考試的同名科目</p>')
            if summary:
                lines.append(f'<details class="ap-more"><summary>{"・".join(summary)}</summary>')
                if chips:
                    lines.append(f'<p class="ap-label">延伸練習：同觀念的高普考、特考考古題</p>'
                                 f'<div class="ap-chips">{"".join(chips)}</div>')
                if tag_chips:
                    lines.append(f'<p class="ap-label">相關文章：老師專欄解析</p>'
                                 f'<div class="ap-chips">{"".join(tag_chips)}</div>')
                lines.append('</details>')
            lines.append('</div>')
        lines.extend([
            '</div>',
            "",
            "## 建議讀法",
            "",
            "1. **主題題庫**挑一個主題，限時寫最近三年的題目",
            "2. 標出寫不出來的觀念",
            "3. 展開**相關文章**，讀老師專欄補觀念",
            "4. 用**延伸練習**的高普考題目驗收；考前拿**整科 PDF** 整份模擬",
            "",
            '??? warning "注意法規時效"',
            "    舊題目與舊文章依據的是當年的法規。題目或文章引用的條文若在之後修正過，"
            "頁面上會自動出現「法規可能已修正」提醒並連到現行條文（依全國法規資料庫修法沿革比對）；"
            "沒有提醒不代表內容一定是現行規定，只寫法名未寫條號的引用無法逐條比對。",
        ])
        (self.docs_dir / 'appraiser.md').write_text('\n'.join(lines), encoding='utf-8')
