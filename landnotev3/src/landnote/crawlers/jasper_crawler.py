import json
import time
import random
import re
import os
import hashlib
import urllib.parse
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Optional, Set
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import urllib3

from landnote.config import DATA_DIR, LOGS_DIR
from landnote.core.scraper import BaseScraper, ScraperConfig
from landnote.utils.logger import Logger

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class JasperCrawler(BaseScraper):
    """Crawler for Jasper Real Estate articles."""

    def __init__(self, mode: str = "all"):
        super().__init__("JasperCrawler", ScraperConfig())
        self.mode = mode
        
        # Configuration
        self.base_url = "https://www.jasper-realestate.com/posts/"
        self.output_dir = DATA_DIR / "real_estate_articles" / "jasper"
        self.images_dir = self.output_dir / "images"
        self.checkpoint_file = self.output_dir / "scraper_checkpoint.json"
        self.ua = UserAgent()
        
        self.results: List[Dict] = []
        self.scraped_urls: Set[str] = set()
        self.current_page = 1
        
        # Initialize directories
        self.setup_directories()
        
        # Load state if exists
        self.load_checkpoint()
        self.load_previous_results()

        self.logger = Logger.setup_logger("JasperCrawler", LOGS_DIR)

    def setup_directories(self):
        """Create necessary directories."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def load_previous_results(self):
        """Load previously scraped results to avoid duplicates."""
        try:
            # Find the latest results file
            files = sorted(self.output_dir.glob("jasper_articles_*.json"))
            if files:
                latest_file = files[-1]
                with open(latest_file, 'r', encoding='utf-8') as f:
                    self.results = json.load(f)
                
                for article in self.results:
                    if 'link' in article and article['link'] != 'N/A':
                        self.scraped_urls.add(article['link'])
                self.logger.info(f"Loaded {len(self.results)} previous articles from {latest_file.name}")
        except Exception as e:
            self.logger.warning(f"Error loading previous results: {e}")
            self.results = []

    def save_checkpoint(self):
        """Save current progress."""
        checkpoint = {
            'current_page': self.current_page,
            'scraped_urls': list(self.scraped_urls),
            'timestamp': datetime.now().isoformat()
        }
        with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=4)

    def load_checkpoint(self):
        """Load progress from checkpoint."""
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                    checkpoint = json.load(f)
                self.current_page = checkpoint.get('current_page', 1)
                self.scraped_urls = set(checkpoint.get('scraped_urls', []))
                self.logger.info(f"Resumed from checkpoint: Page {self.current_page}")
            except Exception as e:
                self.logger.warning(f"Error loading checkpoint: {e}")

    def run(self):
        """Main execution method."""
        self.logger.info(f"Starting Jasper crawl. Mode: {self.mode}")
        
        if self.mode == "update":
            # In update mode, just check the first few pages
            self.check_for_updates()
        else:
            # In full mode, crawl everything
            self.crawl_all()

    def get_page_soup(self, url: str, max_retries: int = 3) -> Optional[BeautifulSoup]:
        """Fetch page content with retries."""
        for attempt in range(max_retries):
            try:
                headers = {
                    "User-Agent": self.ua.random,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                }
                
                response = requests.get(url, headers=headers, timeout=30, verify=False)
                response.encoding = 'utf-8'
                
                if response.status_code == 200:
                    return BeautifulSoup(response.text, 'html.parser')
                
                self.logger.warning(f"Failed to fetch {url}: Status {response.status_code}")
                
            except Exception as e:
                self.logger.error(f"Error fetching {url}: {e}")
                
            time.sleep(random.uniform(2, 5))
            
        return None

    def crawl_all(self):
        """Crawl all pages."""
        current_url = f"{self.base_url}page/{self.current_page}/" if self.current_page > 1 else self.base_url
        
        while current_url:
            self.logger.info(f"Crawling page {self.current_page}: {current_url}")
            soup = self.get_page_soup(current_url)
            
            if not soup:
                break
                
            articles = self.extract_articles_from_list(soup)
            if not articles:
                self.logger.warning(f"No articles found on page {self.current_page}")
                break
                
            for article in articles:
                if article['link'] in self.scraped_urls and self.mode != "force":
                    continue
                    
                full_article = self.process_article(article)
                if full_article:
                    self.results.append(full_article)
                    self.scraped_urls.add(article['link'])
                    self.save_to_markdown(full_article)
                
                # Checkpoint every 5 articles
                if len(self.results) % 5 == 0:
                    self.save_results()
                    self.save_checkpoint()
                    
                time.sleep(random.uniform(1, 3))

            # Next page
            next_url = self.get_next_page_url(soup)
            if next_url:
                current_url = next_url
                self.current_page += 1
                self.save_checkpoint()
            else:
                self.logger.info("No more pages.")
                break
        
        # Final save
        self.save_results()
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()

    def extract_articles_from_list(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract article previews from a listing page."""
        articles = []
        # Try different selectors as in original script
        items = soup.find_all('article', class_='elementor-post')
        if not items:
            items = soup.find_all('article')
            
        for item in items:
            try:
                title_elem = item.find('h3', class_='elementor-post__title')
                if not title_elem: continue
                
                link_elem = title_elem.find('a')
                if not link_elem: continue
                
                title = link_elem.text.strip()
                link = link_elem['href']
                
                date_elem = item.find('span', class_='elementor-post-date')
                raw_date = date_elem.text.strip() if date_elem else 'N/A'
                date = self.parse_date(raw_date)

                excerpt_elem = item.find('div', class_='elementor-post__excerpt')
                excerpt = "N/A"
                legal_basis = "N/A"
                if excerpt_elem:
                    paragraphs = excerpt_elem.find_all('p')
                    if paragraphs:
                        excerpt = paragraphs[0].text.strip()
                    if len(paragraphs) > 1:
                        legal_basis = paragraphs[1].text.strip().replace("條文依據：", "").strip()

                articles.append({
                    'title': title,
                    'link': link,
                    'date': date,
                    'excerpt': excerpt,
                    'legal_basis': legal_basis
                })
            except Exception as e:
                self.logger.error(f"Error extracting item: {e}")
                
        return articles

    def parse_date(self, raw_date: str) -> str:
        """Parse various date formats."""
        try:
            return datetime.strptime(raw_date, "%Y 年 %m 月 %d 日").strftime("%Y-%m-%d")
        except:
            try:
                return datetime.strptime(raw_date, "%Y-%m-%d").strftime("%Y-%m-%d")
            except:
                return raw_date

    def get_next_page_url(self, soup: BeautifulSoup) -> Optional[str]:
        """Find the next page URL."""
        pagination = soup.find('nav', class_='elementor-pagination')
        if not pagination: return None
        
        next_link = pagination.find('a', string=['下一頁', '»']) or pagination.find('a', class_='next')
        if next_link and 'href' in next_link.attrs:
            return next_link['href']
            
        # Fallback: check page numbers
        current_page_links = pagination.find_all('a', class_='page-numbers')
        for link in current_page_links:
            if link.text.strip().isdigit() and int(link.text.strip()) > self.current_page:
                return link['href']
        return None

    def process_article(self, article_info: Dict) -> Optional[Dict]:
        """Fetch full content and download images."""
        url = article_info['link']
        if url == 'N/A': return None
        
        self.logger.info(f"Processing article: {article_info['title']}")
        soup = self.get_page_soup(url)
        if not soup: return None
        
        # Locate content
        content_div = soup.find('div', class_='elementor-widget-theme-post-content')
        if not content_div:
            # Fallback
            content_div = soup.find('div', class_='entry-content')
            
        if not content_div:
            self.logger.warning(f"Could not find content for {url}")
            return None

        # Process content (download images, clean up)
        # 1. Download images
        for img in content_div.find_all('img'):
            src = img.get('src') or img.get('data-lazy-src')
            if src:
                local_filename = self.download_image(src)
                if local_filename:
                    # Use standard Markdown image syntax
                    new_src = f"images/{local_filename}"
                    img['src'] = new_src
                    # Remove lazy load attributes to avoid confusion
                    if img.has_attr('data-lazy-src'): del img['data-lazy-src']
                    if img.has_attr('srcset'): del img['srcset']
        
        # 2. Extract text (Keep HTML structure or convert to Markdown?)
        # For simplicity and robustness, we keep HTML for complex layouts but wrap in Markdown
        # Or better: Extract text and structure
        
        # Let's try to be smart: Convert HTML to Markdown
        # Or just keep the HTML part that matters
        
        # Remove "Extended Reading" etc.
        for tag in content_div.find_all(['div', 'p']):
            if tag.text.strip() in ["．延伸閱讀", "．免費諮詢", "延伸閱讀", "免費諮詢"]:
                # Remove this and everything after? Or just this?
                # Usually these are at the bottom.
                pass 

        article_info['content_html'] = str(content_div)
        article_info['crawled_at'] = datetime.now().isoformat()
        
        return article_info

    def download_image(self, url: str) -> Optional[str]:
        """Download image to local folder."""
        try:
            if not url.startswith(('http', '//')):
                return None
            if url.startswith('//'):
                url = 'https:' + url
                
            hash_name = hashlib.md5(url.encode()).hexdigest()[:10]
            ext = os.path.splitext(url.split('?')[0])[1]
            if not ext: ext = '.jpg'
            
            filename = f"{hash_name}{ext}"
            filepath = self.images_dir / filename
            
            if filepath.exists():
                return filename
                
            response = requests.get(url, stream=True, verify=False, timeout=10)
            if response.status_code == 200:
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                return filename
        except Exception as e:
            self.logger.warning(f"Failed to download image {url}: {e}")
        return None

    def save_to_markdown(self, article: Dict):
        """Save as Markdown file with YAML frontmatter."""
        safe_title = re.sub(r'[\/*?:"<>|]', '', article['title']).strip()
        filename = f"{article['date']}-{safe_title}.md"
        filepath = self.output_dir / filename
        
        # YAML Frontmatter
        frontmatter = {
            'title': article['title'],
            'date': article['date'],
            'author': 'Jasper',
            'tags': [article['legal_basis']] if article['legal_basis'] != 'N/A' else [],
            'source_url': article['link']
        }
        
        content = "---
" + json.dumps(frontmatter, ensure_ascii=False) + "
---

"
        
        # Add summary/excerpt
        if article['excerpt'] != 'N/A':
            content += f"> {article['excerpt']}

"
            
        # Add content
        # Use simple HTML to Markdown conversion or just dump HTML
        # For better compatibility with MkDocs, we can use md_in_html extension
        content += article['content_html']
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def save_results(self):
        """Save results to JSON."""
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"jasper_articles_{timestamp}.json"
        filepath = self.output_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=4)
    
    def check_for_updates(self):
        """Check for updates (simplified)."""
        # Logic to check first page and stop if article already exists
        self.logger.info("Checking for updates...")
        soup = self.get_page_soup(self.base_url)
        if not soup: return
        
        articles = self.extract_articles_from_list(soup)
        new_found = False
        
        for article in articles:
            if article['link'] not in self.scraped_urls:
                self.logger.info(f"New article found: {article['title']}")
                full = self.process_article(article)
                if full:
                    self.results.append(full)
                    self.scraped_urls.add(article['link'])
                    self.save_to_markdown(full)
                    new_found = True
            else:
                self.logger.info(f"Article already exists: {article['title']}")
        
        if new_found:
            self.save_results()
        else:
            self.logger.info("No new articles found.")
